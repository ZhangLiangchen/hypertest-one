"""Controlled HTTPS authority uses disposable PostgreSQL fixtures only.

All addresses, responses and toolchain hashes below are declared fixture values.
No DNS lookup, HTTP connection, model, checkout or framework execution occurs.
"""
import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import claimed, configuration, inputs, post, read_all, worker_submit
from test_cloud_tasks import cloud_context as cloud_context

from hypertest.application import cloud_tasks as service
from hypertest.application.cloud_http import WorkerHttpAuthority, authorize_environment
from hypertest.application.cloud_ssh import ensure_remote_closed
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_operations import response_document
from hypertest.cloud.http_profile import HTTPS_ACCESS_PROFILE, digest
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_http import CloudHttpObservation, CloudHttpOperation
from hypertest.domain.cloud_tasks import CloudAttempt, CloudWorkGrant

TARGET = "https://api.example.invalid:443"
BODY = b"SYNTHETIC-HTTP-RESPONSE-BODY-NEVER-PERSIST-IN-DB"


def http_environment():
    catalog = {"profile": HTTPS_ACCESS_PROFILE, "target": TARGET,
        "allowed_addresses": ["8.8.8.8"],
        "resources": [{"key": "inspect", "method": "GET", "path": "/fixture/status",
            "timeout_seconds": 10, "response_limit_bytes": 4096}], "max_operations": 4}
    return {"name": "Declared HTTPS fixture; never contacted", "connection": "HTTPS",
        "host": "api.example.invalid", "port": 443, "cloud_access_policy": "WEB_ONLY",
        "https_access": {key: value for key, value in {**catalog, "catalog_sha256": digest(catalog)}.items()
            if key != "target"}}


def http_inputs():
    task_inputs = inputs()
    task_inputs["authorization"]["targets"].append(TARGET)
    task_inputs["authorization"]["network_targets"] = [TARGET]
    task_inputs["authorization"]["permitted_actions"].append("environment:read")
    task_inputs["framework_runtime"] = {"profile": "FRAMEWORK_LOCKED_V1",
        "lockfiles": [{"path": "requirements.lock", "sha256": "a" * 64}],
        "tools": [{"name": "python", "version": "3.12.0", "sha256": "b" * 64}],
        "entrypoints": [{"key": "python -m pytest", "argv": ["python", "-m", "pytest"]}]}
    return task_inputs


@pytest.fixture
async def http_context(cloud_context, monkeypatch):
    monkeypatch.setattr(get_settings(), "cloud_https_enabled", True)
    current, claim, identity = await claimed(cloud_context,
        config=configuration(environment=http_environment()), task_inputs=http_inputs())
    absolute_deadline = int(time.time()) + 120
    running = await worker_submit(cloud_context, identity, current, "TRANSITION", status="RUNNING",
        runtime_metadata={"https": {"profile": HTTPS_ACCESS_PROFILE, "hard_deadline_epoch": absolute_deadline}},
        budget_reservation={"reserved_seconds": 300,
            "request_limits": [{"scope": "ROOT", "max_requests": 2, "cost_per_request_microunits": 1}]})
    authority = WorkerHttpAuthority(AsyncSessionLocal,
        task_id=current["task_id"], attempt_id=current["attempt_id"], identity=identity)
    return {**cloud_context, "current": running, "claim": claim, "identity": identity,
        "authority": authority, "absolute_deadline": absolute_deadline}


