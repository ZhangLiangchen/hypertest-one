"""Authenticated action transport is bounded and never retries or redirects."""
import hashlib
import json

import httpx
import pytest
from test_cloud_action_profile import prepared, profile

from hypertest.cloud.action_transport import ActionTransport
from hypertest.cloud.errors import CloudBlocked


class FixtureStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"fixture"


@pytest.mark.asyncio
async def test_sends_only_original_signed_bytes_after_rechecking_authority():
    raw = json.dumps(prepared(), indent=2).encode()
    seen = []

    async def resolver(host, port):
        assert (host, port) == ("api.example.invalid", 443)
        return ["8.8.8.8"]

    async def verify(_action, value):
        assert value == raw
        seen.append("verified")
        return True

    async def before_send(digest):
        assert digest == hashlib.sha256(raw).hexdigest()
        seen.append("authority")

    async def exchange(request):
        assert request.method == "POST" and request.url.path == "/fixed/action"
        assert request.content == raw and request.headers["x-api-key"] == "synthetic-key"
        assert request.extensions["sni_hostname"] == "api.example.invalid"
        seen.append("send")
        return httpx.Response(302, headers={"location": "https://unapproved.invalid"}, stream=FixtureStream())

    transport = ActionTransport(resolver=resolver, transport=httpx.MockTransport(exchange))
    result = await transport.send(profile=profile(), action_key="swap-2", client_ref="order-original",
        unique_ref="unique-original", body=raw, sent_body_sha256=hashlib.sha256(raw).hexdigest(),
        api_key=b"synthetic-key", timeout=5, verify_signature=verify, before_send=before_send)
    assert (result.status, result.body) == (302, b"fixture")
    assert seen == ["verified", "authority", "send"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["signature", "dns", "authority", "digest"])
async def test_rejects_without_network_send_when_authority_is_unconfirmed(failure):
    raw = json.dumps(prepared()).encode()
    async def resolver(_host, _port):
        return ["9.9.9.9"] if failure == "dns" else ["8.8.8.8"]
    async def verify(_action, _body):
        return failure != "signature"
    async def before_send(_digest):
        if failure == "authority":
            raise CloudBlocked("FENCED", "synthetic")
    async def unexpected(_request):
        pytest.fail("no POST is authorized")
    transport = ActionTransport(resolver=resolver, transport=httpx.MockTransport(unexpected))
    digest = "0" * 64 if failure == "digest" else hashlib.sha256(raw).hexdigest()
    with pytest.raises(CloudBlocked):
        await transport.send(profile=profile(), action_key="swap-2", client_ref="order-original",
            unique_ref="unique-original", body=raw, sent_body_sha256=digest, api_key=b"synthetic-key",
            timeout=5, verify_signature=verify, before_send=before_send)


@pytest.mark.asyncio
async def test_unknown_after_send_is_reported_without_retry_or_secret_text():
    raw = json.dumps(prepared()).encode()
    calls = []
    async def resolver(_host, _port):
        return ["8.8.8.8"]
    async def verify(_action, _body):
        return True
    async def before_send(_digest):
        pass
    async def fail(_request):
        calls.append(1)
        raise httpx.ReadTimeout("synthetic-key must not leak")
    transport = ActionTransport(resolver=resolver, transport=httpx.MockTransport(fail))
    with pytest.raises(CloudBlocked) as caught:
        await transport.send(profile=profile(), action_key="swap-2", client_ref="order-original",
            unique_ref="unique-original", body=raw, sent_body_sha256=hashlib.sha256(raw).hexdigest(),
            api_key=b"synthetic-key", timeout=5, verify_signature=verify, before_send=before_send)
    assert calls == [1] and caught.value.code == "CONTROLLED_ACTION_TRANSPORT_UNKNOWN"
    assert "synthetic-key" not in str(caught.value)
