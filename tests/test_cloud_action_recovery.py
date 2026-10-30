"""Original action observation under a scoped operator recovery receipt."""
import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_cloud_tasks import post

from hypertest.application import cloud_tasks
from hypertest.application.cloud_action_recovery import ActionRecoveryAuthority
from hypertest.cloud.action_observer import ActionObserver
from hypertest.cloud.action_signer import ActionSigner
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal

pytest_plugins = ("test_cloud_action_ledger",)


@pytest.fixture
async def recovery_context(action_context, monkeypatch):
    context = action_context
    original = await context["authority"].prepare_identity(action_key="swap-2", operation_key="original-key",
        client_ref="client-original", unique_ref="unique-original")
    await context["authority"].prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    op_context = {**context, "headers": context["operator_headers"]}
    fields = {"task_id": context["current"]["task_id"], "attempt_id": context["current"]["attempt_id"],
              "identity_id": original["identity_id"], "original_operation_key": "original-key"}
    before = await post(op_context, "AUTHORIZE_ACTION_OBSERVATION", context["current"]["version"], **fields)
    assert before.status_code == 409
    async with AsyncSessionLocal() as db:
        assert await cloud_tasks.fence_attempt_for_recovery(db, UUID(fields["task_id"]), UUID(fields["attempt_id"]),
                                                           context["identity"], "WORKER_RUNTIME_FAILED")
    stopped = {"value": False}
    async def ensure(_db, _task):
        if not stopped["value"]:
            raise HTTPException(409, "CLOUD_CONTAINER_UNRECONCILED")
    async def intents(_db, _task):
        return [{"attempt_id": fields["attempt_id"], "operation_key": "container-original"}]
    async def observations(_db, _task):
        return ([{"attempt_id": fields["attempt_id"], "state": "STOPPED", "create_operation_key": "container-original"}]
                if stopped["value"] else [])
    monkeypatch.setattr(cloud_tasks, "_ensure_container_closed", ensure)
    monkeypatch.setattr(cloud_tasks, "_container_intents", intents)
    monkeypatch.setattr(cloud_tasks, "_container_observations", observations)
    denied = await post(op_context, "AUTHORIZE_ACTION_OBSERVATION", context["current"]["version"], **fields)
    assert denied.status_code == 409
    stopped["value"] = True
    interactive = await post(context, "AUTHORIZE_ACTION_OBSERVATION", context["current"]["version"], **fields)
    assert interactive.status_code == 403
    accepted = await post(op_context, "AUTHORIZE_ACTION_OBSERVATION", context["current"]["version"], **fields)
    assert accepted.status_code == 200, accepted.text
    authority = ActionRecoveryAuthority(AsyncSessionLocal, task_id=fields["task_id"], attempt_id=fields["attempt_id"],
                                        authorization_key=accepted.json()["operation_key"])
    return {**context, "original": original, "recovery": authority, "stop": stopped, "op": accepted.json()}


def _trusted_objects(task, attempt):
    observer = object.__new__(ActionObserver)
    observer.profile = task.inputs["controlled_actions"]
    signer = object.__new__(ActionSigner)
    signer.profile = observer.profile
    signer.export_policy = task.inputs["agent_source_export"]
    signer.source_root = Path(get_settings().cloud_runtime_root) / ("attempt-" + str(attempt.id)) / "private-signer-source"
    return observer, signer


@pytest.mark.asyncio
async def test_original_only_read_grant_and_unobserved_do_not_close(recovery_context, monkeypatch):
    context, authority = recovery_context, recovery_context["recovery"]
    original = context["original"]
    assert not hasattr(authority, "prepare_send") and not hasattr(authority, "prepare_identity")
    with pytest.raises(HTTPException, match="NOT_FOUND_QUERY_ONLY"):
        await authority.get_by_key("replacement-key")
    with pytest.raises(HTTPException, match="CREDENTIAL_ROLE_INVALID"):
        await authority.materialize_credential(identity_id=original["identity_id"], role="signing_key")
    assert await authority.materialize_credential(identity_id=original["identity_id"], role="observer_oauth") == b"synthetic-private-credential-2"
    async with AsyncSessionLocal() as db:
        task, attempt, *_ = await authority._checked(db)
    observer, signer = _trusted_objects(task, attempt)
    projection = {"profile": "observation/v1", "client_order_id": "client-original", "order_id": "42",
        "business_status": "Processing", "business_terminal": False, "details": [], "chain_receipt": "UNOBSERVED",
        "actual_trx_received": "UNOBSERVED"}
    async def observe(**_kwargs):
        return {"projection": projection, "order_response_sha256": "a" * 64,
                "details_response_sha256": "b" * 64, "observed_at": int(time.time())}
    monkeypatch.setattr(observer, "observe", observe)
    result = await authority.observe_original(observer=observer, signer=signer)
    assert result["business_terminal"] is False and result["recorded"] is False
    async with AsyncSessionLocal() as db:
        from hypertest.application.cloud_actions import ensure_actions_closed
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_actions_closed(db, task_id=UUID(context["current"]["task_id"]))
    context["stop"]["value"] = False
    with pytest.raises(HTTPException, match="CONTAINER_UNRECONCILED"):
        await authority.get_by_key("original-key")