@pytest.mark.parametrize("missing", ["target", "network", "action", "expiry", "framework"])
def test_https_admission_requires_exact_target_authorization_and_frozen_framework(missing):
    task_inputs = http_inputs()
    if missing == "target":
        task_inputs["authorization"]["targets"].remove(TARGET)
    elif missing == "network":
        task_inputs["authorization"]["network_targets"] = ["api.example.invalid"]
    elif missing == "action":
        task_inputs["authorization"]["permitted_actions"].remove("environment:read")
    elif missing == "expiry":
        task_inputs["authorization"]["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    else:
        task_inputs.pop("framework_runtime")
    with pytest.raises(HTTPException):
        authorize_environment(SimpleNamespace(inputs=task_inputs), http_environment(), datetime.now(UTC))


async def test_https_sent_commits_before_send_and_same_key_never_resends_or_changes_resource(http_context):
    authority = http_context["authority"]
    first = await authority.prepare_start("original", "inspect")
    assert first["allow_send"] is True and first["state"] == "SENT"
    assert first["request_digest"] == digest(first["request"])
    assert first["request"]["hard_deadline"] <= int(time.time()) + 10
    assert first["request"]["hard_deadline"] <= http_context["absolute_deadline"]
    assert http_context["identity"].work_token not in json.dumps(first)
    # A distinct session sees the row after prepare_start returns: the intent
    # cannot be an uncommitted promise preceding a future connection.
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudHttpOperation, UUID(first["id"]))
        assert row is not None and row.state == "SENT" and row.request == first["request"]
    await authority.admit_send(first["id"])
    repeated = await authority.prepare_start("original", "inspect")
    assert repeated["id"] == first["id"] and repeated["allow_send"] is False
    with pytest.raises(HTTPException, match="KEY_CONFLICT"):
        await authority.prepare_start("original", "different-resource")
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await authority.prepare_start("replacement", "inspect")
    assert await authority.remote_closed() is False


async def test_lost_prepare_ack_recovers_sent_and_unknown_by_original_key_without_creating_any_intent(http_context):
    context, authority = http_context, http_context["authority"]
    original = await authority.prepare_start("lost-prepare-ack", "inspect")
    # The caller lost the returned ID. The key query must remain a read, rather
    # than an alternate entry to prepare_start or another external send.
    sent = await authority.get_operation_by_key("lost-prepare-ack")
    assert sent["id"] == original["id"] and sent["state"] == "SENT" and sent["allow_send"] is False
    await authority.record_response(original["id"], response_document(original["request"], state="UNKNOWN"))
    unknown = await authority.get_operation_by_key("lost-prepare-ack")
    assert unknown["id"] == original["id"] and unknown["state"] == "UNKNOWN" and not unknown["allow_send"]
    with pytest.raises(HTTPException, match="NOT_FOUND_QUERY_ONLY") as missing:
        await authority.get_operation_by_key("missing-original")
    assert missing.value.status_code == 404
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudHttpOperation).where(
            CloudHttpOperation.attempt_id == UUID(context["current"]["attempt_id"]))) == 1


@pytest.mark.parametrize("runtime", ["missing", "expired"])
async def test_https_intent_requires_the_original_absolute_runtime_deadline(cloud_context, monkeypatch, runtime):
    monkeypatch.setattr(get_settings(), "cloud_https_enabled", True)
    current, _, identity = await claimed(cloud_context,
        config=configuration(environment=http_environment()), task_inputs=http_inputs())
    metadata = {} if runtime == "missing" else {
        "https": {"profile": HTTPS_ACCESS_PROFILE, "hard_deadline_epoch": int(time.time()) - 1}}
    await worker_submit(cloud_context, identity, current, "TRANSITION", status="RUNNING",
        runtime_metadata=metadata, budget_reservation={"reserved_seconds": 300,
            "request_limits": [{"scope": "ROOT", "max_requests": 2, "cost_per_request_microunits": 1}]})
    authority = WorkerHttpAuthority(AsyncSessionLocal,
        task_id=current["task_id"], attempt_id=current["attempt_id"], identity=identity)
    expected = "FIXED_RUNTIME_DEADLINE_REQUIRED" if runtime == "missing" else "TASK_DEADLINE_EXHAUSTED"
    with pytest.raises(HTTPException, match=expected):
        await authority.prepare_start("no-new-window", "inspect")
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudHttpOperation).where(
            CloudHttpOperation.attempt_id == UUID(current["attempt_id"]))) == 0


