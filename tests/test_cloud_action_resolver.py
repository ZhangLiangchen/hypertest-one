"""Fixed DoH resolution is bounded and never selects an Agent-supplied resolver."""
from __future__ import annotations

import gzip
import json

import httpx
import pytest

from hypertest.cloud import action_resolver as resolver
from hypertest.cloud.errors import CloudBlocked


def answer(host="api.example.com", typ=1, rows=None, **changes):
    data = {"Status": 0, "TC": False, "Question": [{"name": host, "type": typ}],
            "Answer": rows if rows is not None else [{"name": host, "type": typ,
                "data": "8.8.8.8" if typ == 1 else "2606:4700:4700::1111"}]}
    data.update(changes)
    return json.dumps(data, separators=(",", ":")).encode()


def test_resolver_accepts_only_the_asked_public_records_and_valid_cname():
    assert resolver.parse_answer(answer(), "api.example.com", 1) == (["8.8.8.8"], "api.example.com")
    rows = [{"name": "api.example.com.", "type": 5, "data": "edge.example.com."},
            {"name": "edge.example.com.", "type": 1, "data": "8.8.4.4"}]
    assert resolver.parse_answer(answer(rows=rows), "api.example.com", 1) == (["8.8.4.4"], "edge.example.com")


@pytest.mark.parametrize("raw", [
    answer(host="other.example.com"),
    answer(Status=3),
    answer(TC=True),
    answer(rows=[{"name": "api.example.com", "type": 1, "data": "198.18.0.1"}]),
    answer(rows=[{"name": "api.example.com", "type": 1, "data": "127.0.0.1"}]),
    answer(rows=[{"name": "api.example.com", "type": 1, "data": "8.8.8.8"},
                 {"name": "unrelated.example.com", "type": 1, "data": "1.1.1.1"}]),
    answer(rows=[{"name": "api.example.com", "type": 5, "data": "edge.example.com"},
                 {"name": "edge.example.com", "type": 5, "data": "api.example.com"}]),
    answer(rows=[{"name": "api.example.com", "type": 5, "data": "edge.example.com"},
                 {"name": "api.example.com", "type": 5, "data": "other.example.com"}]),
    answer(rows=[{"name": "api.example.com", "type": 28, "data": "2606:4700:4700::1111"}]),
    b'{"Status":0,"Status":0,"Question":[]}',
    b"x" * 32769,
], ids=["wrong-question", "nxdomain", "truncated", "fake-ip", "loopback", "unrelated-owner",
        "cname-cycle", "conflicting-cname", "wrong-family", "duplicate-json-key", "oversize"])
def test_resolver_rejects_untrusted_or_ambiguous_answers(raw):
    with pytest.raises(CloudBlocked) as error:
        resolver.parse_answer(raw, "api.example.com", 1)
    assert error.value.code == "CONTROLLED_ACTION_DNS_REFUSED"


@pytest.mark.asyncio
async def test_fixed_doh_transport_and_both_address_families(monkeypatch):
    requests = []

    async def handle(request):
        requests.append(request)
        typ = 1 if request.url.params["type"] == "A" else 28
        return httpx.Response(200, headers={"content-type": "application/dns-json"},
                              stream=httpx.ByteStream(answer(typ=typ)))

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    actual = await resolver.resolve_action_public("api.example.com", 443)
    assert actual == ["2606:4700:4700::1111", "8.8.8.8"]
    assert len(requests) == 2
    for request in requests:
        assert request.method == "GET"
        assert request.url.host == "1.1.1.1" and request.url.path == "/dns-query"
        assert request.url.params["name"] == "api.example.com"
        assert request.headers["host"] == "cloudflare-dns.com:443"
        assert request.extensions["sni_hostname"] == "cloudflare-dns.com"
        assert "authorization" not in request.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"location": "https://other.example.com"}),
    httpx.Response(200, headers={"content-type": "text/html"}, content=answer()),
    httpx.Response(200, headers={"content-type": "application/dns-json", "content-encoding": "gzip"}, content=gzip.compress(answer())),
    httpx.Response(200, headers={"content-type": "application/dns-json"}, content=b"x" * 32769),
])
async def test_doh_rejects_redirect_bad_content_encoding_and_large_response(monkeypatch, response):
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(lambda _: response))
    with pytest.raises(CloudBlocked) as error:
        await resolver.resolve_action_public("api.example.com", 443)
    assert error.value.code == "CONTROLLED_ACTION_DNS_REFUSED"


@pytest.mark.asyncio
async def test_public_literal_never_queries_doh_and_private_literal_is_denied(monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("literal resolution must not construct a transport")
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    assert await resolver.resolve_action_public("8.8.8.8", 443) == ["8.8.8.8"]
    with pytest.raises(CloudBlocked):
        await resolver.resolve_action_public("198.18.0.1", 443)