@pytest.mark.asyncio
async def test_recovery_rechecks_revoked_observer_and_rejects_fake_observer(recovery_context):
    context, authority = recovery_context, recovery_context["recovery"]
    with pytest.raises(HTTPException, match="TRUSTED_OBSERVER_REQUIRED"):
        await authority.observe_original(observer={}, signer={})
    revoked = await post(context, "REVOKE_CREDENTIAL", 1,
        credential_id=context["credential_ids"]["observer_oauth"], reason="fixture")
    assert revoked.status_code == 200
    with pytest.raises(HTTPException, match="RECOVERY_AUTHORITY_INVALID"):
        await authority.get_by_key("original-key")


@pytest.mark.asyncio
async def test_recovery_records_only_verified_original_and_replays_immutable_result(recovery_context, monkeypatch):
    context, authority = recovery_context, recovery_context["recovery"]
    async with AsyncSessionLocal() as db:
        task, attempt, *_ = await authority._checked(db)
    observer, signer = _trusted_objects(task, attempt)
    projection = {"profile": "observation/v1", "client_order_id": "client-original", "order_id": "42",
        "business_status": "Completed", "business_terminal": True, "details": [{"detail_id": "5",
            "transaction_type": "Uniswap", "status": "Success", "tx_hash": "a" * 64, "block_number": "20",
            "confirmations": 2, "required_confirmations": 1}], "chain_receipt": "UNOBSERVED",
        "actual_trx_received": "UNOBSERVED"}
    calls = []
    async def observe(**kwargs):
        calls.append((kwargs["identity_id"], kwargs["operation_key"]))
        return {"projection": projection, "order_response_sha256": "a" * 64,
                "details_response_sha256": "b" * 64, "observed_at": int(time.time())}
    monkeypatch.setattr(observer, "observe", observe)
    result = await authority.observe_original(observer=observer, signer=signer)
    assert result == {"projection": projection, "business_terminal": True, "recorded": True}
    assert await authority.observe_original(observer=observer, signer=signer) == result
    assert calls == [(context["original"]["identity_id"], "original-key")]
    async with AsyncSessionLocal() as db:
        from hypertest.application.cloud_actions import ensure_actions_closed
        await ensure_actions_closed(db, task_id=UUID(context["current"]["task_id"]))


@pytest.mark.asyncio
async def test_recovery_rechecks_authorization_after_observe_before_writing(recovery_context, monkeypatch):
    context, authority = recovery_context, recovery_context["recovery"]
    async with AsyncSessionLocal() as db:
        task, attempt, *_ = await authority._checked(db)
    observer, signer = _trusted_objects(task, attempt)
    async def observe(**_kwargs):
        revoked = await post(context, "REVOKE_CREDENTIAL", 1,
            credential_id=context["credential_ids"]["observer_oauth"], reason="fixture")
        assert revoked.status_code == 200
        return {"projection": {"profile": "observation/v1", "client_order_id": "client-original", "order_id": "42",
            "business_status": "Completed", "business_terminal": True, "details": [{"detail_id": "5",
                "transaction_type": "Uniswap", "status": "Success", "tx_hash": "a" * 64, "block_number": "20",
                "confirmations": 2, "required_confirmations": 1}], "chain_receipt": "UNOBSERVED",
            "actual_trx_received": "UNOBSERVED"}, "order_response_sha256": "a" * 64,
            "details_response_sha256": "b" * 64, "observed_at": int(time.time())}
    monkeypatch.setattr(observer, "observe", observe)
    with pytest.raises(HTTPException, match="RECOVERY_AUTHORITY_INVALID"):
        await authority.observe_original(observer=observer, signer=signer)
    async with AsyncSessionLocal() as db:
        from hypertest.application.cloud_actions import ensure_actions_closed
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_actions_closed(db, task_id=UUID(context["current"]["task_id"]))


