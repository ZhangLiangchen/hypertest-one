"""Frozen public HTTPS broker regressions. Synthetic transports only; no SUT/model."""
from __future__ import annotations

import asyncio
import base64
import copy
import ssl
import time
from uuid import uuid4

import httpx
import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_broker import HttpBroker
from hypertest.cloud.http_operations import (
    HttpOriginals,
    project_response,
    request_document,
    response_document,
)
from hypertest.cloud.http_profile import (
    HTTPS_ACCESS_PROFILE,
    digest,
    validate_profile,
)
from hypertest.cloud.http_transport import HttpExchange, HttpsTransport

PUBLIC_IP = "93.184.216.34"


def environment():
    resource = {"key": "health", "method": "GET", "path": "/v1/health", "timeout_seconds": 2,
                "response_limit_bytes": 4096}
    catalog = {"profile": HTTPS_ACCESS_PROFILE, "target": "https://api.example.invalid:443",
        "allowed_addresses": [PUBLIC_IP], "resources": [resource], "max_operations": 8}
    return {"connection": "HTTPS", "host": "api.example.invalid", "port": 443,
        "cloud_access_policy": "WEB_ONLY", "https_access": {
            key: value for key, value in {**catalog, "catalog_sha256": digest(catalog)}.items() if key != "target"}}


def profile():
    return validate_profile(environment())


def request_for(selected=None):
    selected = selected or profile()
    return request_document(operation_id=str(uuid4()), task_id=str(uuid4()), attempt_id=str(uuid4()),
        generation=1, target=selected.target, catalog_sha256=selected.catalog_sha256,
        resource=selected.resources[0].document(), hard_deadline=int(time.time()) + 20)


@pytest.mark.parametrize("host", ["localhost", "metadata.google.internal", "api.local", "api.internal",
    "api.example.invalid.", "API.example.invalid", "name_with_underscore.invalid", "user@api.example.invalid",
    "127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "fe80::1", "::ffff:93.184.216.34"])
def test_profile_refuses_noncanonical_or_restricted_hosts(host):
    value = environment()
    value["host"] = host
    with pytest.raises(CloudBlocked):
        validate_profile(value)


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "10.0.0.1", "172.16.0.1", "192.168.1.1",
    "169.254.169.254", "198.51.100.3", "224.0.0.1", "::1", "fe80::1", "fc00::1", "2002:5db8:d822::1"])
def test_profile_never_freezes_private_reserved_or_transition_addresses(address):
    value = environment()
    value["https_access"]["allowed_addresses"] = [address]
    with pytest.raises(CloudBlocked):
        validate_profile(value)


@pytest.mark.parametrize("path", ["//another.invalid/path", "/../secret", "/a/./b", "/a//b", "/%2fsecret",
    "/health?token=secret", "/health#fragment", "/a\\b", "/unicode/界", "https://another.invalid/a"])
def test_exact_resource_paths_cannot_expand_url_or_encode_a_different_target(path):
    value = environment()
    value["https_access"]["resources"][0]["path"] = path
    with pytest.raises(CloudBlocked):
        validate_profile(value)


@pytest.mark.parametrize("change", ["post", "credential", "local-only", "extra-field", "catalog", "bool-limit"])
def test_first_profile_is_public_readonly_and_rejects_catalog_drift(change):
    value = environment()
    if change == "post":
        value["https_access"]["resources"][0]["method"] = "POST"
    elif change == "credential":
        value["credential_version_id"] = str(uuid4())
    elif change == "local-only":
        value["cloud_access_policy"] = "LOCAL_ONLY"
    elif change == "extra-field":
        value["https_access"]["resources"][0]["headers"] = {"Authorization": "not accepted"}
    elif change == "catalog":
        value["https_access"]["resources"][0]["path"] = "/other"
    else:
        value["https_access"]["max_operations"] = True
    with pytest.raises(CloudBlocked):
        validate_profile(value)


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


