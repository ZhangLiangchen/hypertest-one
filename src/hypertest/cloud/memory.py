"""Optional HTTP-only Worker memory broker; no service admin or platform writer.

The parent deliberately publishes bounded memory intents in a separate directory.
This consumer is independent from report collection and TaskSyncCore ordering.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import stat
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.memory import MemoryClient
from hypertest.sync_core import digest

from .artifacts import _write_workspace_metadata, read_workspace_file
from .errors import CloudBlocked
from .private_file import read_private_file

HANDOFF_PROFILE = "hypertest-cloud-memory-handoff/v1alpha1"
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
RESPONSE_BYTES = 60000


def query_protocol_document(task_id: str, attempt_id: str) -> dict:
    """Public current-task affordance; runtime identity and authority stay private."""
    return {"protocol_file": ".hypertest-cloud/memory-protocol/query.json",
        "ready_directory": ".hypertest-cloud/memory-ready",
        "response_directory": ".hypertest-cloud/memory-responses",
        "envelope_example": {"profile": HANDOFF_PROFILE, "task_id": task_id,
            "attempt_id": attempt_id, "key": "query-1", "operation": "QUERY",
            "payload": {"query": "REPLACE_WITH_EXPLICIT_QUESTION", "collection": "main", "limit": 5}},
        "instructions": [
            "Use this current task's precreated directories. Keep profile/task_id/attempt_id/operation unchanged; choose a fresh key and your explicit query, collection main or history, and limit 1..20.",
            "Write the complete envelope atomically as memory-ready/KEY.json, then read memory-responses/KEY.json. The Worker supplies all private authorization and server scope selection.",
            "This file only explains QUERY; it does not grant execution, archive or memory-write permission. Never edit the protocol or invent identity or credentials.",
            "If this protocol or these directories are missing/unavailable, report memory unavailable. Do not search host configuration, another task/attempt, old workspaces or credentials for substitutes."]}


def prepare_query_workspace(workspace: Path, task_id: str, attempt_id: str) -> None:
    """Create the explicit query surface without following Agent-controlled links."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root = cloud = None
    try:
        root = os.open(workspace, flags)
        try:
            os.mkdir(".hypertest-cloud", 0o700, dir_fd=root)
        except FileExistsError:
            pass
        cloud = os.open(".hypertest-cloud", flags, dir_fd=root)
        for name in ("memory-ready", "memory-responses"):
            try:
                os.mkdir(name, 0o700, dir_fd=cloud)
            except FileExistsError:
                pass
            directory = os.open(name, flags, dir_fd=cloud)
            os.close(directory)
    except OSError:
        raise CloudBlocked("MEMORY_PATH_UNSAFE", "Memory query directories must be real directories inside this workspace") from None
    finally:
        if cloud is not None:
            os.close(cloud)
        if root is not None:
            os.close(root)
    _write_workspace_metadata(workspace, "memory-protocol", "query",
        query_protocol_document(task_id, attempt_id), "MEMORY_PROTOCOL")


def bounded_query_response(result: dict) -> dict:
    """Drop whole immutable records, never alter content covered by a digest."""
    if len(json.dumps(result).encode()) <= RESPONSE_BYTES:
        return result
    result = dict(result)
    fields = ("results", "external_results", "history_results")
    for field in fields:
        if isinstance(result.get(field), list):
            result[field] = list(result[field])
    omitted = result.get("omitted_entries", 0)
    result.update(truncated=True, omitted_entries=omitted if type(omitted) is int else 0, response_byte_limit=RESPONSE_BYTES,
        result_status="PARTIAL", budget_notice=(
            "The response budget omitted complete records. Returned content and digests are unchanged. "
            "Results and any correction chain may be incomplete; narrow an explicit query before drawing conclusions."))
    while len(json.dumps(result).encode()) > RESPONSE_BYTES:
        field = next((name for name in reversed(fields) if isinstance(result.get(name), list) and result[name]), None)
        if field is None:
            return {"status": "UNAVAILABLE", "code": "MEMORY_RESPONSE_LIMIT",
                "result_status": "UNAVAILABLE", "collection": result.get("collection", "main"),
                "results": [], "external_results": [], "history_results": [],
                "truncated": True, "omitted_entries": result["omitted_entries"],
                "response_byte_limit": RESPONSE_BYTES, "task_sync_unaffected": True}
        result[field].pop()
        result["omitted_entries"] += 1
    if not any(result.get(field) for field in fields):
        result.update(status="UNAVAILABLE", code="MEMORY_RESPONSE_LIMIT", result_status="UNAVAILABLE")
    return result


