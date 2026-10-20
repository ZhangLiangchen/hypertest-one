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


class InteractiveService:
    def __init__(self, config: ClientConfig, api: ApiClient, journal: Journal,
                 host_adapter: HostAdapter):
        self.config, self.api, self.journal, self.host = config, api, journal, host_adapter
        self._tools: dict[str, dict] | None = None
        self._grants: dict[str, dict] = {}
        self._content: dict[str, dict] = {}

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

    async def call(self, name: str, arguments: dict, *, peer_pid: int | None = None) -> dict:
        await self.tools()
        spec = self._tools.get(name)
        if not spec:
            raise ClientError("TOOL_UNSUPPORTED")
        try:
            jsonschema.validate(arguments, spec["inputSchema"])
        except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            raise ClientError("INVALID_TOOL_ARGUMENTS") from exc
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

    async def _write(self, kind: str, key: str, payload: dict, path: str,
                     query_path: str, query: dict, *, device=False, token=None,
                     identity: dict | None = None, request_key: str | None = None) -> dict:
        intent = self.journal.intent(kind, key, payload, identity=identity)
        if intent["state"] != "PENDING":
            try:
                result = await self.api.request("GET", query_path, params=query)
                self._observe(kind, key, result)
                return public(result)
            except ApiError as exc:
                # NOT_FOUND is not evidence that the original POST did not run.
                return {"status": "UNKNOWN", "code": exc.code, "query_required": True}
        self.journal.mark(kind, key, "SENT")
        try:
            result = await self.api.request("POST", path, payload=intent["payload"],
                                            device=device, execution_token=token,
                                            request_key=request_key)
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
        if self.journal.get(kind, key) and result.get("status") not in {"NOT_FOUND", "UNKNOWN"}:
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
