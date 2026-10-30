"""Side-effecting action admission and original-key recovery in a test DB."""
import asyncio
import time
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import FRAMEWORK_SHA, claimed, configuration, inputs, post, worker_submit

from hypertest.application import cloud_actions, cloud_tasks
from hypertest.application.cloud_actions import WorkerActionAuthority
from hypertest.application.cloud_ssh import ensure_remote_closed
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_actions import CloudActionIdentity, CloudActionSend

pytest_plugins = ("test_cloud_tasks",)
TARGET = "https://api.example.invalid:443"
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.fixture
async def action_context(cloud_context, monkeypatch):
    monkeypatch.setattr(cloud_actions, "controlled_actions_enabled", lambda: True)
    credentials, credential_ids = {}, {}
    for index, role in enumerate(("api_key", "signing_key", "observer_oauth")):
        result = await post(cloud_context, "STORE_CREDENTIAL", kind="APPLICATION_PRIVATE_KEY", label=role,
            purpose="controlled-action-" + role.replace("_", "-"), allowed_targets=[TARGET],
            allowed_actions=["environment:read" if role == "observer_oauth" else "environment:write"],
            secret=f"synthetic-private-credential-{index}")
        assert result.status_code == 200, result.text
        credentials[role] = result.json()["credential_version_id"]
        credential_ids[role] = result.json()["credential_id"]
    task_inputs = inputs()
    task_inputs["authorization"]["targets"].append(TARGET)
    task_inputs["authorization"]["targets"].append("api.example.invalid")
    task_inputs["authorization"]["network_targets"] = [TARGET]
    task_inputs["authorization"]["permitted_actions"].extend(["environment:read", "environment:write"])
    task_inputs["agent_source_export"] = {"profile": "cloud-agent-source-export/v1",
        "sut": [{"path": "main.py", "sha256": "a" * 64}],
        "framework": [{"path": "python/trusted/adapter.py", "sha256": "a" * 64},
                      {"path": "python/trusted/observer.py", "sha256": "c" * 64}]}
    task_inputs["controlled_actions"] = {"profile": "CONTROLLED_ACTIONS_V1", "target": TARGET,
        "allowed_addresses": ["8.8.8.8"], "max_operations": 4, "actions": [{
            "action_key": "swap-2", "method": "POST", "path": "/api/test/dex",
            "parameters": {"amount": "2"}, "expected_body": {"amount": "2"},
            "identity_fields": {"client_ref": "clientOrderId", "unique_ref": "uniqueUserKey", "signature": "sign"},
            "credential_version_ids": credentials, "framework_commit": FRAMEWORK_SHA,
            "adapter_path": "python/trusted/adapter.py", "adapter_import_root": "python", "adapter_sha256": "a" * 64,
            "signature_policy": {"profile": "RSA_SHA256_SORTED_FIELDS_V1", "excluded_fields": ["class", "sign", "signature"]},
            "observer": {"adapter_path": "python/trusted/observer.py", "adapter_import_root": "python", "adapter_sha256": "c" * 64,
                "profile": "observer/v1", "observed_profile": "observation/v1", "oauth_path": "/oauth/token",
                "client_order_path_prefix": "/orders/client/", "order_detail_path_prefix": "/orders/",
                "order_detail_path_suffix": "/with-details", "order_id_path": ["data", "id"], "expectations": {"wallet_id": "fixture"},
                "preflight_profile": "preflight/v1", "preflight_observed_profile": "preflight-observed/v1",
                "address_page_path": "/addresses", "address_page_query": {"walletId": "fixture"},
                "address_balance_path": "/addresses/balance/fixture", "terminal_transaction_type": "Uniswap"},
            "adapter_protocol": {"prepare": "fixture-prepare/v1", "prepared": "fixture-prepared/v1",
                "verify": "fixture-verify/v1", "verified": "fixture-verified/v1", "client_ref_field": "client_order_id",
                "unique_ref_field": "unique_user_key", "secret_field": "signing_key"}}]}
    action = task_inputs["controlled_actions"]["actions"][0]
    action["expected_body"] = {"amount": "2000000", "chainName": "TRON_TEST", "fromAddress": "synthetic-address"}
    action["observer"]["expectations"] = {"wallet_id": "42", "chain": "TRON_TEST", "from_coin_code": "TRON_TESTUSDT",
        "to_coin_code": "TRON_TESTTRX", "amount_atomic": "2000000", "from_address": "synthetic-address"}
    environment = {"name": "Synthetic HTTPS", "connection": "HTTPS", "host": "api.example.invalid",
                   "port": 443, "cloud_access_policy": "WEB_ONLY"}
    current, claim, identity = await claimed(cloud_context, config=configuration(environment=environment), task_inputs=task_inputs)
    running = await worker_submit(cloud_context, identity, current, "TRANSITION", status="RUNNING",
        budget_reservation={"reserved_seconds": 300,
            "request_limits": [{"scope": "ROOT", "max_requests": 2, "cost_per_request_microunits": 1}]})
    authority = WorkerActionAuthority(AsyncSessionLocal, task_id=current["task_id"],
        attempt_id=current["attempt_id"], identity=identity)
    return {**cloud_context, "current": running, "claim": claim, "identity": identity,
            "authority": authority, "credential_ids": credential_ids}