class CloudMemoryTransport:
    def __init__(self, broker, settings, *, transport=None):
        self.broker = broker
        url = urlsplit(settings.cloud_memory_api_url)
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or (url.scheme != "https" and not (settings.cloud_memory_allow_insecure_loopback
                    and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))):
            raise CloudBlocked("MEMORY_HTTPS_REQUIRED", "Memory credentials require the private configured HTTPS Gateway")
        token_directory = getattr(settings, "cloud_memory_token_directory", None)
        if token_directory:
            directory = Path(token_directory)
            try:
                info = directory.lstat()
                if (not directory.is_absolute() or ".." in directory.parts
                        or not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                        or info.st_mode & 0o077):
                    raise CloudBlocked("MEMORY_IDENTITY_DIRECTORY_UNSAFE", "Project memory grants require a private host-owned directory")
            except OSError:
                raise CloudBlocked("MEMORY_IDENTITY_DIRECTORY_UNAVAILABLE", "Project memory grants are unavailable") from None
        token_file = (Path(token_directory) / (str(UUID(broker.project_id)) + ".token")
            if token_directory else settings.cloud_memory_token_file)
        # The host owns this directory and each Project grant independently.
        # Agent arguments cannot select paths or borrow another Project token.
        self._token = read_private_file(token_file, max_bytes=4096).decode().strip()
        if not self._token or len(self._token) > 512:
            raise CloudBlocked("MEMORY_IDENTITY_UNAVAILABLE", "Independent memory authorization is required")
        context = ssl.create_default_context(cafile=settings.cloud_memory_ca_file)
        uds = getattr(settings, "cloud_memory_api_socket", None)
        if transport is None and uds:
            transport = httpx.AsyncHTTPTransport(uds=uds, verify=context)
        self.http = httpx.AsyncClient(base_url=settings.cloud_memory_api_url.rstrip("/") + "/",
            verify=context, transport=transport, timeout=settings.cloud_memory_timeout_seconds,
            follow_redirects=False, trust_env=False)

    async def request(self, method, path, *, payload=None, params=None):
        if path not in {"memory/query", "memory/operations", "memory/operations/by-key"} and not re.fullmatch(r"memory/entries/[0-9a-f-]{36}", path):
            raise ApiError("MEMORY_ROUTE_INVALID")
        if method == "POST":
            # Current authority is checked locally and again at the Gateway.
            # Only the private HTTP headers carry lease / work proof.
            await self.broker.assert_current()
        identity = self.broker.identity
        identity_proof = (identity.worker_id, identity.lease_token, identity.generation, identity.work_token)
        request_id = str(uuid4()) if path == "memory/query" else None
        headers = {"Authorization": "Bearer " + self._token,
            "X-Hypertest-Memory-Worker-Id": identity.worker_id,
            "X-Hypertest-Memory-Lease-Token": identity.lease_token,
            "X-Hypertest-Memory-Generation": str(identity.generation),
            "X-Hypertest-Memory-Work-Token": identity.work_token}
        if request_id:
            headers["X-Hypertest-Memory-Request-Id"] = request_id
        try:
            async with self.http.stream(method, path, json=payload, params=params, headers=headers) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 1024 * 1024:
                        raise ApiError("MEMORY_RESPONSE_LIMIT")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ApiError("MEMORY_RESPONSE_INVALID")
                if not 200 <= response.status_code < 300:
                    detail = result.get("detail")
                    code = detail.get("code") if isinstance(detail, dict) else detail
                    if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code):
                        code = "MEMORY_REQUEST_REJECTED"
                    raise ApiError(code, response.status_code)
                if request_id:
                    if result.get("request_id", request_id) != request_id:
                        raise ApiError("MEMORY_RESPONSE_IDENTITY_MISMATCH")
                    # A response received after local fencing or replacement of
                    # this claim must not reach the model, even if HTTP succeeded.
                    await self.broker.assert_current()
                    current = self.broker.identity
                    if (current.worker_id, current.lease_token, current.generation, current.work_token) != identity_proof:
                        raise CloudBlocked("MEMORY_CLAIM_CHANGED", "Original query claim changed during retrieval")
                return result
        except (httpx.TimeoutException, TimeoutError):
            raise ApiError("MEMORY_TIMEOUT") from None
        except httpx.HTTPError:
            raise ApiError("MEMORY_UNAVAILABLE") from None
        except (ValueError, UnicodeError):
            raise ApiError("MEMORY_RESPONSE_INVALID") from None

    async def close(self):
        await self.http.aclose()


