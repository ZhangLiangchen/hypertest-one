"""The Agent cannot inject bytes, credentials, or replacement operations."""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import pytest
from test_cloud_action_profile import prepared, profile

from hypertest.cloud.action_broker import ActionBroker, ActionOriginals
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_transport import HttpExchange


class Authority:
    def __init__(self, fail=None):
        self.fail, self.record, self.calls = fail, None, []

    async def prepare_identity(self, **values):
        self.calls.append("identity")
        self.record = {**values, "identity_id": str(uuid4()), "state": "IDENTIFIED", "body_sha256": None,
                       "allow_prepare": True, "allow_send": False}
        if self.fail == "identity_ack":
            raise TimeoutError
        return self.record.copy()

    async def get_by_key(self, _key):
        self.calls.append("query")
        if self.record is None:
            raise LookupError
        return {**self.record, "allow_prepare": False, "allow_send": False}

    async def prepare_send(self, *, identity_id, body_sha256):
        self.calls.append("send_intent")
        assert self.record["identity_id"] == identity_id
        self.record.update(state="SENT", body_sha256=body_sha256, allow_prepare=False, allow_send=True)
        if self.fail == "send_ack":
            raise TimeoutError
        return self.record.copy()

    async def admit_send(self, **_kwargs):
        self.calls.append("admit_send")
        if self.fail == "fenced":
            raise CloudBlocked("FENCED", "synthetic")

    async def record_observation(self, *, identity_id, observation):
        assert identity_id == self.record["identity_id"]
        self.calls.append(observation["state"])
        self.record["allow_send"] = False
        return self.record.copy()

    async def remote_closed(self):
        return False

    async def observe_business_terminal(self, identity_id, operation_key, *, observer, signer, validate_output):
        assert identity_id == self.record["identity_id"]
        assert operation_key == self.record["operation_key"] and observer is not None and signer is not None
        projection = {"business_terminal": True, "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"}
        await validate_output({"controlled_action_observation": projection})
        self.calls.append("observe_original")
        self.record["observations"] = [{"state": "BUSINESS_TERMINAL", "observation": {"projection": projection}}]
        return {"projection": projection}


class Signer:
    def __init__(self):
        self.calls = []

    async def prepare(self, _action, client_ref, unique_ref, *, identity_id):
        assert identity_id
        self.calls.append("prepare")
        return json.dumps({**prepared(), "clientOrderId": client_ref, "uniqueUserKey": unique_ref}).encode()

    async def verify(self, _action, _body, *, identity_id):
        assert identity_id
        self.calls.append("verify")
        return True


class Credentials:
    async def api_key(self, _action, *, identity_id):
        assert identity_id
        return b"synthetic-key"


class Transport:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def send(self, *, before_send, sent_body_sha256, **_kwargs):
        await before_send(sent_body_sha256)
        self.calls.append("POST")
        if self.fail:
            raise CloudBlocked("TRANSPORT_UNKNOWN", "synthetic")
        return HttpExchange(200, b'{"code":200}')


@pytest.fixture
def components(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    authority, signer, transport = Authority(), Signer(), Transport()
    async def validate(_payload):
        pass
    async def preflight(_action):
        return True
    broker = ActionBroker(tmp_path / "broker.sock", task_id=str(uuid4()), profile=profile(), authority=authority,
        signer=signer, credentials=Credentials(), private_root=private, deadline=9999999999,
        validate_output=validate, preflight=preflight, transport=transport)
    return broker, authority, signer, transport, private


@pytest.mark.asyncio
async def test_http_200_is_observed_once_but_never_terminal(components):
    broker, authority, signer, transport, private = components
    result = await broker.invoke("swap-2")
    assert result["status"] == "HTTP_OBSERVED" and result["business_terminal"] is False
    assert authority.calls == ["identity", "send_intent", "admit_send", "HTTP_OBSERVED"]
    assert signer.calls == ["prepare", "verify"] and transport.calls == ["POST"]
    original = ActionOriginals(private).load(result["operation"]["identity_id"])
    assert original["http_status"] == 200 and original["body"] == b'{"code":200}'
    assert (await broker.invoke("swap-2"))["status"] == "ORIGINAL"
    assert transport.calls == ["POST"]
    await broker.close()
    assert await broker.drained() is False  # Business outcome has not been observed.


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["identity_ack", "send_ack", "fenced", "transport"])
async def test_lost_ack_fence_and_unknown_never_replay(components, failure):
    broker, authority, signer, transport, _ = components
    if failure == "transport":
        transport.fail = True
    else:
        authority.fail = failure
    result = await broker.invoke("swap-2")
    assert result["status"] == "UNKNOWN"
    sent = list(transport.calls)
    assert len(sent) == (1 if failure == "transport" else 0)
    again = await broker.invoke("swap-2")
    assert again["status"] == "ORIGINAL" and transport.calls == sent
    if failure == "identity_ack":
        assert signer.calls == []
    if failure == "transport":
        assert "UNKNOWN" in authority.calls


@pytest.mark.asyncio
async def test_missing_preflight_blocks_before_any_business_identity_or_post(components):
    broker, authority, signer, transport, _ = components
    async def unavailable(_action):
        return False
    broker.preflight = unavailable
    result = await broker.invoke("swap-2")
    assert result == {"status": "BLOCKED", "code": "CONTROLLED_ACTION_PREFLIGHT_UNAVAILABLE"}
    assert authority.calls == [] and signer.calls == [] and transport.calls == []