async def resolved(_host, _port):
    return [PUBLIC_IP]


async def permitted():
    pass


async def test_transport_pins_tcp_url_preserves_tls_hostname_and_forbids_redirect_followup(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        assert str(request.url) == f"https://{PUBLIC_IP}/v1/health"
        assert request.extensions["sni_hostname"] == "api.example.invalid"
        assert request.headers["host"] == "api.example.invalid:443"
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert not request.content
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"},
            stream=FixtureStream([b"redirect not followed"]))
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.proxy.invalid:3128")
    transport = HttpsTransport(resolver=resolved, transport=httpx.MockTransport(handle))
    result = await transport.send(profile(), profile().resources[0], timeout=1, before_send=permitted)
    assert result.status == 302 and len(requests) == 1


@pytest.mark.parametrize("answers", [[PUBLIC_IP, "127.0.0.1"], ["169.254.169.254"], ["8.8.8.8"], []])
async def test_dns_private_mixed_rebinding_or_new_unfrozen_public_address_never_connects(answers):
    async def resolver(_host, _port):
        return answers
    def forbidden(_request):
        pytest.fail("HTTP transport touched after DNS rejection")
    transport = HttpsTransport(resolver=resolver, transport=httpx.MockTransport(forbidden))
    with pytest.raises(CloudBlocked):
        await transport.send(profile(), profile().resources[0], timeout=1, before_send=permitted)


@pytest.mark.parametrize("fault", ["length", "stream", "compressed", "headers"])
async def test_transport_rejects_unbounded_or_unsupported_output_without_silent_truncation(fault):
    def handle(_request):
        headers, chunks = {}, [b"ok"]
        if fault == "length":
            headers["Content-Length"] = "4097"
        elif fault == "stream":
            chunks = [b"a" * 4000, b"b" * 200]
        elif fault == "compressed":
            headers["Content-Encoding"] = "gzip"
        else:
            headers["X-Large"] = "x" * 17000
        return httpx.Response(200, headers=headers, stream=FixtureStream(chunks))
    transport = HttpsTransport(resolver=resolved, transport=httpx.MockTransport(handle))
    with pytest.raises(CloudBlocked):
        await transport.send(profile(), profile().resources[0], timeout=1, before_send=permitted)


async def test_transport_total_deadline_includes_dns_and_fence_rechecked_before_send():
    requests = []
    async def delayed_dns(_host, _port):
        await asyncio.sleep(1)
        return [PUBLIC_IP]
    transport = HttpsTransport(resolver=delayed_dns, transport=httpx.MockTransport(lambda r: requests.append(r)))
    with pytest.raises(TimeoutError):
        await transport.send(profile(), profile().resources[0], timeout=0.03, before_send=permitted)
    assert requests == []
    async def lost():
        raise CloudBlocked("STALE", "fixed safe fixture reason")
    transport = HttpsTransport(resolver=resolved, transport=httpx.MockTransport(lambda r: requests.append(r)))
    with pytest.raises(CloudBlocked, match="safe fixture"):
        await transport.send(profile(), profile().resources[0], timeout=1, before_send=lost)
    assert requests == []


def test_transport_cannot_disable_tls_verification_even_through_host_injection():
    context = ssl._create_unverified_context()
    with pytest.raises(CloudBlocked) as error:
        HttpsTransport(tls_context=context)
    assert error.value.code == "HTTPS_TLS_REQUIRED"


