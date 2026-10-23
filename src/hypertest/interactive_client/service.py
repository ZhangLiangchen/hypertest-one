"""Local typed tool broker. It never calls a Provider or launches an Agent."""
from __future__ import annotations

import base64
import copy
import hashlib
import time
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import jsonschema

from hypertest.interactive_client import EXECUTION_TOOLS
from hypertest.interactive_client.api_client import ApiClient, ApiError
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.host_types import HostAdapter
from hypertest.interactive_client.journal import Journal

PRIVATE_FIELDS = frozenset({"execution_token", "claim_token", "lease_token", "device_token",
                            "integration_token", "host_proof"})


def public(value):
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if k not in PRIVATE_FIELDS}
    if isinstance(value, list):
        return [public(v) for v in value]
    return value


def host_identity(proof: dict) -> dict:
    return {key: value for key, value in proof.items() if key not in {"observed_at", "lifecycle"}}


def validate_sync_receipt(result: dict, key: str, expected_version: int | None = None,
                          prior_task_id: str | None = None, identity: dict | None = None) -> None:
    """A JSON object alone is insufficient to acknowledge this management write."""
    try:
        task_id = str(UUID(result["task_id"]))
        project_id = str(UUID(result["project_id"]))
        version = result["version"]
        identity = identity or {}
        prior_task_id = identity.get("task_id") or prior_task_id
        valid = (result.get("status") == "ACCEPTED" and result.get("idempotency_key") == key
                 and result.get("profile") == "codex-session-task-sync/v1alpha1"
                 and result.get("source") == "AGENT_REPORTED"
                 and type(version) is int and version > 0
                 and isinstance(result.get("provider"), str) and bool(result["provider"])
                 and isinstance(result.get("session_id"), str) and bool(result["session_id"])
                 and ("project_id" not in identity or project_id == str(UUID(identity["project_id"])))
                 and all(result.get(field) == identity[field] for field in ("provider", "session_id") if field in identity)
                 and (expected_version is None or version == expected_version + 1)
                 and (prior_task_id is None or task_id == str(UUID(prior_task_id))))
    except (ValueError, TypeError, KeyError, AttributeError):
        valid = False
    if not valid:
        raise ApiError("INVALID_SYNC_RECEIPT")


