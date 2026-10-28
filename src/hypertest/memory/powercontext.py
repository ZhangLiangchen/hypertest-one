"""Bounded explicit PowerContext 1.4.0 REST adapter, with no inference or hooks.

Only the Gateway role mounts the configured administrator credential. Queries
are FTS only; the context/prepare and generation surfaces are never called.
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import unicodedata
from urllib.parse import quote, urlsplit

import httpx

from hypertest.cloud.private_file import read_private_file
from hypertest.config import get_settings

KIND = "hypertest-experience"
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


class MemoryUpstreamError(Exception):
    def __init__(self, code="MEMORY_UPSTREAM_UNAVAILABLE"):
        self.code = code
        super().__init__(code)


def _path_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise MemoryUpstreamError("MEMORY_UPSTREAM_ID_INVALID")
    return quote(value, safe="")


def _ref(value):
    if not isinstance(value, dict) or value.get("family") != "atomic-memory":
        raise MemoryUpstreamError("MEMORY_UPSTREAM_REF_INVALID")
    artifact_id, revision = value.get("artifact_id"), value.get("revision")
    _path_id(artifact_id)
    if type(revision) is not int or revision < 1:
        raise MemoryUpstreamError("MEMORY_UPSTREAM_REF_INVALID")
    return {"artifact_id": artifact_id, "revision": revision}


class PowerContextAdapter:
    def __init__(self, settings=None, *, transport=None):
        self.settings = settings or get_settings()
        self.transport = transport
        parsed = urlsplit(self.settings.memory_powercontext_origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_ORIGIN_INVALID")
        self.origin = self.settings.memory_powercontext_origin.rstrip("/")

    async def _request(self, method, path, *, payload=None, params=None):
        # No retry transport, redirects, proxy credentials, raw error bodies or
        # exception reprs cross this adapter. SENT ownership belongs to Gateway.
        try:
            token = read_private_file(self.settings.memory_powercontext_token_file, max_bytes=8192).decode().strip()
            if not token or any(char.isspace() for char in token):
                raise MemoryUpstreamError("MEMORY_UPSTREAM_CREDENTIAL_INVALID")
            tls = ssl.create_default_context(cafile=self.settings.memory_powercontext_ca_file)
            async with httpx.AsyncClient(base_url=self.origin, headers={"Authorization": "Bearer " + token},
                    verify=tls, timeout=self.settings.memory_timeout_seconds, follow_redirects=False,
                    trust_env=False, transport=self.transport) as client:
                async with client.stream(method, path, json=payload, params=params) as response:
                    if not 200 <= response.status_code < 300:
                        raise MemoryUpstreamError("MEMORY_UPSTREAM_RESPONSE_REJECTED")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.memory_max_response_bytes:
                            raise MemoryUpstreamError("MEMORY_UPSTREAM_RESPONSE_LIMIT")
                        chunks.append(chunk)
                    value = json.loads(b"".join(chunks))
                    if not isinstance(value, dict):
                        raise MemoryUpstreamError("MEMORY_UPSTREAM_RESPONSE_INVALID")
                    return value
        except MemoryUpstreamError:
            raise
        except Exception:
            raise MemoryUpstreamError() from None

    async def capabilities(self):
        value = await self._request("GET", "/v1/capabilities")
        if ("fts" not in value.get("search_modes", []) or any(value.get(key) is not False for key in
                ("memory_extraction", "experience_generation", "managed_skill_generation", "handoff_generation"))):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_PROFILE_UNSUPPORTED")
        return {"ready": True, "version": "1.4.0", "retrieval": "fts", "external_generation": False,
                "external_embedding": False, "source": "CONFIGURED_FIXED_PROFILE"}

    async def create_scope(self, namespace, operation_key):
        _path_id(namespace)
        _path_id(operation_key)
        value = await self._request("POST", "/v1/scopes", payload={"title": namespace,
            "summary": "Explicit HyperTest Project curated experience; not testing evidence or authorization.",
            "idempotency_key": operation_key,
            "external_references": [{"kind": "hypertest-project", "value": namespace}]})
        return self._scope(value, namespace)

    @staticmethod
    def _scope(value, namespace):
        if (value.get("title") != namespace or not any(ref == {"kind": "hypertest-project", "value": namespace}
                for ref in value.get("external_references", []))):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_SCOPE_MISMATCH")
        _path_id(value.get("scope_id"))
        return value["scope_id"]

    async def find_scope(self, namespace):
        _path_id(namespace)
        cursor, seen, matches = None, set(), set()
        for _ in range(10):
            params = {"query": namespace, "query_field": "title", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            value = await self._request("GET", "/v1/scopes", params=params)
            items = value.get("items")
            if not isinstance(items, list):
                raise MemoryUpstreamError("MEMORY_UPSTREAM_RESPONSE_INVALID")
            for item in items:
                if isinstance(item, dict) and item.get("title") == namespace:
                    matches.add(self._scope(item, namespace))
            cursor = value.get("next_cursor")
            if not cursor:
                if len(matches) > 1:
                    raise MemoryUpstreamError("MEMORY_UPSTREAM_SCOPE_AMBIGUOUS")
                return next(iter(matches), None)
            if not isinstance(cursor, str) or len(cursor) > 4096 or cursor in seen:
                raise MemoryUpstreamError("MEMORY_UPSTREAM_CURSOR_INVALID")
            seen.add(cursor)
        raise MemoryUpstreamError("MEMORY_UPSTREAM_LOOKUP_LIMIT")

    async def remember(self, scope_id, content, metadata=None):
        _path_id(scope_id)
        if (not isinstance(content, str) or not content or content != unicodedata.normalize("NFC", content).strip()
                or len(content.encode()) > 8192):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_CONTENT_INVALID")
        # Metadata contains private provenance; only the approved rendered text
        # is transmitted. The operation marker is already part of that text.
        value = await self._request("POST", "/v1/memory/remember", payload={"scope_id": scope_id,
            "kind": KIND, "text": content, "reason": "HyperTest operator confirmed publication"})
        records = value.get("records")
        if (not isinstance(records, list) or len(records) != 1 or records[0].get("kind") != KIND
                or records[0].get("text") != content or records[0].get("state") != "active"):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_ACK_INVALID")
        return _ref(records[0].get("artifact"))

    async def get(self, scope_id, artifact_id, revision):
        scope, artifact = _path_id(scope_id), _path_id(artifact_id)
        ref = _ref({"family": "atomic-memory", "artifact_id": artifact_id, "revision": revision})
        value = await self._request("GET", f"/v1/scopes/{scope}/artifacts/atomic-memory/{artifact}/revisions/{revision}")
        content = value.get("content")
        if (value.get("scope_id") != scope_id or value.get("family") != "atomic-memory"
                or value.get("artifact_id") != artifact_id or value.get("revision") != revision
                or not isinstance(content, dict) or content.get("kind") != KIND
                or not isinstance(content.get("text"), str) or len(content["text"].encode()) > 8192
                or not isinstance(value.get("content_digest"), str) or not _DIGEST.fullmatch(value["content_digest"])):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_READBACK_MISMATCH")
        # This fixed schema has strings only, so sorted compact UTF-8 JSON is
        # equivalent to upstream RFC8785 canonical serialization.
        digest = "sha256:" + hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        if digest != value["content_digest"]:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_DIGEST_MISMATCH")
        return {**ref, "content": content["text"], "content_digest": digest}

    async def search(self, scope_id, query, limit):
        _path_id(scope_id)
        if not isinstance(query, str) or not 1 <= len(query) <= 8192 or type(limit) is not int or limit < 1:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_QUERY_INVALID")
        value = await self._request("POST", "/v1/memory/search", payload={"scope_id": scope_id,
            "query": query, "limit": min(limit, 50), "mode": "fts"})
        hits = value.get("hits")
        # PowerContext 1.4.0 maps the public request mode "fts" to its
        # atomic-memory response mode "text". Reject vector/hybrid results.
        if value.get("mode") != "text" or not isinstance(hits, list) or len(hits) > 50:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_SEARCH_INVALID")
        result = []
        for hit in hits:
            memory = hit.get("memory") if isinstance(hit, dict) else None
            if isinstance(memory, dict) and memory.get("kind") == KIND and memory.get("state") == "active":
                result.append({**_ref(memory.get("artifact")), "content": memory.get("text")})
        return result

    async def find_operation(self, scope_id, marker):
        _path_id(marker)
        # Upstream's FTS lookup is a read-only POST. It never repeats remember.
        matches = await self.search(scope_id, marker, 50)
        result = []
        for match in matches:
            if isinstance(match.get("content"), str) and marker in match["content"]:
                value = await self.get(scope_id, match["artifact_id"], match["revision"])
                if marker in value["content"]:
                    result.append(value)
        return result