async def test_unknown_https_blocks_completion_reconciliation_and_budget_release(http_context):
    context, authority = http_context, http_context["authority"]
    record = await authority.prepare_start("uncertain", "inspect")
    unknown = response_document(record["request"], state="UNKNOWN")
    result = await authority.record_response(record["id"], unknown)
    assert result["state"] == "UNKNOWN" and result["allow_send"] is False
    async with AsyncSessionLocal() as db:
        summary = await service.task_summary(db, UUID(context["current"]["task_id"]))
        operation = summary["http_operations"][0]
        assert operation["intent_state"] == "SENT" and operation["state"] == "UNKNOWN"
        assert operation["observation"]["reason"] == "TRANSPORT_UNKNOWN"
        assert "HTTPS_REMOTE_OPERATIONS_UNRECONCILED" in summary["recovery"]["blocking_reasons"]
        assert "body_base64" not in operation["observation"]
    assert (await authority.prepare_start("uncertain", "inspect"))["allow_send"] is False
    with pytest.raises(HTTPException, match="HTTPS_REMOTE_OPERATIONS_UNRECONCILED"):
        async with AsyncSessionLocal() as db:
            await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await worker_submit(context, context["identity"], context["current"], "TRANSITION", status="FAILED")
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await worker_submit(context, context["identity"], context["current"], "TRANSITION",
            status="RECOVERY_REQUIRED", usage_seconds=1, cost_microunits=0,
            budget_settlement={"accounting_unit": "CONSERVATIVE_MICROUNITS", "observed_seconds": 1,
                "namespace_stopped": True, "brokers_drained": True, "requests": [{"scope": "ROOT", "requests": 0}]})
    cancelled = await post(context, "CANCEL_ATTEMPT", context["current"]["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], reason="Synthetic cancel")
    assert cancelled.status_code == 200, cancelled.text
    refused = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], status="CANCELLED",
        reason="Operator cannot erase an unknown HTTPS operation", reconciliation={"old_owner_fenced": True,
            "local_processes_stopped": True, "external_operations_reconciled": True,
            "observations": "Synthetic declaration, not an observed HTTP response"})
    assert refused.status_code == 409 and "HTTPS_REMOTE_OPERATIONS_UNRECONCILED" in refused.text
    async with AsyncSessionLocal() as db:
        attempt = await db.get(CloudAttempt, UUID(context["current"]["attempt_id"]))
        assert attempt.status == "RECOVERY_REQUIRED"
        assert attempt.runtime_metadata["budget_reservation"]["state"] == "HELD"
    assert await authority.remote_closed() is False


