"""Pinned upstream REST boundary: no network, models or production projects."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from hypertest.memory.powercontext import KIND, MemoryUpstreamError, PowerContextAdapter


def make_adapter(tmp_path, handler, **overrides):
    secret = tmp_path / "memory-token"
    secret.write_text("synthetic-private-memory-administrator")
    secret.chmod(0o600)
    values = dict(memory_powercontext_origin="https://memory.example.test",
        memory_powercontext_token_file=str(secret), memory_powercontext_ca_file=None,
        memory_timeout_seconds=0.2, memory_max_response_bytes=16384)
    values.update(overrides)
    return PowerContextAdapter(SimpleNamespace(**values), transport=httpx.MockTransport(handler))


def ref():
    return {"family": "atomic-memory", "artifact_id": "art_original", "revision": 1}


def material(text, **overrides):
    content = {"schema": "powercontext.atomic-memory.v1", "kind": KIND, "text": text}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return {"scope_id": "scp_original", **ref(), "content": content,
            "content_digest": "sha256:" + digest, **overrides}


@pytest.mark.asyncio
async def test_pinned_remember_transmits_only_approved_text_and_fixed_get(tmp_path):
    calls = []
    text = "Explicit curated experience\nhtmemoriginal123"
    def handle(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer synthetic-private-memory-administrator"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body == {"scope_id": "scp_original", "kind": KIND, "text": text,
                            "reason": "HyperTest operator confirmed publication"}
            return httpx.Response(200, json={"changed": True, "records": [
                {"artifact": ref(), "kind": KIND, "text": text, "state": "active"}]})
        assert request.url.path.endswith("/atomic-memory/art_original/revisions/1")
        return httpx.Response(200, json=material(text))
    adapter = make_adapter(tmp_path, handle)
    accepted = await adapter.remember("scp_original", text, {"private_source": "never send this report"})
    assert accepted == {"artifact_id": "art_original", "revision": 1}
    assert (await adapter.get("scp_original", **accepted))["content"] == text
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_scope_reconciliation_reads_exact_namespace_and_never_recreates(tmp_path):
    calls = []
    namespace = "hypertest-project-123"
    scope = {"scope_id": "scp_original", "title": namespace,
             "external_references": [{"kind": "hypertest-project", "value": namespace}]}
    def handle(request):
        calls.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [dict(scope, title=namespace + "-other"), scope], "next_cursor": None})
    assert await make_adapter(tmp_path, handle).find_scope(namespace) == "scp_original"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_scope_creation_preserves_the_original_upstream_idempotency_key(tmp_path):
    def handle(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/scopes" and body["idempotency_key"] == "op_original"
        return httpx.Response(201, json={**body, "scope_id": "scp_original"})
    assert await make_adapter(tmp_path, handle).create_scope("project-123", "op_original") == "scp_original"


@pytest.mark.asyncio
async def test_lost_ack_lookup_uses_fts_then_exact_revision_without_remember(tmp_path):
    calls = []
    text = "Historical method\nhtmemoriginal123"
    def handle(request):
        calls.append(request.url.path)
        if request.method == "POST":
            assert request.url.path == "/v1/memory/search"
            assert json.loads(request.content) == {"scope_id": "scp_original", "query": "htmemoriginal123", "limit": 50, "mode": "fts"}
            return httpx.Response(200, json={"mode": "fts", "hits": [{"memory": {
                "artifact": ref(), "kind": KIND, "state": "active", "text": text}}]})
        return httpx.Response(200, json=material(text))
    matches = await make_adapter(tmp_path, handle).find_operation("scp_original", "htmemoriginal123")
    assert matches[0]["content"] == text
    assert "/v1/memory/remember" not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"scope_id": "scp_other"}, {"revision": 2}, {"content_digest": "sha256:" + "0" * 64},
])
async def test_fixed_readback_rejects_wrong_scope_version_or_bytes(tmp_path, change):
    adapter = make_adapter(tmp_path, lambda request: httpx.Response(200, json=material("original", **change)))
    with pytest.raises(MemoryUpstreamError):
        await adapter.get("scp_original", "art_original", 1)


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_error_body_cannot_escape(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example.test/"},
                              text="synthetic-private-memory-administrator")
    with pytest.raises(MemoryUpstreamError) as error:
        await make_adapter(tmp_path, handle).find_scope("project-123")
    assert "synthetic" not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_response_limit_and_invalid_normalization_fail_without_retry(tmp_path):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b"x" * 20000)
    adapter = make_adapter(tmp_path, handle)
    with pytest.raises(MemoryUpstreamError, match="RESPONSE_LIMIT"):
        await adapter.search("scp_original", "method", 2)
    with pytest.raises(MemoryUpstreamError, match="CONTENT_INVALID"):
        await adapter.remember("scp_original", " e\u0301 ")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_capability_probe_rejects_generation_and_requires_fts(tmp_path):
    value = {"search_modes": ["auto", "fts"], "memory_extraction": False, "experience_generation": False,
             "managed_skill_generation": False, "handoff_generation": False}
    adapter = make_adapter(tmp_path, lambda request: httpx.Response(200, json=value))
    assert (await adapter.capabilities())["external_generation"] is False
    value["experience_generation"] = True
    with pytest.raises(MemoryUpstreamError, match="PROFILE_UNSUPPORTED"):
        await adapter.capabilities()


@pytest.mark.parametrize("origin", ["http://memory.example.test", "https://token@memory.example.test", "https://memory.example.test/path"])
def test_admin_transport_rejects_plaintext_userinfo_and_prefix_override(tmp_path, origin):
    with pytest.raises(MemoryUpstreamError, match="ORIGIN_INVALID"):
        make_adapter(tmp_path, lambda request: httpx.Response(200), memory_powercontext_origin=origin)