def validate_task_page(result: dict, arguments: dict) -> None:
    """Bound a current/versioned JSON read without truncating report content."""
    try:
        UUID(result["task_id"])
        offset, total, version = result["offset"], result["total_chars"], result["version"]
        content, following = result["content"], result["next_offset"]
        valid = (type(version) is int and version > 0
                 and ("version" not in arguments or version == arguments["version"])
                 and type(offset) is int and offset == arguments.get("offset", 0)
                 and type(total) is int and total >= offset
                 and isinstance(content, str) and 0 < len(content) <= min(arguments.get("limit", 24000), 24000)
                 and offset + len(content) <= total
                 and type(result["complete"]) is bool
                 and result["complete"] == (offset + len(content) == total)
                 and ((following is None and result["complete"])
                      or (type(following) is int and following == offset + len(content) and not result["complete"]))
                 and result.get("format") == "application/json"
                 and "source" in result and result.get("source") in {None, "AGENT_REPORTED"}
                 and ("task_id" not in arguments or result["task_id"] == arguments["task_id"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        valid = False
    if not valid:
        raise ClientError("INVALID_TASK_PAGE")


class InteractiveService:
    def __init__(self, config: ClientConfig, api: ApiClient, journal: Journal,
                 host_adapter: HostAdapter):
        self.config, self.api, self.journal, self.host = config, api, journal, host_adapter
        self._tools: dict[str, dict] | None = None
        self._grants: dict[str, dict] = {}
        self._content: dict[str, dict] = {}
        self.coordinator = None
        self.local_capabilities = {
            "explicit_task_binding": bool(config.local_sync.get("enabled")
                and config.local_sync.get("host") == "codex"
                and config.local_sync.get("harness_version") == "0.144.6"),
            "query_only_binding_recovery": True, "target_task_id_reads": True,
            "task_binding_callers": {
                "codex": {"support": "NATIVE_THREAD_ID_REQUIRED", "harness_version": "0.144.6",
                          "metadata_key": "threadId", "per_call_check": True},
                "claude_code": {"support": "UNSUPPORTED"},
                "deepseek_harness": {"support": "UNSUPPORTED"}},
        }
        if config.local_sync.get("enabled"):
            from hypertest.local_sync.coordinator import LocalSyncCoordinator
            self.coordinator = LocalSyncCoordinator(config, api, journal)

    async def tools(self) -> list[dict]:
        if self._tools is None:
            capabilities = await self.api.capabilities()
            values = capabilities.get("tools", []) + capabilities.get("execution_tools", [])
            self._tools = {item["name"]: copy.deepcopy(item) for item in values}
            for name in EXECUTION_TOOLS:
                if name in self._tools:
                    self._tools[name]["inputSchema"].setdefault("properties", {})["request_key"] = {
                        "type": "string", "minLength": 1, "maxLength": 255,
                        "description": "Original transport key for query-only reconciliation. For writes it must equal arguments.idempotency_key.",
                    }
            bind = self._tools.get("hypertest_bind_execution")
            if bind:
                schema = bind["inputSchema"]
                # Host evidence stays private; callers can only select an intent.
                schema.get("properties", {}).pop("host_proof", None)
                schema["required"] = [name for name in schema.get("required", []) if name != "host_proof"]
                schema.setdefault("properties", {}).update({
                    "action": {"type": "string", "enum": ["bind", "continue"], "default": "bind"},
                    "continuation_key": {"type": "string", "minLength": 1, "maxLength": 128},
                })
        return list(self._tools.values())

    async def call(self, name: str, arguments: dict, *, peer_pid: int | None = None,
                   native_caller_context: dict | None = None) -> dict:
        await self.tools()
        spec = self._tools.get(name)
        if not spec:
            raise ClientError("TOOL_UNSUPPORTED")
        try:
            jsonschema.validate(arguments, spec["inputSchema"])
        except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            raise ClientError("INVALID_TOOL_ARGUMENTS") from exc
        if name == "hypertest_sync_task":
            payload = dict(arguments)
            payload.setdefault("provider", "codex")
            if self.coordinator is not None:
                return public(await self.coordinator.submit_full(payload, native_caller_context=native_caller_context))
            lookup = {"project_id": payload["project_id"], "idempotency_key": payload["idempotency_key"]}
            # Reports live on the platform. Keep only lookup identity plus the
            # complete-request digest in this bounded local transport journal.
            compact = {**lookup, "provider": payload["provider"], "session_id": payload["session_id"],
                       "expected_version": payload["expected_version"]}
            return public(await self._write(
                "session-task:" + payload["project_id"], payload["idempotency_key"], payload,
                "interactive/tasks/sync", "interactive/tasks/syncs/by-key",
                lookup, identity=payload, journal_payload=compact,
                receipt_validator=lambda result, intent: validate_sync_receipt(
                    result, payload["idempotency_key"], payload["expected_version"],
                    (intent.get("result") or {}).get("task_id"), payload),
            ))
        if name == "hypertest_bind_task":
            if self.coordinator is None:
                raise ClientError("LOCAL_COORDINATOR_REQUIRED")
            return public(await self.coordinator.bind_task(arguments, native_caller_context=native_caller_context))
        if name == "hypertest_get_task_binding":
            if self.coordinator is None:
                raise ClientError("LOCAL_COORDINATOR_REQUIRED")
            return public(await self.coordinator.get_binding(arguments))
        if name == "hypertest_get_task":
            if "idempotency_key" in arguments:
                kind, key = "session-task:" + arguments["project_id"], arguments["idempotency_key"]
                intent = self.journal.get(kind, key)
                try:
                    result = await self.api.request("GET", "interactive/tasks/syncs/by-key", params=arguments)
                    validate_sync_receipt(result, key,
                                          intent["payload"].get("expected_version") if intent else None,
                                          (intent.get("result") or {}).get("task_id") if intent else None,
                                          intent["payload"] if intent else arguments)
                except ApiError as exc:
                    if intent and intent["state"] not in {"READBACK_COMPLETE", "LEGACY_ACCEPTED_READBACK"}:
                        self.journal.mark(kind, key, "UNKNOWN", intent.get("result"))
                    return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
                self._observe(kind, key, result)
            elif "task_id" in arguments:
                params = dict(arguments)
                task_id = str(UUID(params.pop("task_id")))
                result = await self.api.request("GET", "interactive/tasks/" + task_id, params=params)
                validate_task_page(result, arguments)
            else:
                result = await self.api.request("GET", "interactive/tasks/by-session", params=arguments)
                validate_task_page(result, arguments)
            return public(result)
        if name == "hypertest_submit_task":
            payload = dict(arguments)
            return public(await self._write("submission:" + payload["project_id"], payload["submission_key"], payload,
                                     "interactive/submissions", "interactive/submissions/by-key",
                                     {"project_id": payload["project_id"], "submission_key": payload["submission_key"]}))
        if name == "hypertest_get_submission":
            result = await self.api.request("GET", "interactive/submissions/by-key", params=arguments)
            self._observe("submission:" + arguments["project_id"], arguments["submission_key"], result)
            return public(result)
        if name in {"hypertest_bind_execution", "hypertest_get_execution"}:
            if name == "hypertest_get_execution":
                result = await self.api.request("GET", "interactive/executions/by-key", params=arguments)
                self._observe("attach:" + arguments["run_id"], arguments["attach_key"], result)
                return public(result)
            return await self._bind(arguments, peer_pid)
        if name in EXECUTION_TOOLS:
            return await self._execute(name, arguments, peer_pid)
        routes = {
            "hypertest_get_progress": "progress", "hypertest_list_evidence": "evidence",
            "hypertest_read_evidence": "evidence", "hypertest_list_reports": "reports",
            "hypertest_read_report": "reports",
        }
        route = routes.get(name)
        if not route:
            raise ClientError("TOOL_UNSUPPORTED")
        params = dict(arguments)
        run_id = str(UUID(params.pop("run_id")))
        path = f"interactive/runs/{run_id}/{route}"
        for field in ("object_id", "evidence_id", "report_id"):
            if field in params:
                path += "/" + str(UUID(params.pop(field)))
        result = await self.api.request("GET", path, params=params)
        if name in {"hypertest_read_evidence", "hypertest_read_report"}:
            self._verify_content(result, requested_cursor=arguments.get("cursor"))
        return public(result)

    async def local_hook(self, payload: dict) -> dict:
        """Private local IPC operation, deliberately absent from MCP tools/API."""
        from hypertest.local_sync.hooks import handle_hook
        if self.coordinator is None:
            raise ClientError("LOCAL_COORDINATOR_DISABLED")
        return await handle_hook(self.config, self.coordinator, payload)

    async def local_manifest(self, payload: dict) -> dict:
        from hypertest.local_sync.hooks import submit_manifest
        if payload or self.coordinator is None:
            raise ClientError("LOCAL_COORDINATOR_DISABLED")
        return await submit_manifest(self.config, self.coordinator)

    async def local_source(self, payload: dict) -> dict:
        from hypertest.local_sync.hooks import drain_source
        if (set(payload) != {"session_id"} or not isinstance(payload["session_id"], str)
                or self.coordinator is None):
            raise ClientError("LOCAL_COORDINATOR_DISABLED")
        return await drain_source(self.config, self.coordinator, payload["session_id"])

    async def _write(self, kind: str, key: str, payload: dict, path: str,
                     query_path: str, query: dict, *, device=False, token=None,
                     identity: dict | None = None, request_key: str | None = None,
                     journal_payload: dict | None = None, receipt_validator=None) -> dict:
        intent = self.journal.intent(kind, key, journal_payload if journal_payload is not None else payload,
                                     identity=identity)
        if intent["state"] != "PENDING":
            try:
                result = await self.api.request("GET", query_path, params=query)
                if receipt_validator is not None:
                    receipt_validator(result, intent)
                self._observe(kind, key, result)
                return public(result)
            except ApiError as exc:
                # NOT_FOUND is not evidence that the original POST did not run.
                if receipt_validator is not None:
                    self.journal.mark(kind, key, "UNKNOWN", intent.get("result"))
                return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
        self.journal.mark(kind, key, "SENT")
        try:
            result = await self.api.request("POST", path,
                                            payload=payload if journal_payload is not None else intent["payload"],
                                            device=device, execution_token=token,
                                            request_key=request_key)
            if receipt_validator is not None:
                receipt_validator(result, intent)
        except ApiError as exc:
            if 400 <= exc.status < 500 and exc.status != 408:
                self.journal.mark(kind, key, "REJECTED", {"code": exc.code})
                raise ClientError(exc.code) from exc
            self.journal.mark(kind, key, "UNKNOWN")
            return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
        projected = public(result)
        self.journal.mark(kind, key, "ACKED", projected)
        return result  # Caller consumes secrets privately before final projection.

    def _observe(self, kind: str, key: str, result: dict) -> None:
        record = self.journal.get(kind, key)
        if record and record["state"] not in {"READBACK_COMPLETE", "LEGACY_ACCEPTED_READBACK"} and result.get("status") not in {"NOT_FOUND", "UNKNOWN"}:
            self.journal.mark(kind, key, "ACKED", public(result))

    async def _proof(self, run_id: str, peer_pid: int | None) -> dict:
        assert_peer = getattr(self.host, "assert_peer", None)
        if peer_pid is None or assert_peer is None:
            raise ClientError("TRUSTED_HOST_UNSUPPORTED")
        await assert_peer(peer_pid)
        progress = await self.api.request("GET", f"interactive/runs/{UUID(run_id)}/execution-context")
        local = self.config.workspaces.get(run_id)
        if not local or not self.config.node_id:
            raise ClientError("CONTROLLED_WORKSPACE_REQUIRED")
        selection = progress.get("selection", progress)
        source = progress.get("source", progress)
        if (selection.get("execution_mode") != "LOCAL"
                or selection.get("execution_driver") != "INTERACTIVE_MCP"
                or selection.get("harness_node_id") != self.config.node_id
                or selection.get("source_bundle_transfer_id") != local.get("source_bundle_transfer_id")
                or source.get("repository_url") != local.get("origin")
                or source.get("commit_sha") != local.get("commit_sha")):
            raise ClientError("HOST_SOURCE_SCOPE_REJECTED")
        workspace = Path(local["path"]).expanduser().resolve(strict=True)
        proof = await self.host.attest(project_id=progress["project_id"], run_id=run_id,
                                      node_id=self.config.node_id,
                                      source_transfer_id=local["source_bundle_transfer_id"], workspace=workspace)
        if (proof.get("node_id") != self.config.node_id
                or proof.get("source_bundle_transfer_id") != local["source_bundle_transfer_id"]
                or proof.get("workspace_id") != local["workspace_id"]):
            raise ClientError("HOST_SOURCE_SCOPE_REJECTED")
        return proof

    async def _bind(self, arguments: dict, peer_pid: int | None) -> dict:
        run_id, attach_key = arguments["run_id"], arguments["attach_key"]
        query = {"run_id": run_id, "attach_key": attach_key}
        attach_kind, continue_kind = "attach:" + run_id, "continue:" + run_id
        if arguments.get("action", "bind") == "bind":
            old = self.journal.get(attach_kind, attach_key)
            if old and old["state"] != "PENDING":
                if old["payload"].get("run_id") != run_id:
                    raise ClientError("IDEMPOTENCY_CONFLICT")
                return await self._write(attach_kind, attach_key, old["payload"],
                                         "interactive/executions/bind", "interactive/executions/by-key", query,
                                         device=True, identity={**query, "host_identity": host_identity(old["payload"]["host_proof"])})
            proof = await self._proof(run_id, peer_pid)
            result = await self._write(attach_kind, attach_key,
                                       {"run_id": run_id, "attach_key": attach_key, "host_proof": proof},
                                       "interactive/executions/bind", "interactive/executions/by-key", query,
                                       device=True, identity={**query, "host_identity": host_identity(proof)})
            return public(result)
        continuation_key = arguments.get("continuation_key")
        if not continuation_key:
            raise ClientError("EXPLICIT_CONTINUATION_KEY_REQUIRED")
        continuation_identity = {**query, "continuation_key": continuation_key}
        old = self.journal.get(continue_kind, continuation_key)
        if old and old["state"] != "PENDING":
            return public(await self._write(continue_kind, continuation_key, old["payload"],
                                            "interactive/executions/unused/continue",
                                            "interactive/executions/by-key", query,
                                            identity={**continuation_identity, "host_identity": host_identity(old["payload"]["host_proof"])}))
        found = await self.api.request("GET", "interactive/executions/by-key", params=query)
        execution_id = found.get("execution_id", found.get("id"))
        if not execution_id:
            raise ClientError("EXECUTION_BINDING_REQUIRED")
        proof = await self._proof(run_id, peer_pid)
        result = await self._write(continue_kind, continuation_key,
                                   {"host_proof": proof, "continuation_key": continuation_key},
                                   f"interactive/executions/{UUID(execution_id)}/continue",
                                   "interactive/executions/by-key", query, device=True,
                                   identity={**continuation_identity, "host_identity": host_identity(proof)})
        token = result.get("execution_token")
        if token:
            expires = result.get("expires_at", result.get("expiry", result.get("grant_expires_at")))
            if not isinstance(token, str) or not isinstance(expires, str):
                raise ClientError("INVALID_EXECUTION_AUTHORIZATION")
            expiry = datetime.fromisoformat(expires)
            if expiry.tzinfo is None:
                raise ClientError("INVALID_EXECUTION_AUTHORIZATION")
            remaining = expiry.timestamp() - time.time()
            if remaining <= 0:
                raise ClientError("EXECUTION_AUTHORIZATION_EXPIRED")
            self._grants[execution_id] = {"token": token, "proof": proof,
                                          "deadline": time.monotonic() + remaining}
        return public(result)

    async def _execute(self, name: str, arguments: dict, peer_pid: int | None) -> dict:
        execution_id = str(UUID(arguments["execution_id"]))
        business = arguments["arguments"]
        business_key = business.get("idempotency_key")
        supplied_key = arguments.get("request_key")
        if business_key and supplied_key and supplied_key != business_key:
            raise ClientError("IDEMPOTENCY_CONFLICT")
        # Writes retain their domain identity. The two domain reads use a
        # durable transport identity without changing their business schema.
        key = business_key or supplied_key or uuid4().hex
        kind = "tool:" + execution_id + ":" + name
        old = self.journal.get(kind, key)
        if old and old["state"] != "PENDING":
            result = await self._write(kind, key, {"arguments": business},
                                       "interactive/executions/unused/tools/unused",
                                       f"interactive/executions/{execution_id}/tools/by-key",
                                       {"tool_name": name, "idempotency_key": key})
            return self._tool_result(result, key)
        grant = self._grants.get(execution_id)
        if not grant or grant["deadline"] <= time.monotonic():
            raise ClientError("EXPLICIT_CONTINUATION_REQUIRED")
        assert_peer = getattr(self.host, "assert_peer", None)
        if not assert_peer or peer_pid is None:
            raise ClientError("TRUSTED_HOST_UNSUPPORTED")
        await assert_peer(peer_pid)
        await self.host.assert_live(grant["proof"])
        path = f"interactive/executions/{execution_id}/tools/{name}"
        result = await self._write(kind, key, {"arguments": business}, path,
                                   f"interactive/executions/{execution_id}/tools/by-key",
                                   {"tool_name": name, "idempotency_key": key},
                                   token=grant["token"], request_key=key)
        return self._tool_result(result, key)

    @staticmethod
    def _tool_result(result: dict, request_key: str) -> dict:
        # Transport completion is distinct from domain acceptance. A successful
        # request can contain a business REJECTED result, which stays rejected.
        if result.get("status") == "SUCCEEDED":
            business = result.get("result")
            if not isinstance(business, dict):
                raise ClientError("INVALID_PLATFORM_RESPONSE")
            return {**public(business), "_transport": {
                "request_key": request_key, "request_id": result.get("request_id"),
                "tool_call_id": result.get("tool_call_id"), "status": "SUCCEEDED"}}
        return {**public(result), "request_key": request_key}

    def _verify_content(self, result: dict, *, requested_cursor: str | None) -> None:
        if result.get("schema_version") != "hypertest.interactive-content/v1alpha1":
            raise ClientError("CONTENT_ENVELOPE_REJECTED")
        identity = tuple(result.get(k) for k in ("object_type", "object_id", "run_id", "object_version", "sha256"))
        if (result.get("total_bytes", -1) not in range(0, 8 * 1024 * 1024 + 1)
                or result.get("encoding") not in {"utf-8", "base64"}
                or result.get("untrusted") is not True):
            raise ClientError("CONTENT_ENVELOPE_REJECTED")
        page = result.get("content")
        if not isinstance(page, str):
            raise ClientError("CONTENT_ENVELOPE_REJECTED")
        try:
            data = (page.encode("utf-8") if result["encoding"] == "utf-8"
                    else base64.b64decode(page, validate=True))
        except (ValueError, KeyError) as exc:
            raise ClientError("CONTENT_ENVELOPE_REJECTED") from exc
        prior = self._content.pop(requested_cursor, None) if requested_cursor else None
        if requested_cursor and (not prior or prior["identity"] != identity):
            raise ClientError("CONTENT_VERSION_CONFLICT")
        expected_offset = prior["next_offset"] if prior else 0
        if result.get("offset") != expected_offset:
            raise ClientError("CONTENT_OFFSET_CONFLICT")
        whole = (prior["data"] if prior else b"") + data
        if len(whole) > result["total_bytes"]:
            raise ClientError("CONTENT_INTEGRITY_REJECTED")
        following = result.get("next_cursor")
        if following:
            if not data or result.get("complete") is not False:
                raise ClientError("CONTENT_ENVELOPE_REJECTED")
            if len(self._content) >= 16 or sum(len(p["data"]) for p in self._content.values()) + len(whole) > 16 * 1024 * 1024:
                raise ClientError("CONTENT_READING_LIMIT")
            advance = len(page) if result["encoding"] == "utf-8" else len(data)
            self._content[following] = {"identity": identity, "data": whole,
                                        "next_offset": expected_offset + advance}
        elif (result.get("complete") is not True or len(whole) != result["total_bytes"]
              or hashlib.sha256(whole).hexdigest() != result["sha256"]):
            raise ClientError("CONTENT_INTEGRITY_REJECTED")