@pytest.mark.asyncio
async def test_expired_authorization_cannot_read_original(recovery_context, monkeypatch):
    from datetime import timedelta

    authority = recovery_context["recovery"]
    original_clock = cloud_tasks.clock
    async def future(db):
        return await original_clock(db) + timedelta(minutes=6)
    monkeypatch.setattr(cloud_tasks, "clock", future)
    with pytest.raises(HTTPException, match="RECOVERY_AUTHORITY_INVALID"):
        await authority.get_by_key("original-key")


@pytest.mark.asyncio
async def test_recovery_full_original_observer_path_never_uses_business_post(recovery_context, monkeypatch):
    import json

    import httpx
    from test_cloud_action_observer import JsonStream

    context, authority = recovery_context, recovery_context["recovery"]
    async with AsyncSessionLocal() as db:
        task, attempt, *_ = await authority._checked(db)
    _, signer = _trusted_objects(task, attempt)
    requests = []
    order = {"id": "42", "clientOrderId": "client-original", "status": "Completed", "walletId": 42,
             "fromChain": "TRON_TEST", "toChain": "TRON_TEST", "fromCoinCode": "TRON_TESTUSDT",
             "toCoinCode": "TRON_TESTTRX", "amount": "2000000", "fromAddress": "synthetic-address",
             "transactionType": "Uniswap"}
    detail = {"id": "5", "orderId": "42", "transactionType": "Uniswap", "status": "Success",
              "txHash": "a" * 64, "blockNumber": "20", "confirmations": 2, "requiredConfirmations": 1,
              "signedTransaction": "SYNTHETIC-PRIVATE-PAYLOAD"}
    def handler(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/oauth/token":
            return httpx.Response(200, stream=JsonStream({"code": 200, "data": {"access_token": "fake-token"}}))
        if request.url.path == "/orders/client/client-original":
            return httpx.Response(200, stream=JsonStream({"code": 200, "data": order}))
        if request.url.path == "/orders/42/with-details":
            return httpx.Response(200, stream=JsonStream({"code": 200, "data": {**order, "details": [detail]}}))
        raise AssertionError("unexpected endpoint")
    async def resolver(_host, _port):
        return ["8.8.8.8"]
    observer = ActionObserver(profile=signer.profile, resolver=resolver, transport=httpx.MockTransport(handler))
    async def credentials(**_kwargs):
        return json.dumps({"username": "fake-user", "password": "fake-password", "client_id": "fake-client",
                           "client_secret": "fake-secret", "grant_type": "password"}).encode()
    monkeypatch.setattr(authority, "materialize_credential", credentials)
    async def project(_action, ref, _first, _details):
        return {"profile": "observation/v1", "client_order_id": ref, "order_id": "42", "business_status": "Completed",
            "business_terminal": True, "details": [{"detail_id": "5", "transaction_type": "Uniswap",
                "status": "Success", "tx_hash": "a" * 64, "block_number": "20", "confirmations": 2,
                "required_confirmations": 1}], "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"}
    monkeypatch.setattr(signer, "observe", project, raising=False)
    result = await authority.observe_original(observer=observer, signer=signer)
    assert result["business_terminal"] is True and result["recorded"] is True
    assert requests == [("POST", "/oauth/token"), ("GET", "/orders/client/client-original"), ("GET", "/orders/42/with-details")]
    assert "SYNTHETIC-PRIVATE-PAYLOAD" not in json.dumps(result)
    assert context["original"]["client_ref"] == result["projection"]["client_order_id"]


@pytest.mark.asyncio
async def test_recovery_authorization_receipt_cannot_be_updated_or_deleted(recovery_context):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_operation_receipts SET actor_ref='operator:forged' "
                                  "WHERE project_id=:project AND operation_key=:key"),
                {"project": UUID(recovery_context["project_id"]), "key": recovery_context["op"]["operation_key"]})
    async with AsyncSessionLocal() as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("DELETE FROM cloud_operation_receipts WHERE project_id=:project AND operation_key=:key"),
                {"project": UUID(recovery_context["project_id"]), "key": recovery_context["op"]["operation_key"]})
