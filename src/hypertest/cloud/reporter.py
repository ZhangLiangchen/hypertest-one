"""Worker-owned reporting through ADR-021; never a SessionTask writer."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from hypertest.api.cloud_schemas import PROFILE, CloudMutation
from hypertest.interactive_client.journal import Journal
from hypertest.sync_core import FrozenIntent, SyncError, TaskSyncCore, digest
from hypertest.sync_core.storage import JournalLedger, SnapshotStore

from .artifacts import read_workspace_file
from .errors import CloudBlocked
from .handoff_rejections import HandoffRejected, LocalRejections, validation_metadata
from .manifests import Handoff


class CloudSyncAdapter:
    def __init__(self, broker):
        self.broker = broker

    async def submit(self, intent: FrozenIntent) -> dict:
        if intent.target["generation"] != self.broker.identity.generation:
            raise CloudBlocked("STALE_FROZEN_GENERATION", "A frozen request cannot change its original lease generation")
        return await self.broker.submit(intent.payload)

    async def reconcile(self, intent: FrozenIntent) -> dict:
        return await self.broker.receipt(intent.key)

    def validate_receipt(self, intent: FrozenIntent, receipt: dict) -> None:
        target, payload = intent.target, intent.payload
        if (receipt.get("status") != "ACCEPTED" or receipt.get("profile") != PROFILE
                or receipt.get("project_id") != target["project_id"]
                or receipt.get("task_id") != target["task_id"]
                or receipt.get("attempt_id") != target["attempt_id"]
                or receipt.get("operation_key") != intent.key
                or receipt.get("operation") != payload["operation"]
                or type(receipt.get("version")) is not int
                or receipt["version"] != intent.expected_version + 1):
            raise SyncError("CLOUD_RECEIPT_MISMATCH")

    async def readback(self, intent: FrozenIntent, receipt: dict) -> dict:
        version = receipt["version"]
        offset, parts, total = 0, [], None
        while True:
            page = await self.broker.page(version=version, offset=offset, limit=24000)
            if (page.get("task_id") != intent.target["task_id"] or page.get("version") != version
                    or page.get("offset") != offset or not isinstance(page.get("content"), str)
                    or type(page.get("total_characters")) is not int):
                raise SyncError("CLOUD_READBACK_MISMATCH")
            if total is None:
                total = page["total_characters"]
            if total != page["total_characters"] or total > 32 * 1024 * 1024:
                raise SyncError("CLOUD_READBACK_SIZE")
            content = page["content"]
            parts.append(content)
            offset += len(content)
            if page.get("complete"):
                if offset != total:
                    raise SyncError("CLOUD_READBACK_INCOMPLETE")
                break
            if page.get("next_offset") != offset or not content:
                raise SyncError("CLOUD_READBACK_INCOMPLETE")
        document = json.loads("".join(parts))
        task = document["task"]
        if (task["id"] != intent.target["task_id"] or task["project_id"] != intent.target["project_id"]
                or task["version"] != version):
            raise SyncError("CLOUD_READBACK_TARGET")
        attempt = next((x for x in document["attempts"] if x["id"] == intent.target["attempt_id"]), None)
        if attempt is None or receipt.get("checkpoint") != attempt["checkpoint"]:
            raise SyncError("CLOUD_CHECKPOINT_MISMATCH")
        payload = intent.payload
        if payload["operation"] == "UPLOAD_ARTIFACT":
            original = await self.broker.artifact(receipt["artifact_id"])
            if (len(original) != payload["byte_count"]
                    or hashlib.sha256(original).hexdigest() != payload["sha256"]
                    or original != base64.b64decode(payload["content_base64"], validate=True)):
                raise SyncError("CLOUD_ARTIFACT_READBACK_MISMATCH")
        if payload["operation"] == "SUBMIT_ASSETS":
            for asset in payload["assets"]:
                matches = [x for x in document["assets"] if x["key"] == asset["key"] and x["kind"] == asset["kind"]]
                latest = max(matches, key=lambda x: x["revision"], default=None)
                if latest is None or any(latest.get(k) != asset.get(k) for k in
                        ("markdown", "details", "title", "artifact_id", "reported_result", "source")):
                    raise SyncError("CLOUD_ASSET_READBACK_MISMATCH")
        return document


class CloudTaskReporter:
    def __init__(self, *, broker, private_root: Path, workspace: Path):
        self.broker, self.workspace = broker, workspace
        private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.journal = Journal(private_root / "submissions.sqlite3")
        self.snapshots = SnapshotStore(private_root / "snapshots", max_bytes=13 * 1024 * 1024)
        self.core = TaskSyncCore(JournalLedger(self.journal), CloudSyncAdapter(broker))
        self.namespace = "cloud:" + broker.attempt_id
        self.version = broker.version
        self.rejections = LocalRejections(private_root / "local-rejections", workspace)

    def rejected(self, key: str) -> bool:
        return self.rejections.get(key) is not None

    def _typed_request(self, handoff: Handoff, payload: dict, source_digest: str) -> dict:
        complete = {**payload, "profile": PROFILE, "project_id": self.broker.project_id,
            "task_id": self.broker.task_id, "attempt_id": self.broker.attempt_id,
            "operation_key": "c:" + digest([self.broker.attempt_id, handoff.key]),
            "expected_version": self.version, "operation": handoff.operation}
        try:
            return TypeAdapter(CloudMutation).validate_python(complete).model_dump(mode="json")
        except ValidationError as error:
            errors = error.errors(include_url=False, include_context=False, include_input=False)
            host_fields = {"profile", "project_id", "task_id", "attempt_id", "operation_key", "expected_version",
                "budget_reservation", "budget_settlement", "usage_seconds", "cost_microunits",
                "all_local_processes_stopped", "local_processes_stopped", "external_operations_reconciled"}
            if handoff.operation == "TRANSITION" or any(
                    any(part in host_fields for part in item.get("loc", ()) if isinstance(part, str)) for item in errors):
                raise  # Host transitions are never Agent-correctable proposals.
            observation = self.rejections.record(handoff.key, source_digest, validation_metadata(error))
            raise HandoffRejected(observation) from None

    def prevalidate_handoff(self, handoff: Handoff, source_digest: str) -> None:
        """Validate shape before stopping a healthy loop or freezing any request.

        Host-only fields below are inert shape placeholders. They are discarded;
        only submit_handoff may materialize real observations and frozen writes.
        """
        if self.pending():
            raise CloudBlocked("REPORT_STREAM_PENDING", "Reconcile original pending delivery before proposal correction")
        if handoff.operation != "TRANSITION" and {"budget_reservation", "budget_settlement"} & handoff.payload.keys():
            raise CloudBlocked("HANDOFF_BUDGET_AUTHORITY", "Only the host Worker owns budget accounting")
        if handoff.operation == "SUBMIT_DELEGATION" and {"status", "terminal_observation"} & handoff.payload.keys():
            raise CloudBlocked("DELEGATION_OBSERVATION_AUTHORITY", "The Worker supplies native delegation terminal observations")
        previous = self.rejections.get(handoff.key)
        if previous is not None:
            raise HandoffRejected(previous)
        payload = dict(handoff.payload)
        if handoff.operation == "UPLOAD_ARTIFACT":
            payload.pop("path", None)
            payload["content_base64"] = ""
        elif handoff.operation == "SUBMIT_DELEGATION":
            payload.update(status="UNKNOWN", terminal_observation=None)
        elif handoff.operation == "REQUEST_INPUT":
            payload.update(local_processes_stopped=False, external_operations_reconciled=False)
        elif handoff.operation == "COMPLETE_ATTEMPT":
            payload.update(usage_seconds=0, cost_microunits=0)
            completion = payload.get("completion_manifest")
            if isinstance(completion, dict):
                payload["completion_manifest"] = {**completion,
                    "all_local_processes_stopped": False, "external_operations_reconciled": False}
        self._typed_request(handoff, payload, source_digest)

    def pending(self) -> list[str]:
        return [row[0] for row in self.journal.db.execute(
            "SELECT key FROM intents WHERE kind=? AND state NOT IN ('READBACK_COMPLETE','REJECTED') ORDER BY rowid",
            (self.namespace,))]

    async def recover(self):
        for key in self.pending():
            frozen = self.snapshots.load(self.namespace, key)
            result = await self.core.deliver(frozen)
            if not result.synced:
                raise CloudBlocked("REPORT_RECONCILIATION_PENDING", "Original report requires receipt/readback reconciliation")
            self.version = result.receipt["version"]

    async def submit_handoff(self, handoff: Handoff, handoff_digest: str, *,
                             usage_seconds=0, cost_microunits=0, runtime_stopped=False,
                             external_operations_reconciled=False, budget_settlement=None,
                             delegation_observation=None):
        key = "c:" + digest([self.broker.attempt_id, handoff.key])
        previous = self.journal.get(self.namespace, key)
        if previous:
            intent = self.snapshots.load(self.namespace, key)
            if intent.target["handoff_digest"] != handoff_digest:
                raise CloudBlocked("HANDOFF_CHANGED", "A published handoff cannot change after its operation is frozen")
        else:
            if self.pending():
                raise CloudBlocked("REPORT_STREAM_PENDING", "Reconcile the original pending report before another mutation")
            if handoff.operation in {"COMPLETE_ATTEMPT", "REQUEST_INPUT"} and (
                    not runtime_stopped or not external_operations_reconciled):
                raise CloudBlocked("RUNTIME_STILL_ACTIVE", "Terminal/input handoff is accepted only after stopping the runtime")
            if handoff.operation == "SUBMIT_DELEGATION" and delegation_observation is None:
                raise CloudBlocked("DELEGATION_CAPABILITY_UNSUPPORTED", "Native delegation requires a Worker-observed official lifecycle terminal")
            self.prevalidate_handoff(handoff, handoff_digest)
            payload = dict(handoff.payload)
            if handoff.operation != "TRANSITION" and {"budget_reservation", "budget_settlement"} & payload.keys():
                raise CloudBlocked("HANDOFF_BUDGET_AUTHORITY", "Only the host Worker owns budget accounting")
            if handoff.operation == "UPLOAD_ARTIFACT":
                original = read_workspace_file(self.workspace, payload.pop("path"))
                if (hashlib.sha256(original).hexdigest() != payload.get("sha256")
                        or len(original) != payload.get("byte_count")):
                    raise CloudBlocked("HANDOFF_ARTIFACT_CHANGED", "Artifact bytes differ from their published manifest")
                payload["content_base64"] = base64.b64encode(original).decode()
            if handoff.operation == "SUBMIT_DELEGATION":
                if delegation_observation is None:
                    raise CloudBlocked("DELEGATION_CAPABILITY_UNSUPPORTED", "Native delegation requires a Worker-observed official lifecycle terminal")
                if {"status", "terminal_observation"} & payload.keys():
                    raise CloudBlocked("DELEGATION_OBSERVATION_AUTHORITY", "The Worker supplies native delegation terminal observations")
                from .delegation import HARNESS_SOURCE, DelegationObservations
                check = DelegationObservations()
                check.accept({**delegation_observation, "state": "RUNNING", "stop_reason": None})
                check.accept(delegation_observation)
                observed = check.terminal(payload.get("native_ref"))
                if payload.get("provider") != observed["provider"]:
                    raise CloudBlocked("DELEGATION_OBSERVATION_CONFLICT", "The contribution names a different native provider")
                payload["status"] = {"completed": "COMPLETED", "aborted": "CANCELLED",
                    "error": "FAILED", "max-tokens": "FAILED", "refusal": "FAILED"}[observed["stop_reason"]]
                payload["terminal_observation"] = {"source": "official-plugin-runtime-reported",
                    "source_commit": HARNESS_SOURCE, "run_id": observed["run_id"],
                    "stop_reason": observed["stop_reason"], "independent_execution_proof": False}
            if handoff.operation in {"COMPLETE_ATTEMPT", "REQUEST_INPUT"}:
                if not runtime_stopped or not external_operations_reconciled:
                    raise CloudBlocked("RUNTIME_STILL_ACTIVE", "Terminal/input handoff is accepted only after stopping the runtime")
                if handoff.operation == "COMPLETE_ATTEMPT":
                    payload.update(usage_seconds=usage_seconds, cost_microunits=cost_microunits)
                    if budget_settlement is not None:
                        payload["budget_settlement"] = budget_settlement
                    payload["completion_manifest"] = {**payload["completion_manifest"],
                        "all_local_processes_stopped": True,
                        "external_operations_reconciled": True}
                else:
                    payload.update(local_processes_stopped=True, external_operations_reconciled=True)
            request = self._typed_request(handoff, payload, handoff_digest)
            await self.broker.validate_payload(request)
            intent = FrozenIntent(self.namespace, key,
                {"project_id": self.broker.project_id, "task_id": self.broker.task_id,
                 "attempt_id": self.broker.attempt_id, "generation": self.broker.identity.generation,
                 "handoff_key": handoff.key, "handoff_digest": handoff_digest}, request, self.version)
            self.snapshots.save(intent)
        result = await self.core.deliver(intent)
        if result.synced:
            self.version = result.receipt["version"]
        return result

    def close(self):
        self.journal.close()