async def test_original_identity_and_send_are_single_use_even_with_concurrency(action_context):
    context, authority = action_context, action_context["authority"]
    original = await authority.prepare_identity(action_key="swap-2", operation_key="operation-2",
        client_ref="client-order-2", unique_ref="unique-order-2")
    assert original["state"] == "IDENTIFIED" and original["allow_prepare"] is True and original["allow_send"] is False
    replay = await authority.prepare_identity(action_key="swap-2", operation_key="operation-2",
        client_ref="client-order-2", unique_ref="unique-order-2")
    assert replay["allow_prepare"] is False and replay["identity_id"] == original["identity_id"]
    assert await authority.materialize_credential(identity_id=original["identity_id"], role="api_key") == b"synthetic-private-credential-0"
    with pytest.raises(HTTPException, match="CREDENTIAL_ROLE_INVALID"):
        await authority.materialize_credential(identity_id=original["identity_id"], role="git_token")
    with pytest.raises(HTTPException, match="SEND_AUTHORITY_INVALID"):
        await authority.admit_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    senders = await asyncio.gather(*(authority.prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)
                                     for _ in range(2)))
    assert sum(result["allow_send"] for result in senders) == 1
    assert all(result["state"] == "SENT" and result["body_sha256"] == "b" * 64 for result in senders)
    with pytest.raises(HTTPException, match="SIGNER_AFTER_SEND_REFUSED"):
        await authority.materialize_credential(identity_id=original["identity_id"], role="signing_key")
    await authority.admit_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    with pytest.raises(HTTPException, match="SEND_AUTHORITY_INVALID"):
        await authority.admit_send(identity_id=original["identity_id"], body_sha256="c" * 64)
    recovered = await authority.get_by_key("operation-2")
    assert recovered["allow_send"] is False and recovered["send_id"] == senders[0]["send_id"]
    with pytest.raises(HTTPException, match="ORIGINAL_SEND_CONFLICT"):
        await authority.prepare_send(identity_id=original["identity_id"], body_sha256="c" * 64)
    with pytest.raises(HTTPException, match="ORIGINAL_IDENTITY_CONFLICT"):
        await authority.prepare_identity(action_key="swap-2", operation_key="other-key",
            client_ref="other-order", unique_ref="other-unique")
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudActionIdentity).where(
            CloudActionIdentity.attempt_id == UUID(context["current"]["attempt_id"]))) == 1
        assert await db.scalar(select(func.count()).select_from(CloudActionSend).where(
            CloudActionSend.attempt_id == UUID(context["current"]["attempt_id"]))) == 1
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_action_sends SET body_sha256=:digest WHERE id=:id"),
                {"digest": "d" * 64, "id": UUID(recovered["send_id"])})
    assert context["identity"].work_token not in str(recovered)


async def test_http_and_unknown_do_not_close_action_or_accept_agent_terminal(action_context):
    context, authority = action_context, action_context["authority"]
    original = await authority.prepare_identity(action_key="swap-2", operation_key="operation-observe",
        client_ref="client-observe", unique_ref="unique-observe")
    await authority.prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    observed = {"state": "HTTP_OBSERVED", "http_status": 200, "body_sha256": "c" * 64,
        "byte_count": 16, "reason": "RESPONSE_OBSERVED", "observed_at": int(time.time())}
    result = await authority.record_observation(identity_id=original["identity_id"], observation=observed)
    assert result["observations"][0]["state"] == "HTTP_OBSERVED"
    summary = await context["client"].get(f"/api/v1/cloud/tasks/{context['current']['task_id']}/summary",
        headers=context["headers"], params={"project_id": context["project_id"]})
    assert summary.status_code == 200
    assert summary.json()["controlled_actions"][0]["state"] == "SENT_UNRECONCILED"
    assert "CLOUD_ACTION_BUSINESS_UNRECONCILED" in summary.json()["recovery"]["blocking_reasons"]
    with pytest.raises(HTTPException, match="HTTP_OBSERVATION_CONFLICT"):
        await authority.record_observation(identity_id=original["identity_id"], observation={**observed, "body_sha256": "d" * 64})
    unknown = {"state": "UNKNOWN", "http_status": None, "body_sha256": EMPTY, "byte_count": 0,
        "reason": "TRANSPORT_UNKNOWN", "observed_at": int(time.time())}
    await authority.record_observation(identity_id=original["identity_id"], observation=unknown)
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
    with pytest.raises(HTTPException, match="TERMINAL_VERIFIER_UNAVAILABLE"):
        await authority.record_business_terminal(identity_id=original["identity_id"], status="completed")
    with pytest.raises(HTTPException, match="NOT_FOUND_QUERY_ONLY"):
        await authority.get_by_key("missing")
    wrong_task = WorkerActionAuthority(AsyncSessionLocal, task_id=str(uuid4()),
        attempt_id=context["current"]["attempt_id"], identity=context["identity"])
    with pytest.raises(HTTPException, match="NOT_FOUND_QUERY_ONLY"):
        await wrong_task.get_by_key("operation-observe")