class FixtureAuthority:
    def __init__(self, selected):
        self.profile = selected
        self.records, self.keys = {}, {}
        self.current = True
        self.reject_body = self.lose_record_ack = False
        self.prepares = self.validations = 0

    async def prepare_start(self, key, resource_key):
        self.prepares += 1
        if key in self.keys:
            return {**copy.deepcopy(self.records[self.keys[key]]), "allow_send": False}
        if not self.current:
            raise CloudBlocked("STALE", "Worker lost authority")
        request = request_for(self.profile)
        request["resource"] = self.profile.resource(resource_key).document()
        operation_id = request["operation_id"]
        record = {"id": operation_id, "operation_key": key, "request": request, "request_digest": digest(request),
            "state": "SENT", "allow_send": False, "response": None}
        self.records[operation_id] = record
        self.keys[key] = operation_id
        return {**copy.deepcopy(record), "allow_send": True}

    async def admit_send(self, _operation_id):
        if not self.current:
            raise CloudBlocked("STALE", "Worker lost authority")

    async def get_operation(self, operation_id):
        return copy.deepcopy(self.records[operation_id])

    async def get_operation_by_key(self, key):
        return await self.get_operation(self.keys[key])

    async def record_response(self, operation_id, response):
        request = self.records[operation_id]["request"]
        validated = project_response(response, request)
        old = self.records[operation_id]
        if old["state"] == "OBSERVED":
            return copy.deepcopy(old)
        if validated["state"] == "OBSERVED" and not self.current:
            raise CloudBlocked("STALE", "Worker lost authority")
        old.update(state=validated["state"], response={k: v for k, v in validated.items() if k != "body_base64"})
        if self.lose_record_ack and validated["state"] == "OBSERVED":
            self.lose_record_ack = False
            raise OSError("synthetic secret-bearing upstream exception must not escape")
        return copy.deepcopy(old)

    async def validate_output(self, body):
        self.validations += 1
        if self.reject_body or b"fixture-secret" in body:
            raise CloudBlocked("SECRET", "Do not publish known secret")

    async def remote_closed(self):
        return all(row["state"] == "OBSERVED" for row in self.records.values())


class FixtureTransport:
    def __init__(self, authority):
        self.authority = authority
        self.calls = 0
        self.body = b'{"fixture":"no model or SUT"}'
        self.status = 200
        self.error = None
        self.after_send = None

    async def send(self, selected, resource, *, timeout, before_send):
        assert any(row["state"] == "SENT" for row in self.authority.records.values())
        await before_send()
        self.calls += 1
        if self.after_send:
            await self.after_send()
        if self.error:
            raise self.error
        return HttpExchange(self.status, self.body)


def broker_fixture(tmp_path):
    selected = profile()
    authority = FixtureAuthority(selected)
    transport = FixtureTransport(authority)
    broker = HttpBroker(tmp_path / "fixture.sock", profile=selected, authority=authority,
        private_root=tmp_path / "private-originals", deadline=int(time.time()) + 120, transport=transport)
    return broker, authority, transport


async def test_broker_frozen_original_key_duplicate_and_restart_read_only(tmp_path):
    broker, authority, transport = broker_fixture(tmp_path)
    first = await broker.invoke("original-key", "health")
    assert first["status"] == "OBSERVED" and transport.calls == 1
    duplicate = await broker.invoke("original-key", "health")
    assert duplicate == first and transport.calls == 1
    restarted = HttpBroker(tmp_path / "restarted.sock", profile=profile(), authority=authority,
        private_root=tmp_path / "private-originals", deadline=int(time.time()) + 120, transport=transport)
    recovered = await restarted.query(key="original-key")
    assert recovered == first and transport.calls == 1
    assert "body_base64" not in authority.records[first["response"]["operation_id"]]["response"]
    await broker.close()
    await restarted.close()
    assert restarted.drained is True


async def test_accepted_response_ack_loss_uses_saved_original_and_original_db_id_without_resend(tmp_path):
    broker, authority, transport = broker_fixture(tmp_path)
    authority.lose_record_ack = True
    first = await broker.invoke("lost-response", "health")
    assert first["status"] == "UNKNOWN" and transport.calls == 1
    operation_id = authority.keys["lost-response"]
    recovered = await broker.query(operation_id)
    assert recovered["status"] == "OBSERVED" and transport.calls == 1
    assert base64.b64decode(recovered["response"]["body_base64"]) == transport.body
    await broker.close()
    assert broker.drained is True


