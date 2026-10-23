"""One effective local writer across the entire baseline/merge/send/readback cycle."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import stat
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from pydantic import ValidationError

from hypertest.api.task_schemas import SessionTaskSync, TaskBind, TaskCase, TaskReport
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory, private_read
from hypertest.local_sync.adapter import SCALARS, LocalSyncAdapter, task_document_payload
from hypertest.sync_core import (
    FrozenIntent,
    SyncError,
    TaskSyncCore,
    canonical_json,
    digest,
    merge_present,
)
from hypertest.sync_core.storage import JournalLedger, SnapshotStore


class LocalSyncCoordinator:
    def __init__(self, config, api, journal):
        self.config, self.journal = config, journal
        self.directory = private_directory(config.state_dir / "local-sync")
        self.snapshots = SnapshotStore(self.directory / "approved-snapshots")
        self.adapter = LocalSyncAdapter(api, journal)
        self.core = TaskSyncCore(JournalLedger(journal), self.adapter)
        from hypertest.local_sync.binding import LocalBindingAdapter
        self.binding_adapter = LocalBindingAdapter(api)
        self.binding_core = TaskSyncCore(JournalLedger(journal), self.binding_adapter)
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def writer(self, identity: dict):
        source = {field: identity[field] for field in ("provider", "session_id")}
        key = digest(source)
        async with self._locks.setdefault(key, asyncio.Lock()):
            # OS lock protects separate MCP/hook daemon processes as well. It is
            # intentionally source-only: a second Project cannot bypass it.
            fd = os.open(self.directory / (key + ".lock"),
                         os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ClientError("PRIVATE_FILE_REQUIRED")
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(0.05)
                binding = {**source, "project_id": identity["project_id"]}
                binding_file = self.directory / (key + ".binding.json")
                try:
                    private_create(binding_file, canonical_json(binding).encode())
                except FileExistsError:
                    if json.loads(private_read(binding_file)) != binding:
                        raise ClientError("LOCAL_SOURCE_PROJECT_CONFLICT") from None
                yield
            finally:
                os.close(fd)

    def _pending(self, identity: dict) -> list[tuple[str, str]]:
        # The existing Journal remains the only transmission ledger. Full
        # approved payload snapshots are not duplicated into this compact row.
        rows = self.journal.db.execute(
            "SELECT kind,key,payload FROM intents WHERE (kind LIKE 'session-task:%' OR kind LIKE 'task-bind:%') "
            "AND state NOT IN ('READBACK_COMPLETE','LEGACY_ACCEPTED_READBACK','REJECTED') ORDER BY rowid").fetchall()
        return [(kind, key) for kind, key, raw in rows
                if all(json.loads(raw).get(field) == identity[field]
                       for field in ("provider", "session_id"))]

    async def _settle_pending(self, identity: dict, *, current_key=None, current_namespace=None) -> dict | None:
        for namespace, key in self._pending(identity):
            if key == current_key and namespace == current_namespace:
                continue
            try:
                original = self.snapshots.load(namespace, key)
            except (ClientError, ValueError, KeyError):
                if self.journal.get(namespace, key)["payload"].get("snapshot_schema"):
                    return {"status": "BLOCKED", "code": "ORIGINAL_APPROVED_SNAPSHOT_REQUIRED",
                            "idempotency_key": key, "query_required": True}
                blocked = await self._reconcile_compact_legacy(namespace, key)
                if blocked:
                    return blocked
                continue
            outcome = await (self.binding_core if namespace.startswith("task-bind:") else self.core).deliver(original)
            if not outcome.synced and outcome.state != "REJECTED":
                return self._projection(outcome, key)
            if outcome.synced and namespace.startswith("task-bind:"):
                self._remember_target(original.target)
            if outcome.synced and original.target.get("checkpoint_digest"):
                self._mark_checkpoint(identity, original.target["checkpoint_digest"], key,
                                      outcome.receipt["version"])
        return None

    async def _reconcile_compact_legacy(self, namespace, key):
        """Upgrade old receipts without inventing their unavailable request body.

        The existing compact journal already binds identity + original digest.
        Only original-key GET and a complete fixed accepted-version read are
        permitted. This historical acceptance is deliberately not called a new
        checkpoint whose original approved bytes were compared.
        """
        from hypertest.interactive_client.api_client import ApiError
        from hypertest.interactive_client.service import validate_sync_receipt
        record = self.journal.get(namespace, key)
        target = record["payload"]
        try:
            receipt = await self.adapter.api.request("GET", "interactive/tasks/syncs/by-key", params={
                "project_id": target["project_id"], "idempotency_key": key})
            validate_sync_receipt(receipt, key, target.get("expected_version"),
                                  (record.get("result") or {}).get("task_id"), target)
            self.journal.mark(namespace, key, "ACKED", receipt)
            document = await self.adapter.baseline(target, version=receipt["version"])
            if document is None or document["task"].get("id") != receipt["task_id"]:
                raise SyncError("READBACK_TASK_ID_MISMATCH")
        except (ApiError, ClientError, SyncError, KeyError, ValueError) as exc:
            return {"status": "BLOCKED", "code": getattr(exc, "code", "LEGACY_RECEIPT_READBACK_REQUIRED"),
                    "idempotency_key": key, "query_required": True,
                    "original_request_comparison": "UNAVAILABLE_LEGACY_COMPACT"}
        self.journal.mark(namespace, key, "LEGACY_ACCEPTED_READBACK", receipt)
        return None

    def _mark_checkpoint(self, identity, checkpoint_digest, key, version):
        completed = self.directory / ("checkpoint-" + digest([identity, checkpoint_digest]) + ".json")
        try:
            private_create(completed, canonical_json({"version": version,
                "idempotency_key": key, "checkpoint_digest": checkpoint_digest}).encode())
        except FileExistsError:
            pass

    @staticmethod
    def _projection(outcome, key):
        if outcome.receipt and outcome.state in {"ACCEPTED", "READBACK_COMPLETE"}:
            return {**outcome.receipt, "_sync": {"state": outcome.state,
                    "readback_complete": outcome.synced, "code": outcome.code}}
        return {"status": outcome.state, "idempotency_key": key,
                "code": outcome.code, "query_required": outcome.state in {"SENT", "UNKNOWN"}}

    def _require_native_source(self, payload: dict) -> None:
        """An opted-in file source admits only existing native root bindings.

        This validates source selection, not the caller's native identity. A
        local actor knowing an admitted root id is not authenticated by it.
        Legacy profiles and the explicit GET/reconciliation tools are unchanged.
        """
        settings = self.config.local_sync
        if not settings.get("artifact_source"):
            return
        from hypertest.local_sync.hosts import HOST_PROVIDERS
        from hypertest.local_sync.sources import source_binding
        try:
            expected = {"project_id": str(UUID(settings["project_id"])),
                        "provider": HOST_PROVIDERS[settings["host"]],
                        "session_id": payload["session_id"]}
            supplied = {"project_id": str(UUID(str(payload["project_id"]))),
                        "provider": payload["provider"], "session_id": payload["session_id"]}
            if supplied != expected:
                raise ClientError("LOCAL_NATIVE_SOURCE_IDENTITY_MISMATCH")
            _, record, _ = source_binding(self.config, {
                "session_id": supplied["session_id"],
                "cwd": settings["artifact_source"]["workspace"]}, create=False)
            if record["identity"] != supplied:
                raise ClientError("LOCAL_NATIVE_SOURCE_IDENTITY_MISMATCH")
        except (KeyError, TypeError, ValueError) as exc:
            raise ClientError("LOCAL_NATIVE_SOURCE_CONFIGURATION_REQUIRED") from exc

    def _target_path(self, identity):
        source = {field: identity[field] for field in ("provider", "session_id")}
        return self.directory / (digest(source) + ".task.json")

    def _remember_target(self, identity):
        selected = {field: identity[field] for field in ("project_id", "provider", "session_id", "task_id")}
        path = self._target_path(identity)
        try:
            private_create(path, canonical_json(selected).encode())
        except FileExistsError:
            if json.loads(private_read(path)) != selected:
                raise ClientError("LOCAL_TARGET_TASK_CONFLICT") from None

    async def _target(self, identity, *, supplied_task_id=None):
        path = self._target_path(identity)
        if path.exists():
            target = json.loads(private_read(path))
            if (any(target[field] != identity[field] for field in ("project_id", "provider", "session_id"))
                    or (supplied_task_id is not None and target["task_id"] != supplied_task_id)):
                raise ClientError("LOCAL_TARGET_TASK_CONFLICT")
            return target
        # A current scoped server read confirms an existing legacy source.
        # Missing new fields mean a historical BOUND auto-task, never a new root.
        baseline = await self.adapter.baseline(identity, allow_unsynced=True)
        if baseline is None:
            raise ClientError("TASK_BINDING_REQUIRED")
        task = baseline["task"]
        if task.get("binding_required", False):
            raise ClientError("TASK_BINDING_REQUIRED")
        if supplied_task_id is not None and task["id"] != supplied_task_id:
            raise ClientError("LOCAL_TARGET_TASK_CONFLICT")
        target = {**{field: identity[field] for field in ("project_id", "provider", "session_id")},
                  "task_id": task["id"]}
        self._remember_target(target)
        return target

    async def bind_task(self, arguments):
        from hypertest.local_sync.sources import require_native_root
        try:
            payload = TaskBind.model_validate(arguments).model_dump(mode="json")
        except ValidationError as exc:
            raise ClientError("INVALID_TOOL_ARGUMENTS") from exc
        # Source metadata supplied by the model can only select an existing
        # private SessionStart context; it cannot create or override one.
        require_native_root(self.config, payload)
        async with self.writer(payload):
            blocked = await self._settle_pending(payload, current_key=payload["idempotency_key"],
                                                 current_namespace="task-bind:" + payload["project_id"])
            if blocked:
                return blocked
            path = self._target_path(payload)
            if path.exists() and json.loads(private_read(path))["task_id"] != payload["task_id"]:
                raise ClientError("LOCAL_TARGET_TASK_CONFLICT")
            target = {field: payload[field] for field in ("project_id", "provider", "session_id", "task_id")}
            intent = FrozenIntent("task-bind:" + payload["project_id"], payload["idempotency_key"],
                                  target, payload, payload["expected_version"])
            self.snapshots.save(intent)
            previous = self.journal.get(intent.namespace, intent.key)
            if previous and previous["state"] == "READBACK_COMPLETE":
                return await self._binding_query(intent)
            outcome = await self.binding_core.deliver(intent)
            if outcome.synced:
                self._remember_target(target)
            return self._projection(outcome, intent.key)

    async def get_binding(self, arguments):
        from hypertest.interactive_client.api_client import ApiError
        from hypertest.local_sync.binding import validate_binding_receipt
        namespace, key = "task-bind:" + arguments["project_id"], arguments["idempotency_key"]
        record = self.journal.get(namespace, key)
        if record is not None:
            original = self.snapshots.load(namespace, key)
            async with self.writer(original.target):
                # Explicit GET always queries the original receipt with current
                # authorization, even for a cached ACK or definitive rejection.
                try:
                    receipt = await self.binding_adapter.reconcile(original)
                    self.binding_adapter.validate_receipt(original, receipt)
                except ApiError as exc:
                    if record["state"] != "READBACK_COMPLETE":
                        self.journal.mark(namespace, key, "UNKNOWN", record.get("result"))
                    return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
                self.journal.mark(namespace, key, "ACKED", receipt)
                outcome = await self.binding_core.deliver(original)
                if outcome.synced:
                    self._remember_target(original.target)
                return self._projection(outcome, key)
        try:
            receipt = await self.adapter.api.request("GET", "interactive/tasks/bindings/by-key", params=arguments)
            validate_binding_receipt(receipt, key, payload=arguments)
        except ApiError as exc:
            return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
        return receipt

    async def _binding_query(self, intent):
        from hypertest.interactive_client.api_client import ApiError
        try:
            receipt = await self.binding_adapter.reconcile(intent)
            self.binding_adapter.validate_receipt(intent, receipt)
        except ApiError as exc:
            return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
        return {**receipt, "_sync": {"state": "READBACK_COMPLETE", "readback_complete": True, "code": None}}

    async def submit_full(self, payload: dict) -> dict:
        # Preserve the caller's exact body, empty strings, original key/version
        # and no-op acceptance. This is never interpreted as PATCH or rebased.
        payload = dict(payload)
        payload.setdefault("provider", "codex")
        try:
            SessionTaskSync.model_validate(payload)
        except ValidationError as exc:
            raise ClientError("INVALID_TOOL_ARGUMENTS") from exc
        # Before writer admission, snapshots, journal records or API calls.
        self._require_native_source(payload)
        async with self.writer(payload):
            blocked = await self._settle_pending(payload, current_key=payload["idempotency_key"],
                                                 current_namespace="session-task:" + payload["project_id"])
            if blocked:
                return blocked
            namespace, key = "session-task:" + payload["project_id"], payload["idempotency_key"]
            known = self.journal.get(namespace, key)
            if known is not None:
                try:
                    frozen = self.snapshots.load(namespace, key)
                except (ClientError, ValueError, KeyError):
                    if known["payload"].get("snapshot_schema"):
                        return {"status": "BLOCKED", "code": "ORIGINAL_APPROVED_SNAPSHOT_REQUIRED",
                                "idempotency_key": key, "query_required": True}
                    # Historical compact records cannot be refrozen from a new
                    # caller body. Reconcile the original key and pinned view.
                    blocked = await self._reconcile_compact_legacy(namespace, key)
                    if blocked:
                        return blocked
                    return {**self.journal.get(namespace, key)["result"], "_sync": {
                        "state": "LEGACY_ACCEPTED_READBACK", "readback_complete": True,
                        "original_request_comparison": "UNAVAILABLE_LEGACY_COMPACT"}}
                if canonical_json(frozen.payload) != canonical_json(payload):
                    raise ClientError("IDEMPOTENCY_CONFLICT")
                return self._projection(await self.core.deliver(frozen), key)
            target = await self._target(payload, supplied_task_id=payload.get("task_id"))
            # The explicit full body is never silently changed after freezing.
            # New manually bound tasks require the caller's exact target ID.
            if payload.get("task_id") is None:
                document = await self.adapter.baseline(target, allow_unsynced=True)
                if document["task"].get("binding_required", False):
                    raise ClientError("TASK_ID_REQUIRED")
            intent = FrozenIntent("session-task:" + payload["project_id"], payload["idempotency_key"],
                                  target,
                                  payload, payload["expected_version"])
            self.snapshots.save(intent)
            return self._projection(await self.core.deliver(intent), intent.key)

    async def reconcile_source(self, identity: dict) -> dict:
        """Recover original frozen writes without requiring current files."""
        async with self.writer(identity):
            blocked = await self._settle_pending(identity)
            return blocked or {"status": "SETTLED", "readback_complete": True}

    async def submit_partial(self, identity: dict, changes: dict, *, clear_fields=(),
                             base_version: int | None, checkpoint_digest: str,
                             initial_fields: dict | None = None,
                             artifact_observation: bool = False) -> dict:
        if not set(changes) <= set(SCALARS) | {"cases", "reports"}:
            raise ClientError("PARTIAL_FIELD_UNSUPPORTED")
        async with self.writer(identity):
            blocked = await self._settle_pending(identity)
            if blocked:
                return blocked
            target = await self._target(identity)
            completed = self.directory / ("checkpoint-" + digest([identity, checkpoint_digest]) + ".json")
            if completed.exists():
                previous = json.loads(private_read(completed))
                return {"status": "UNCHANGED", "version": previous["version"],
                        "readback_complete": True, "checkpoint_already_synced": True}
            baseline = await self.adapter.baseline(target, allow_unsynced=True)
            actual_version = baseline["task"]["version"] if baseline else 0
            if base_version is not None and base_version != actual_version:
                raise ClientError("LOCAL_BASE_VERSION_CONFLICT")
            if baseline:
                original = task_document_payload(baseline)
            else:
                original = {}
                if initial_fields is not None:
                    if set(initial_fields) != set(SCALARS):
                        raise ClientError("NEW_TASK_REQUIRES_EXPLICIT_COMPLETE_FIELDS")
                    changes = {**initial_fields, **changes}
                if not set(SCALARS) <= changes.keys():
                    raise ClientError("NEW_TASK_REQUIRES_EXPLICIT_COMPLETE_FIELDS")
            scalars = {field: value for field, value in changes.items() if field in SCALARS}
            merged = merge_present(original, scalars, clear_fields=clear_fields,
                                   clear_values={"objective": "", "plan_markdown": ""})
            submitted_groups = {}
            for group, model in (("cases", TaskCase), ("reports", TaskReport)):
                additions = changes.get(group, [])
                if len({item.get("key") for item in additions}) != len(additions):
                    raise ClientError("DUPLICATE_ARTIFACT_KEY")
                items = {item["key"]: item for item in original.get(group, [])}
                submitted = []
                for item in additions:
                    if artifact_observation and group == "reports" and item.get("key") in items:
                        # A file edit expresses new Markdown only. Preserve
                        # later explicit MCP semantics (especially FAIL), not
                        # stale defaults from the installation's source policy.
                        item = {**items[item["key"]], "markdown": item["markdown"]}
                    if item.get("key") in items and set(item) != set(model.model_fields):
                        raise ClientError("ARTIFACT_REVISION_REQUIRES_COMPLETE_FIELDS")
                    try:
                        normalized = model.model_validate(item).model_dump(mode="json")
                    except ValidationError as exc:
                        raise ClientError("INVALID_ARTIFACT_REVISION") from exc
                    items[normalized["key"]] = normalized
                    submitted.append(normalized)
                merged[group] = sorted(items.values(), key=lambda item: item["key"])
                submitted_groups[group] = submitted
            comparable = {**original, "cases": sorted(original.get("cases", []), key=lambda item: item["key"]),
                          "reports": sorted(original.get("reports", []), key=lambda item: item["key"])}
            if canonical_json(merged) == canonical_json(comparable):
                return {"status": "UNCHANGED", "version": actual_version, "readback_complete": True}
            # Partial additions needn't repeat old revisions. Wire omissions
            # preserve them; explicit complete task scalars always remain.
            payload = {**target, **{field: merged[field] for field in SCALARS},
                       **submitted_groups, "expected_version": actual_version,
                       "idempotency_key": "hook-" + uuid4().hex}
            try:
                payload = SessionTaskSync.model_validate(payload).model_dump(mode="json")
            except ValidationError as exc:
                raise ClientError("INVALID_APPROVED_MANIFEST") from exc
            target = {**target, "checkpoint_digest": checkpoint_digest}
            if baseline:
                target["task_id"] = baseline["task"]["id"]
            intent = FrozenIntent("session-task:" + identity["project_id"], payload["idempotency_key"],
                                  target, payload, actual_version)
            self.snapshots.save(intent)
            outcome = await self.core.deliver(intent)
            if outcome.synced:
                self._mark_checkpoint(identity, checkpoint_digest, intent.key, outcome.receipt["version"])
            return self._projection(outcome, intent.key)