async def test_disabled_stale_and_wrong_attempt_never_send(action_context, monkeypatch):
    context, authority = action_context, action_context["authority"]
    monkeypatch.setattr(cloud_actions, "controlled_actions_enabled", lambda: False)
    with pytest.raises(HTTPException, match="LEDGER_UNAVAILABLE"):
        await authority.prepare_identity(action_key="swap-2", operation_key="disabled", client_ref="x", unique_ref="y")
    monkeypatch.setattr(cloud_actions, "controlled_actions_enabled", lambda: True)
    identity = context["identity"]
    stale = cloud_tasks.WorkerIdentity(identity.worker_id, identity.lease_token, identity.generation + 1, identity.work_token)
    wrong = WorkerActionAuthority(AsyncSessionLocal, task_id=context["current"]["task_id"],
        attempt_id=context["current"]["attempt_id"], identity=stale)
    with pytest.raises(HTTPException):
        await wrong.prepare_identity(action_key="swap-2", operation_key="stale", client_ref="x", unique_ref="y")
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudActionSend).where(
            CloudActionSend.attempt_id == UUID(context["current"]["attempt_id"]))) == 0


async def test_revoked_credential_and_environment_mismatch_reject_identity(action_context, monkeypatch):
    context, authority = action_context, action_context["authority"]
    original_target = cloud_actions.canonical_target
    monkeypatch.setattr(cloud_actions, "canonical_target", lambda *_: "https://other.invalid:443")
    with pytest.raises(HTTPException, match="ENVIRONMENT_MISMATCH"):
        await authority.prepare_identity(action_key="swap-2", operation_key="different-target", client_ref="x", unique_ref="y")
    monkeypatch.setattr(cloud_actions, "canonical_target", original_target)
    revoked = await post(context, "REVOKE_CREDENTIAL", 1, credential_id=context["credential_ids"]["signing_key"], reason="fixture")
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(HTTPException, match="CREDENTIAL_SCOPE_REQUIRED"):
        await authority.prepare_identity(action_key="swap-2", operation_key="revoked", client_ref="x", unique_ref="y")


async def test_credential_revocation_blocks_send_and_further_materialization(action_context):
    context, authority = action_context, action_context["authority"]
    original = await authority.prepare_identity(action_key="swap-2", operation_key="before-revoke",
        client_ref="client-revoke", unique_ref="unique-revoke")
    revoked = await post(context, "REVOKE_CREDENTIAL", 1, credential_id=context["credential_ids"]["signing_key"], reason="fixture")
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(HTTPException, match="CREDENTIAL_SCOPE_REQUIRED"):
        await authority.materialize_credential(identity_id=original["identity_id"], role="api_key")
    with pytest.raises(HTTPException, match="CREDENTIAL_SCOPE_REQUIRED"):
        await authority.prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)


async def test_preflight_requires_original_scoped_live_authority(action_context):
    context, authority = action_context, action_context["authority"]
    await authority.admit_preflight(action_key="swap-2")
    assert await authority.materialize_preflight_credential(action_key="swap-2") == b"synthetic-private-credential-2"
    with pytest.raises(HTTPException):
        await authority.materialize_preflight_credential(action_key="unapproved")
    revoked = await post(context, "REVOKE_CREDENTIAL", 1,
        credential_id=context["credential_ids"]["observer_oauth"], reason="fixture")
    assert revoked.status_code == 200
    with pytest.raises(HTTPException, match="CREDENTIAL_SCOPE_REQUIRED"):
        await authority.materialize_preflight_credential(action_key="swap-2")