async def test_fenced_https_owner_cannot_send_observe_or_release_body_but_can_append_unknown(http_context):
    context, authority = http_context, http_context["authority"]
    record = await authority.prepare_start("before-fence", "inspect")
    cancelled = await post(context, "CANCEL_ATTEMPT", context["current"]["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], reason="Synthetic fence")
    assert cancelled.status_code == 200, cancelled.text
    for action in (lambda: authority.admit_send(record["id"]), lambda: authority.validate_output(BODY),
            lambda: authority.record_response(record["id"], response_document(record["request"],
                state="OBSERVED", http_status=200, body=BODY, reason="RESPONSE_OBSERVED"))):
        with pytest.raises(HTTPException):
            await action()
    unknown = response_document(record["request"], state="UNKNOWN", reason="AUTHORITY_LOST")
    result = await authority.record_response(record["id"], unknown)
    assert result["state"] == "UNKNOWN" and not result["allow_send"]
    assert (await authority.get_operation(record["id"]))["state"] == "UNKNOWN"
    assert await authority.remote_closed() is False
    with pytest.raises(HTTPException):
        await authority.prepare_start("new-after-fence", "inspect")


async def test_https_observed_response_is_immutable_metadata_and_preserves_fixed_history(http_context):
    context, authority = http_context, http_context["authority"]
    before = await read_all(context, context["current"]["task_id"], context["current"]["version"])
    record = await authority.prepare_start("response", "inspect")
    observed = response_document(record["request"], state="OBSERVED", http_status=200,
        body=BODY, reason="RESPONSE_OBSERVED")
    result = await authority.record_response(record["id"], observed)
    assert result["state"] == "OBSERVED" and await authority.remote_closed() is True
    assert "body_base64" not in result["response"] and BODY.decode() not in json.dumps(result)
    assert result["response"]["body_sha256"] == hashlib.sha256(BODY).hexdigest()
    await authority.record_response(record["id"], observed)
    async with AsyncSessionLocal() as db:
        rows = list(await db.scalars(select(CloudHttpObservation).where(CloudHttpObservation.operation_id == UUID(record["id"]))))
        assert len(rows) == 1 and "body_base64" not in rows[0].observation
        assert BODY.decode() not in json.dumps(rows[0].observation)
    assert await read_all(context, context["current"]["task_id"], context["current"]["version"]) == before
    assert before["task"]["reported_result"] == "NOT_RUN"
    accepted = await worker_submit(context, context["identity"], context["current"], "SUBMIT_ASSETS",
        assets=[{"kind": "REPORT", "key": "http-metadata", "title": "Synthetic HTTPS response observed",
            "markdown": "A response was observed. No business test result was inferred."}])
    later = await read_all(context, accepted["task_id"], accepted["version"])
    assert len(later["http_operation_results"]) == 1
    assert later["http_operation_results"][0]["observation"]["http_status"] == 200
    assert BODY.decode() not in json.dumps(later) and "body_base64" not in json.dumps(later)
    assert later["task"]["reported_result"] == "NOT_RUN"
    changed = response_document(record["request"], state="OBSERVED", http_status=500,
        body=b"Different synthetic original", reason="RESPONSE_OBSERVED")
    with pytest.raises(HTTPException, match="IMMUTABLE"):
        await authority.record_response(record["id"], changed)


async def test_wrong_worker_capability_cannot_claim_an_original_https_operation(http_context):
    context, authority = http_context, http_context["authority"]
    record = await authority.prepare_start("original-owner", "inspect")
    identity = context["identity"]
    wrong = service.WorkerIdentity(identity.worker_id, identity.lease_token, identity.generation, "wrong-original-capability")
    other = WorkerHttpAuthority(AsyncSessionLocal, task_id=context["current"]["task_id"],
        attempt_id=context["current"]["attempt_id"], identity=wrong)
    with pytest.raises(HTTPException, match="ORIGINAL_OPERATION_OWNER_REQUIRED"):
        await other.get_operation(record["id"])
    with pytest.raises(HTTPException, match="ORIGINAL_OPERATION_OWNER_REQUIRED"):
        await other.prepare_start("original-owner", "inspect")
    with pytest.raises(HTTPException, match="QUERY_ONLY"):
        await authority.get_operation(uuid4())


async def test_https_history_rejects_database_update_delete_and_observation_rebinding(http_context):
    authority = http_context["authority"]
    record = await authority.prepare_start("immutable", "inspect")
    value = response_document(record["request"], state="UNKNOWN")
    await authority.record_response(record["id"], value)
    changed = deepcopy(value)
    changed["request_digest"] = "f" * 64
    with pytest.raises(CloudBlocked):
        await authority.record_response(record["id"], changed)
    for table, column in (("cloud_http_operations", "id"), ("cloud_http_observations", "operation_id")):
        for statement in (f"UPDATE {table} SET request_digest=:digest WHERE {column}=:id",
                          f"DELETE FROM {table} WHERE {column}=:id"):
            async with AsyncSessionLocal() as db:
                with pytest.raises(DBAPIError, match="immutable"):
                    await db.execute(text(statement), {"id": UUID(record["id"]), "digest": "e" * 64})
                await db.rollback()


async def test_https_database_intent_cannot_borrow_foreign_grant_worker_or_generation(http_context):
    authority = http_context["authority"]
    record = await authority.prepare_start("bound-original", "inspect")
    async with AsyncSessionLocal() as db:
        original = await db.get(CloudHttpOperation, UUID(record["id"]))
        frozen = {column.name: getattr(original, column.name) for column in CloudHttpOperation.__table__.columns}
        foreign = await db.scalar(select(CloudWorkGrant.id).where(CloudWorkGrant.id != original.work_grant_id,
            CloudWorkGrant.project_id == original.project_id))
        assert foreign is not None  # The earlier resolution has its own grant.
    for change in ({"work_grant_id": foreign}, {"worker_id": "foreign-worker"},
                   {"generation": frozen["generation"] + 1}, {"project_id": uuid4()}, {"attempt_id": uuid4()}):
        candidate = {**frozen, "id": uuid4(), "operation_key": "foreign-" + uuid4().hex, **change}
        candidate["request"] = {**frozen["request"], "operation_id": str(candidate["id"]),
            "attempt_id": str(candidate["attempt_id"]), "generation": candidate["generation"]}
        candidate["request_digest"] = digest(candidate["request"])
        async with AsyncSessionLocal() as db:
            db.add(CloudHttpOperation(**candidate))
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()


async def test_https_database_observation_keeps_original_identity_and_excludes_body(http_context):
    authority = http_context["authority"]
    record = await authority.prepare_start("bound-observation", "inspect")
    await authority.record_response(record["id"], response_document(record["request"], state="UNKNOWN"))
    async with AsyncSessionLocal() as db:
        original = await db.scalar(select(CloudHttpObservation).where(CloudHttpObservation.operation_id == UUID(record["id"])))
        frozen = {column.name: getattr(original, column.name) for column in CloudHttpObservation.__table__.columns}
    for change in ({"project_id": uuid4()}, {"attempt_id": uuid4()}, {"request_digest": "f" * 64},
                   {"worker_id": "foreign-worker"}, {"generation": frozen["generation"] + 1},
                   {"observation": {**frozen["observation"], "body_base64": ""}}):
        candidate = {**frozen, "id": uuid4(), "observation_digest": uuid4().hex * 2, **change}
        async with AsyncSessionLocal() as db:
            db.add(CloudHttpObservation(**candidate))
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudHttpObservation).where(
            CloudHttpObservation.operation_id == UUID(record["id"]))) == 1


