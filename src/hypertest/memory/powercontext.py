"""Bounded explicit PowerContext REST adapter, with no generation or hooks.

Only the Gateway role mounts the configured administrator credential. Queries
use an explicitly configured retrieval profile. Publication recovery stays FTS;
the context/prepare and generation surfaces are never called.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import ssl
import unicodedata
from urllib.parse import quote, urlsplit

import httpx

from hypertest.cloud.private_file import read_private_file
from hypertest.config import get_settings

KIND = "hypertest-experience"
RESERVED_KINDS = frozenset({KIND, "historical_technical_record"})
_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,256}$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def shared_kind(kind):
    return isinstance(kind, str) and 1 <= len(kind) <= 128 and kind not in RESERVED_KINDS


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
                    if response.status_code == 404:
                        raise MemoryUpstreamError("MEMORY_UPSTREAM_NOT_FOUND")
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
        mode = getattr(self.settings, "memory_search_mode", "fts")
        if (mode not in value.get("search_modes", []) or "fts" not in value.get("search_modes", []) or any(value.get(key) is not False for key in
                ("memory_extraction", "experience_generation", "managed_skill_generation", "handoff_generation"))):
            raise MemoryUpstreamError("MEMORY_UPSTREAM_PROFILE_UNSUPPORTED")
        return {"ready": True, "retrieval": mode, "external_generation": False,
                "external_embedding": mode == "hybrid", "source": "CONFIGURED_FIXED_PROFILE"}

    async def adopt_scope(self, scope_id, namespace, *, reference_kind="hypertest-project"):
        """Verify an Operator's exact target; neither rename nor create a scope."""
        value = await self._request("GET", f"/v1/scopes/{_path_id(scope_id)}")
        references = value.get("external_references", [])
        expected = {"kind": reference_kind, "value": namespace}
        project_refs = [ref for ref in references if isinstance(ref, dict) and ref.get("kind") == reference_kind]
        if value.get("scope_id") != scope_id or project_refs != [expected]:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_SCOPE_MISMATCH")
        return scope_id

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

    async def get(self, scope_id, artifact_id, revision, *, kind=KIND):
        scope, artifact = _path_id(scope_id), _path_id(artifact_id)
        ref = _ref({"family": "atomic-memory", "artifact_id": artifact_id, "revision": revision})
        value = await self._request("GET", f"/v1/scopes/{scope}/artifacts/atomic-memory/{artifact}/revisions/{revision}")
        content = value.get("content")
        if (value.get("scope_id") != scope_id or value.get("family") != "atomic-memory"
                or value.get("artifact_id") != artifact_id or value.get("revision") != revision
                or not isinstance(content, dict) or content.get("kind") != kind
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

    async def _shared_material(self, scope_id, hit):
        # Search is only a locator. Re-read current lifecycle/ref, then immutable
        # bytes and digest; never project a retired or superseded search hit.
        path = f"/v1/scopes/{_path_id(scope_id)}/artifacts/atomic-memory/{_path_id(hit['artifact_id'])}/state"
        state = await self._request("GET", path)
        current = _ref(state.get("artifact"))
        if state.get("state") != "active" or current != {key: hit[key] for key in ("artifact_id", "revision")}:
            return None
        if type(state.get("state_version")) is not int or state["state_version"] < 0:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_STATE_INVALID")
        material = await self.get(scope_id, **current, kind=hit["kind"])
        return {**hit, **material, "state_version": state["state_version"]}

    async def search_project(self, scope_id, query, limit, shared_limit):
        """Same-scope published locators and explicitly shared active lessons."""
        _path_id(scope_id)
        mode = getattr(self.settings, "memory_search_mode", "fts")
        value = await self._request("POST", "/v1/memory/search", payload={"scope_id": scope_id,
            "query": query, "limit": min(limit, 50), "mode": mode})
        hits = value.get("hits")
        allowed_modes = {"text"} if mode == "fts" else {"text", "vector", "hybrid"}
        if value.get("mode") not in allowed_modes or not isinstance(hits, list) or len(hits) > 50:
            raise MemoryUpstreamError("MEMORY_UPSTREAM_SEARCH_INVALID")
        result, shared = [], []
        for hit in hits:
            memory = hit.get("memory") if isinstance(hit, dict) else None
            if (not isinstance(memory, dict) or memory.get("state") != "active"
                    or not (memory.get("kind") == KIND or shared_kind(memory.get("kind")))):
                continue
            row = {**_ref(memory.get("artifact")), "kind": memory["kind"]}
            score = hit.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score):
                row["score"] = score
            channels = hit.get("matched_by")
            if not isinstance(channels, list) or any(item not in {"text", "vector"} for item in channels):
                raise MemoryUpstreamError("MEMORY_UPSTREAM_SEARCH_INVALID")
            row["matched_by"] = channels
            if row["kind"] == KIND:
                result.append(row)
            elif len(shared) < shared_limit:
                result.append(row)
                shared.append(row)
        # A bounded batch shares the Gateway's overall deadline. There are no
        # retries, context references, Source reads or hidden generation calls.
        material = await asyncio.gather(*(self._shared_material(scope_id, row) for row in shared))
        by_identity = {(row["artifact_id"], row["revision"]): row for row in material if row is not None}
        return {"mode": value["mode"], "hits": [row if row["kind"] == KIND else by_identity[(row["artifact_id"], row["revision"])]
            for row in result if row["kind"] == KIND or (row["artifact_id"], row["revision"]) in by_identity]}

    async def browse(self, scope_id, *, history=False, query=None, cursor=None, limit=20):
        """Explicit inventory/search; never follows Scope references or reads Sources."""
        _path_id(scope_id)
        if query is not None:
            if cursor is not None:
                raise MemoryUpstreamError("MEMORY_SEARCH_CURSOR_UNSUPPORTED")
            mode = getattr(self.settings, "memory_search_mode", "fts")
            payload = {"scope_id": scope_id, "query": query, "limit": limit, "mode": mode}
            value = await self._request("POST", "/v1/memory/search", payload=payload)
            if value.get("mode") not in ({"text"} if mode == "fts" else {"text", "vector", "hybrid"}):
                raise MemoryUpstreamError("MEMORY_UPSTREAM_SEARCH_INVALID")
            hits = value.get("hits")
            if not isinstance(hits, list) or len(hits) > limit:
                raise MemoryUpstreamError("MEMORY_UPSTREAM_SEARCH_INVALID")
            records = [hit.get("memory") for hit in hits if isinstance(hit, dict)]
            next_cursor = None
        else:
            payload = {"scope_id": scope_id, "states": ["active"], "limit": limit}
            if history:
                payload["kind"] = "historical_technical_record"
            if cursor is not None:
                payload["cursor"] = cursor
            value = await self._request("POST", "/v1/atomic-memory/list", payload=payload)
            records, next_cursor = value.get("items"), value.get("next_cursor")
            if not isinstance(records, list) or len(records) > limit or (next_cursor is not None and (
                    not isinstance(next_cursor, str) or not next_cursor or len(next_cursor) > 4096 or next_cursor == cursor)):
                raise MemoryUpstreamError("MEMORY_UPSTREAM_CURSOR_INVALID")
        locators = []
        for record in records:
            if not isinstance(record, dict) or record.get("state") != "active":
                continue
            kind = record.get("kind")
            if not (kind == "historical_technical_record" if history else shared_kind(kind)):
                continue
            locators.append({**_ref(record.get("artifact")), "kind": kind})
        material = await asyncio.gather(*(self._shared_material(scope_id, row) for row in locators))
        return {"items": [row for row in material if row is not None], "next_cursor": next_cursor,
                "search_mode": value.get("mode") if query is not None else None}

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