async def test_terminal_observation_only_from_worker_and_original_key(action_context, monkeypatch):
    from hypertest.cloud.action_observer import ActionObserver
    from hypertest.cloud.action_signer import ActionSigner
    from hypertest.domain.cloud_tasks import CloudTask

    context, authority = action_context, action_context["authority"]
    original = await authority.prepare_identity(action_key="swap-2", operation_key="op-terminal",
        client_ref="client-terminal", unique_ref="unique-terminal")
    await authority.prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(context["current"]["task_id"]))
        profile = task.inputs["controlled_actions"]
    observer = object.__new__(ActionObserver)
    observer.profile = profile
    signer = object.__new__(ActionSigner)
    projection = {"profile": "observation/v1", "client_order_id": "client-terminal", "order_id": "42",
        "business_status": "Completed", "business_terminal": True, "details": [{"detail_id": "5",
            "transaction_type": "Uniswap", "status": "Success", "tx_hash": "a" * 64, "block_number": "20",
            "confirmations": 2, "required_confirmations": 1}], "chain_receipt": "UNOBSERVED",
        "actual_trx_received": "UNOBSERVED"}
    calls = []
    async def observe(**_kwargs):
        calls.append(1)
        return {"projection": projection, "order_response_sha256": "a" * 64,
                "details_response_sha256": "b" * 64, "observed_at": int(time.time())}
    async def validate_output(_value):
        pass
    monkeypatch.setattr(observer, "observe", observe)
    with pytest.raises(HTTPException, match="TRUSTED_OBSERVER_REQUIRED"):
        await authority.observe_business_terminal(original["identity_id"], "op-terminal", observer={}, signer=signer,
            validate_output=validate_output)
    with pytest.raises(HTTPException, match="OBSERVATION_AUTHORITY_INVALID"):
        await authority.observe_business_terminal(original["identity_id"], "wrong-key", observer=observer, signer=signer,
            validate_output=validate_output)
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
    result = await authority.observe_business_terminal(original["identity_id"], "op-terminal", observer=observer,
        signer=signer, validate_output=validate_output)
    assert result == {"projection": projection, "business_terminal": True, "recorded": True}
    replay = await authority.observe_business_terminal(original["identity_id"], "op-terminal", observer=observer,
        signer=signer, validate_output=validate_output)
    assert replay == result and calls == [1]
    async with AsyncSessionLocal() as db:
        await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE cloud_action_observations SET observation_sha256=:digest WHERE state='BUSINESS_TERMINAL'"),
                             {"digest": "d" * 64})


async def test_nonterminal_and_revocation_do_not_close_original(action_context, monkeypatch):
    from hypertest.cloud.action_observer import ActionObserver
    from hypertest.cloud.action_signer import ActionSigner
    from hypertest.domain.cloud_tasks import CloudTask

    context, authority = action_context, action_context["authority"]
    original = await authority.prepare_identity(action_key="swap-2", operation_key="op-unknown",
        client_ref="client-unknown", unique_ref="unique-unknown")
    await authority.prepare_send(identity_id=original["identity_id"], body_sha256="b" * 64)
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(context["current"]["task_id"]))
        profile = task.inputs["controlled_actions"]
    observer = object.__new__(ActionObserver)
    observer.profile = profile
    signer = object.__new__(ActionSigner)
    projection = {"profile": "observation/v1", "client_order_id": "client-unknown", "order_id": "42",
        "business_status": "Processing", "business_terminal": False, "details": [],
        "chain_receipt": "UNOBSERVED", "actual_trx_received": "UNOBSERVED"}
    async def observe(**_kwargs):
        return {"projection": projection, "order_response_sha256": "a" * 64,
                "details_response_sha256": "b" * 64, "observed_at": int(time.time())}
    async def validate_output(_value):
        pass
    monkeypatch.setattr(observer, "observe", observe)
    result = await authority.observe_business_terminal(original["identity_id"], "op-unknown", observer=observer,
        signer=signer, validate_output=validate_output)
    assert result["business_terminal"] is False and result["recorded"] is False
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException, match="BUSINESS_UNRECONCILED"):
            await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
    revoked = await post(context, "REVOKE_CREDENTIAL", 1,
        credential_id=context["credential_ids"]["observer_oauth"], reason="fixture")
    assert revoked.status_code == 200
    with pytest.raises(HTTPException, match="CREDENTIAL_SCOPE_REQUIRED"):
        await authority.observe_business_terminal(original["identity_id"], "op-unknown", observer=observer,
            signer=signer, validate_output=validate_output)