async def test_https_database_rejects_incomplete_untyped_or_extra_response_metadata(http_context):
    authority = http_context["authority"]
    record = await authority.prepare_start("metadata-boundary", "inspect")
    await authority.record_response(record["id"], response_document(record["request"], state="UNKNOWN"))
    async with AsyncSessionLocal() as db:
        original = await db.scalar(select(CloudHttpObservation).where(CloudHttpObservation.operation_id == UUID(record["id"])))
        frozen = {column.name: getattr(original, column.name) for column in CloudHttpObservation.__table__.columns}
    for change in ("extra-field", "raw-base64", "raw-body", "missing-sha", "null-sha", "missing-count",
                   "null-count", "null-observed-at", "unknown-claims-status", "unknown-claims-observed-reason"):
        metadata = deepcopy(frozen["observation"])
        if change == "extra-field":
            metadata["arbitrary"] = "not canonical response metadata"
        elif change == "raw-base64":
            metadata["body_base64"] = ""
        elif change == "raw-body":
            metadata["body"] = BODY.decode()
        elif change == "missing-sha":
            del metadata["body_sha256"]
        elif change == "null-sha":
            metadata["body_sha256"] = None
        elif change == "missing-count":
            del metadata["byte_count"]
        elif change == "null-count":
            metadata["byte_count"] = None
        elif change == "null-observed-at":
            metadata["observed_at"] = None
        elif change == "unknown-claims-status":
            metadata["http_status"] = 200
        else:
            metadata["reason"] = "RESPONSE_OBSERVED"
        candidate = {**frozen, "id": uuid4(), "observation_digest": digest(metadata), "observation": metadata}
        async with AsyncSessionLocal() as db:
            db.add(CloudHttpObservation(**candidate))
            with pytest.raises(DBAPIError, match="HTTPS"):
                await db.flush()
            await db.rollback()