async def test_timeout_lost_worker_and_output_rejection_keep_canonical_unknown_no_body_no_replay(tmp_path):
    broker, authority, transport = broker_fixture(tmp_path)
    transport.body = b"fixture-secret"
    response = await broker.invoke("secret-output", "health")
    assert response["status"] == "UNKNOWN" and response["response"]["reason"] == "OUTPUT_REJECTED"
    assert "fixture-secret" not in str(response)
    assert list((tmp_path / "private-originals").iterdir()) == []
    assert (await broker.invoke("secret-output", "health"))["status"] == "UNKNOWN" and transport.calls == 1
    transport.body, transport.error = b"ok", TimeoutError("private exception canary")
    timed_out = await broker.invoke("lost-http-response", "health")
    assert timed_out["status"] == "UNKNOWN" and "canary" not in str(timed_out)
    transport.error = None
    async def fence():
        authority.current = False
    transport.after_send = fence
    fenced = await broker.invoke("fenced-inflight", "health")
    assert fenced["status"] == "UNKNOWN" and fenced["response"]["body_base64"] == ""
    assert (await broker.invoke("late-worker", "health"))["status"] == "UNKNOWN"
    await broker.close()
    assert broker.drained is False
    assert all(row["state"] == "UNKNOWN" for row in authority.records.values())


async def test_close_cancels_inflight_uds_request_without_claiming_external_stop(tmp_path):
    broker, authority, transport = broker_fixture(tmp_path)
    entered = asyncio.Event()
    async def wait_for_cancel():
        entered.set()
        await asyncio.sleep(60)
    transport.after_send = wait_for_cancel
    await broker.start()
    reader, writer = await asyncio.open_unix_connection(broker.socket_path)
    writer.write(b'{"verb":"INVOKE","key":"cancel-inflight","resource_key":"health"}\n')
    await writer.drain()
    await asyncio.wait_for(entered.wait(), 2)
    result = await broker.close()
    assert result["remote_closed"] is False and broker.drained is False
    assert next(iter(authority.records.values()))["state"] == "UNKNOWN"
    assert transport.calls == 1
    await reader.read()
    writer.close()


def test_originals_are_immutable_private_and_full_response_hash_checked(tmp_path):
    request = request_for()
    original = response_document(request, state="OBSERVED", http_status=200, body=b"original",
        reason="RESPONSE_OBSERVED")
    store = HttpOriginals(tmp_path / "private")
    store.save(request, original)
    assert store.get(request) == original
    changed = response_document(request, state="OBSERVED", http_status=200, body=b"changed",
        reason="RESPONSE_OBSERVED")
    with pytest.raises(CloudBlocked):
        store.save(request, changed)
    invalid = {**original, "byte_count": 1}
    with pytest.raises(CloudBlocked):
        project_response(invalid, request)


async def test_admission_response_loss_keeps_original_key_and_query_does_not_prepare_or_send(tmp_path):
    broker, authority, transport = broker_fixture(tmp_path)
    prepare = authority.prepare_start
    async def lost_ack(key, resource_key):
        await prepare(key, resource_key)
        raise OSError("private synthetic admission canary")
    authority.prepare_start = lost_ack
    result = await broker.invoke("original-before-id", "health")
    assert result == {"status": "UNKNOWN", "code": "HTTPS_ADMISSION_UNKNOWN", "operation_key": "original-before-id"}
    assert transport.calls == 0 and authority.prepares == 1
    restored = await broker.query(key="original-before-id")
    assert restored["status"] == "UNKNOWN" and authority.prepares == 1 and transport.calls == 0
    assert restored["response"]["operation_id"] == authority.keys["original-before-id"]
    await broker.close()
    assert broker.drained is False and broker.observation()["pending_keys"] == ["original-before-id"]
