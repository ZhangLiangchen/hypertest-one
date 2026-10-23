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
from uuid import UUID

import httpx

from hypertest.interactive_client.api_client import ApiError
from hypertest.interactive_client.memory import MemoryClient
from hypertest.sync_core import digest

from .artifacts import _write_workspace_metadata, read_workspace_file
from .errors import CloudBlocked
from .private_file import read_private_file

HANDOFF_PROFILE = "hypertest-cloud-memory-handoff/v1alpha1"
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


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
        headers = {"Authorization": "Bearer " + self._token,
            "X-Hypertest-Memory-Worker-Id": identity.worker_id,
            "X-Hypertest-Memory-Lease-Token": identity.lease_token,
            "X-Hypertest-Memory-Generation": str(identity.generation),
            "X-Hypertest-Memory-Work-Token": identity.work_token}
        try:
            async with self.http.stream(method, path, json=payload, params=params, headers=headers) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 1024 * 1024:
                        raise ApiError("MEMORY_RESPONSE_LIMIT")
                if not 200 <= response.status_code < 300:
                    raise ApiError("MEMORY_REQUEST_REJECTED", response.status_code)
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ApiError("MEMORY_RESPONSE_INVALID")
                return result
        except (httpx.HTTPError, TimeoutError):
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
        private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.client = MemoryClient(transport.request, private_root / "memory.sqlite3", timeout_seconds=timeout_seconds)
        self.seen: dict[str, str] = {}

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
            try:
                raw = read_workspace_file(self.workspace, ".hypertest-cloud/memory-ready/" + path.name, max_bytes=65536)
                fingerprint = digest(raw.decode())
                if key in self.seen:
                    # A response is immutable. Changing an intent never causes
                    # new processing or a second candidate POST.
                    continue
                document = json.loads(raw)
                result = await self.handle(document, key)
            except (CloudBlocked, ApiError, ValueError, TypeError, KeyError) as error:
                result = {"status": "REFUSED", "code": getattr(error, "code", "MEMORY_HANDOFF_INVALID"), "task_sync_unaffected": True}
                fingerprint = "REFUSED"
            if len(json.dumps(result).encode()) > 60000:
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
        if operation == "QUERY" and payload.keys() <= {"query", "limit"}:
            if not isinstance(payload.get("query"), str) or not 1 <= len(payload["query"]) <= 1000:
                raise CloudBlocked("MEMORY_QUERY_INVALID", "Only a minimal explicit query is admitted")
            limit = payload.get("limit", 5)
            if type(limit) is not int or not 1 <= limit <= 20:
                raise CloudBlocked("MEMORY_QUERY_INVALID", "Memory result count is bounded")
            return await self.client.query({"project_id": self.broker.project_id,
                "context": self.query_context, "query": payload["query"], "limit": limit})
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
