"""Exercise the broker against the dedicated synthetic ledger and observer."""
import base64
import json
import time
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_cloud_action_ledger import action_context as action_context

from hypertest.application.cloud_ssh import ensure_remote_closed
from hypertest.cloud.action_broker import ActionBroker
from hypertest.cloud.action_observer import ActionObserver
from hypertest.cloud.action_signer import ActionCredentials, ActionSigner
from hypertest.cloud.http_transport import HttpExchange
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudTask

pytest_plugins = ("test_cloud_tasks",)


@pytest.mark.asyncio
async def test_broker_sends_once_and_closes_only_on_original_terminal(action_context, tmp_path, monkeypatch):
    context = action_context
    authority = context["authority"]
    task_id = context["current"]["task_id"]
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(task_id))
        profile = task.inputs["controlled_actions"]
    signer = object.__new__(ActionSigner)
    observer = object.__new__(ActionObserver)
    observer.profile = profile
    calls = []

    async def prepare(_action, client_ref, unique_ref, *, identity_id):
        return json.dumps({"amount": "2", "clientOrderId": client_ref, "uniqueUserKey": unique_ref,
            "sign": base64.b64encode(b"s" * 256).decode()}).encode()

    async def verify(_action, _body, *, identity_id):
        return True

    async def preflight(_action):
        return True

    async def validate_output(_value):
        pass

    async def observe(*, operation_key, **_kwargs):
        record = await authority.get_by_key(operation_key)
        calls.append("GET original")
        return {"projection": {"profile": "observation/v1", "client_order_id": record["client_ref"],
            "order_id": "42", "business_status": "Completed", "business_terminal": True,
            "details": [{"detail_id": "5", "transaction_type": "Uniswap", "status": "Success",
                "tx_hash": "a" * 64, "block_number": "20", "confirmations": 2, "required_confirmations": 1}],
            "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"},
            "order_response_sha256": "a" * 64, "details_response_sha256": "b" * 64, "observed_at": int(time.time())}

    class Transport:
        async def send(self, *, before_send, sent_body_sha256, **_kwargs):
            await before_send(sent_body_sha256)
            calls.append("POST once")
            return HttpExchange(200, b'{"code":200}')

    monkeypatch.setattr(signer, "prepare", prepare)
    monkeypatch.setattr(signer, "verify", verify)
    monkeypatch.setattr(observer, "observe", observe)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    broker = ActionBroker(tmp_path / "broker.sock", task_id=task_id, profile=profile, authority=authority,
        signer=signer, credentials=ActionCredentials(authority), private_root=private, deadline=int(time.time()) + 120,
        validate_output=validate_output, preflight=preflight, observer=observer, transport=Transport())
    assert (await broker.invoke("swap-2"))["status"] == "HTTP_OBSERVED"
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_remote_closed(db, task_id=UUID(task_id))
    assert (await broker.observe("swap-2"))["status"] == "BUSINESS_TERMINAL"
    assert (await broker.observe("swap-2"))["status"] == "BUSINESS_TERMINAL"
    assert (await broker.invoke("swap-2"))["status"] == "ORIGINAL"
    assert calls == ["POST once", "GET original"]
    async with AsyncSessionLocal() as db:
        await ensure_remote_closed(db, task_id=UUID(task_id))