@pytest.mark.asyncio
async def test_broker_returns_only_allowlisted_preflight_code(components):
    broker, authority, _, transport, _ = components
    async def denied(_action):
        raise CloudBlocked("CONTROLLED_ACTION_PREFLIGHT_BALANCE_UNAVAILABLE", "SYNTHETIC-SECRET")
    broker.preflight = denied
    result = await broker.invoke("swap-2")
    assert result == {"status": "BLOCKED", "code": "CONTROLLED_ACTION_PREFLIGHT_BALANCE_UNAVAILABLE"}
    assert "SYNTHETIC" not in json.dumps(result) and authority.calls == [] and transport.calls == []


@pytest.mark.asyncio
async def test_observe_uses_only_frozen_action_and_original_sent_identity(components):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    missing = await broker.observe("swap-2")
    assert missing["status"] == "UNKNOWN" and transport.calls == []
    await broker.invoke("swap-2")
    result = await broker.observe("swap-2")
    assert result["status"] == "BUSINESS_TERMINAL"
    assert result["observation"]["chain_receipt"] == "UNOBSERVED"
    assert authority.calls[-1] == "observe_original" and transport.calls == ["POST"]
    assert (await broker.observe("swap-2"))["status"] == "BUSINESS_TERMINAL"
    assert (await broker.query("swap-2"))["status"] == "ORIGINAL"
    with pytest.raises(CloudBlocked):
        await broker.observe("unapproved-action")


@pytest.mark.asyncio
async def test_close_observes_only_the_original_action_without_resending(components):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    await broker.invoke("swap-2")

    async def remote_closed():
        return bool(authority.record.get("observations"))

    authority.remote_closed = remote_closed
    assert await broker.observe_before_close(deadline=time.monotonic() + 1)
    assert authority.calls.count("observe_original") == 1
    assert transport.calls == ["POST"]
    with pytest.raises(CloudBlocked):
        await broker.invoke("swap-4")
    await broker.close()
    assert await broker.drained()


@pytest.mark.asyncio
async def test_close_keeps_unknown_when_original_was_not_sent(components):
    broker, authority, _, transport, _ = components
    authority.fail = "identity_ack"
    await broker.invoke("swap-2")
    broker.observer = object()
    assert not await broker.observe_before_close(deadline=time.monotonic() + 1)
    assert "observe_original" not in authority.calls and transport.calls == []


@pytest.mark.asyncio
async def test_close_keeps_unknown_at_deadline_without_resending(components):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    await broker.invoke("swap-2")

    async def pending(*_args, **_kwargs):
        await asyncio.sleep(1)

    authority.observe_business_terminal = pending
    assert not await broker.observe_before_close(deadline=time.monotonic() + 0.02)
    assert transport.calls == ["POST"]


@pytest.mark.asyncio
async def test_close_quiesces_existing_handlers_and_rejects_new_actions(components):
    broker, authority, _, transport, _ = components
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler():
        entered.set()
        await release.wait()

    async def remote_closed():
        return True

    authority.remote_closed = remote_closed
    active = asyncio.create_task(handler())
    broker._handlers.add(active)
    active.add_done_callback(broker._handlers.discard)
    await entered.wait()
    closing = asyncio.create_task(broker.observe_before_close(deadline=time.monotonic() + 1))
    await asyncio.sleep(0)
    assert not closing.done()
    with pytest.raises(CloudBlocked):
        await broker.invoke("swap-2")
    release.set()
    assert await closing
    assert transport.calls == []


@pytest.mark.asyncio
async def test_close_propagates_lost_authority_cancellation(components):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    await broker.invoke("swap-2")

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    authority.observe_business_terminal = cancelled
    with pytest.raises(asyncio.CancelledError):
        await broker.observe_before_close(deadline=time.monotonic() + 1)
    assert transport.calls == ["POST"]


@pytest.mark.asyncio
async def test_socket_rejects_agent_supplied_terminal_or_order_id(components):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    with tempfile.TemporaryDirectory(prefix="ht-a-", dir=os.path.realpath("/tmp")) as directory:
        broker.socket_path = Path(directory) / "broker.sock"
        await broker.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(broker.socket_path))
            writer.write(json.dumps({"verb": "OBSERVE", "action_key": "swap-2", "order_id": "fake"}).encode() + b"\n")
            await writer.drain()
            assert json.loads(await reader.readline())["status"] == "UNKNOWN"
            writer.close()
            await writer.wait_closed()
            assert authority.calls == [] and transport.calls == []
        finally:
            await broker.close()


def test_private_original_cannot_be_overwritten_or_replaced_by_symlink(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    originals = ActionOriginals(root)
    original_id = str(uuid4())
    originals.save(original_id, b"fixture", http_status=200, observed_at=1)
    with pytest.raises(CloudBlocked):
        originals.save(original_id, b"different", http_status=200, observed_at=2)
    path = root / (original_id + ".response")
    path.unlink()
    path.symlink_to(tmp_path / "untrusted")
    with pytest.raises(CloudBlocked):
        originals.load(original_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("raised,expected", [
    ("CONTROLLED_ACTION_OBSERVE_DETAIL_GET_UNAVAILABLE", "CONTROLLED_ACTION_OBSERVE_DETAIL_GET_UNAVAILABLE"),
    ("SYNTHETIC-SECRET", "CONTROLLED_ACTION_OBSERVE_AUTHORITY_UNAVAILABLE"),
])
async def test_observe_exposes_only_allowlisted_stage(components, raised, expected):
    broker, authority, _, transport, _ = components
    broker.observer = object()
    await broker.invoke("swap-2")
    async def fail(*_args, **_kwargs):
        raise CloudBlocked(raised, "SYNTHETIC-SECRET")
    authority.observe_business_terminal = fail
    result = await broker.observe("swap-2")
    assert result["status"] == "UNKNOWN" and result["code"] == expected
    assert "SYNTHETIC-SECRET" not in json.dumps(result)
    assert transport.calls == ["POST"]