class CloudMemoryBridge:
    def __init__(self, broker, transport, private_root: Path, workspace: Path, *, timeout_seconds=5):
        self.broker, self.transport, self.workspace = broker, transport, workspace
        # Operational claims do not spend a business version; this original
        # accepted dispatch snapshot exists before any report is generated.
        self.query_context = {"task_id": broker.task_id, "attempt_id": broker.attempt_id,
            "task_version": broker.version}
        self.query_identity = self._identity()
        prepare_query_workspace(workspace, broker.task_id, broker.attempt_id)
        private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.timeout_seconds = min(timeout_seconds, 5)
        self.client = MemoryClient(transport.request, private_root / "memory.sqlite3", timeout_seconds=self.timeout_seconds)
        self.seen: dict[str, str] = {}

    def _identity(self):
        identity = self.broker.identity
        return (self.broker.project_id, self.broker.task_id, self.broker.attempt_id,
            identity.worker_id, identity.lease_token, identity.generation, identity.work_token)

    async def _assert_query_current(self):
        if self._identity() != self.query_identity:
            raise CloudBlocked("MEMORY_CLAIM_CHANGED", "Only the original fixed query claim may read memory")
        await self.broker.assert_current()
        if self._identity() != self.query_identity:
            raise CloudBlocked("MEMORY_CLAIM_CHANGED", "Original query claim changed during authorization")

    async def run(self):
        while True:
            try:
                await self.collect_once()
            except (CloudBlocked, ApiError, OSError, ValueError, TypeError, KeyError):
                # Optional memory failure never interrupts report delivery,
                # runtime progress or the independent fenced task writer.
                pass
            await asyncio.sleep(0.3)

    async def collect_once(self):
        directory = self.workspace / ".hypertest-cloud" / "memory-ready"
        if not directory.exists():
            return
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.workspace.resolve()):
            raise CloudBlocked("MEMORY_PATH_INVALID", "Explicit memory directory must remain inside the workspace")
        paths = sorted(directory.iterdir())
        if len(paths) > 64:
            raise CloudBlocked("MEMORY_COUNT_LIMIT", "Optional memory intents exceed their bounded count")
        for path in paths:
            key = path.stem
            if path.suffix != ".json" or not KEY.fullmatch(key):
                continue
            document = None
            deadline = asyncio.get_running_loop().time() + self.timeout_seconds
            try:
                raw = read_workspace_file(self.workspace, ".hypertest-cloud/memory-ready/" + path.name, max_bytes=65536)
                fingerprint = digest(raw.decode())
                if key in self.seen:
                    # A response is immutable. Changing an intent never causes
                    # new processing or a second candidate POST.
                    continue
                document = json.loads(raw)
                async with asyncio.timeout_at(deadline):
                    result = await self.handle(document, key)
            except TimeoutError:
                result = {"status": "UNAVAILABLE", "code": "MEMORY_TIMEOUT", "task_sync_unaffected": True}
                fingerprint = "UNAVAILABLE"
            except (CloudBlocked, ApiError, ValueError, TypeError, KeyError) as error:
                result = {"status": "REFUSED", "code": getattr(error, "code", "MEMORY_HANDOFF_INVALID"), "task_sync_unaffected": True}
                fingerprint = "REFUSED"
            if isinstance(document, dict) and document.get("operation") == "QUERY":
                result = bounded_query_response(result)
                # Last local fence immediately before publishing model-readable
                # bytes. No stale fetched content is written on refusal.
                try:
                    async with asyncio.timeout_at(deadline):
                        await self._assert_query_current()
                except TimeoutError:
                    result = {"status": "UNAVAILABLE", "code": "MEMORY_TIMEOUT", "task_sync_unaffected": True}
                except (CloudBlocked, ApiError):
                    result = {"status": "REFUSED", "code": "MEMORY_QUERY_FENCED", "task_sync_unaffected": True}
            elif len(json.dumps(result).encode()) > RESPONSE_BYTES:
                result = {"status": "UNAVAILABLE", "code": "MEMORY_RESPONSE_LIMIT", "task_sync_unaffected": True}
            _write_workspace_metadata(self.workspace, "memory-responses", key, result, "MEMORY_RESPONSE")
            self.seen[key] = fingerprint

    async def handle(self, document, key):
        if (not isinstance(document, dict) or set(document) != {"profile", "task_id", "attempt_id", "key", "operation", "payload"}
                or document["profile"] != HANDOFF_PROFILE or document["task_id"] != self.broker.task_id
                or document["attempt_id"] != self.broker.attempt_id or document["key"] != key
                or not isinstance(document["payload"], dict)):
            raise CloudBlocked("MEMORY_HANDOFF_INVALID", "Explicit memory intent must match its original parent task and attempt")
        payload = document["payload"]
        operation = document["operation"]
        if operation == "GET_OPERATION":
            if set(payload) != {"operation_key"} or not isinstance(payload["operation_key"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", payload["operation_key"]):
                raise CloudBlocked("MEMORY_HANDOFF_INVALID", "Recovery needs only the original memory operation key")
            return await self.client.recover(self.broker.project_id, payload["operation_key"])
        if operation == "QUERY":
            if not payload.keys() <= {"query", "limit", "collection"}:
                raise CloudBlocked("MEMORY_QUERY_IDENTITY_OVERRIDE", "Worker alone supplies project, task, attempt and authorization")
            if not isinstance(payload.get("query"), str) or not 1 <= len(payload["query"]) <= 1000:
                raise CloudBlocked("MEMORY_QUERY_INVALID", "Only a minimal explicit query is admitted")
            limit = payload.get("limit", 5)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise CloudBlocked("MEMORY_QUERY_INVALID", "Memory result count is bounded")
            if payload.get("collection", "main") not in ("main", "history"):
                raise CloudBlocked("MEMORY_QUERY_INVALID", "Collection must be main or explicitly selected history")
            body = {"project_id": self.broker.project_id,
                "context": self.query_context, "query": payload["query"], "limit": limit}
            if "collection" in payload:
                body["collection"] = payload["collection"]
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    await self._assert_query_current()
                    result = await self.client.query(body)
                    await self._assert_query_current()
                    result = {**result, "query_context": {
                        "project_id": self.broker.project_id, **self.query_context,
                        "worker_id": self.broker.identity.worker_id,
                        "generation": self.broker.identity.generation}}
                    return result
            except TimeoutError:
                return {"status": "UNAVAILABLE", "code": "MEMORY_TIMEOUT", "task_sync_unaffected": True}
        required = {"task_version", "asset_revision_id"}
        if (not required <= payload.keys() or type(payload["task_version"]) is not int
                or payload["task_version"] < 1):
            raise CloudBlocked("MEMORY_FIXED_SOURCE_REQUIRED", "Memory requires a fixed already accepted source revision")
        source = {"mode": "CLOUD", "task_id": self.broker.task_id, "attempt_id": self.broker.attempt_id,
            "task_version": payload["task_version"], "asset_revision_id": str(UUID(payload["asset_revision_id"]))}
        base = {"project_id": self.broker.project_id, "source": source}
        if operation == "CREATE_CANDIDATE" and set(payload) == required | {"title", "content"}:
            if (not isinstance(payload["title"], str) or not 1 <= len(payload["title"]) <= 240
                    or not isinstance(payload["content"], str) or not 1 <= len(payload["content"]) <= 16000):
                raise CloudBlocked("MEMORY_CONTENT_INVALID", "Only bounded explicitly approved experience text is admitted")
            return await self.client.propose({**base, "operation": operation, "expected_version": 0,
                "operation_key": "m:" + digest([self.broker.attempt_id, key]), "title": payload["title"], "content": payload["content"]})
        raise CloudBlocked("MEMORY_OPERATION_UNSUPPORTED", "Agents can only query or propose experience; publication remains human authorized")

    async def close(self):
        self.client.close()
        await self.transport.close()
