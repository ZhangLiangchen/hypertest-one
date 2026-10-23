"""SSH control-plane tests use PostgreSQL metadata only; no network or process."""
import base64
import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_cloud_tasks import (
    claimed,
    configuration,
    inputs,
    post,
    read_all,
    worker_submit,
)
from test_cloud_tasks import (
    cloud_context as cloud_context,
)

from hypertest.api.cloud_schemas import Environment
from hypertest.application import cloud_tasks as service
from hypertest.application.cloud_ssh import (
    WorkerSshAuthority,
    authorize_environment,
    ensure_remote_closed,
)
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.ssh_profile import SSH_ACCESS_PROFILE, SSH_OBSERVATION, digest, unit_name
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import (
    CloudRemoteObservation,
    CloudRemoteOperation,
    CloudRemoteOperationResult,
)

TARGET = "ssh://diag@192.0.2.30:2222"
SECRET = "synthetic-ssh-private-key-canary-not-a-real-key"
PUBLIC = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"p" * 32).decode()


def ssh_environment(credential_id=None):
    access = {"profile": SSH_ACCESS_PROFILE, "helper_sha256": "a" * 64, "authority_public_key": PUBLIC,
        "actions": [{"key": "inspect", "script_path": "/opt/hypertest-ssh/actions/inspect.sh",
            "script_sha256": "b" * 64, "timeout_seconds": 10, "stdout_limit_bytes": 4096, "stderr_limit_bytes": 4096}],
        "max_operations": 8}
    access["catalog_sha256"] = digest({**access, "target": TARGET})
    return {"name": "Synthetic SSH diagnostics", "connection": "SSH", "host": "192.0.2.30", "port": 2222,
        "user": "diag", "host_key": PUBLIC, "credential_version_id": credential_id, "ssh_access": access}


@pytest.fixture
async def ssh_context(cloud_context, monkeypatch):
    context = cloud_context
    monkeypatch.setattr(get_settings(), "cloud_ssh_enabled", True)
    stored = await post(context, "STORE_CREDENTIAL", kind="SSH_KEY", label="SSH fixture", purpose="Fixed diagnostics",
        allowed_targets=[TARGET], allowed_actions=["environment:read"], secret=SECRET)
    assert stored.status_code == 200, stored.text
    credential = stored.json()
    task_inputs = inputs()
    task_inputs["authorization"]["targets"].append(TARGET)
    task_inputs["authorization"]["network_targets"] = [TARGET]
    task_inputs["authorization"]["permitted_actions"].append("environment:read")
    current, claim, identity = await claimed(context, config=configuration(
        environment=ssh_environment(credential["credential_version_id"])), task_inputs=task_inputs)
    running = await worker_submit(context, identity, current, "TRANSITION", status="RUNNING",
        runtime_metadata={"ssh": {"profile": SSH_ACCESS_PROFILE, "hard_deadline_epoch": int(time.time()) + 120}},
        budget_reservation={"reserved_seconds": 300, "request_limits": [{"scope": "ROOT", "max_requests": 2, "cost_per_request_microunits": 1}]})
    authority = WorkerSshAuthority(AsyncSessionLocal, task_id=current["task_id"], attempt_id=current["attempt_id"], identity=identity)
    return {**context, "current": running, "claim": claim, "identity": identity, "authority": authority, "credential": credential}


def observation(record, state="RUNNING", *, stopped=False):
    unknown = state == "NOT_FOUND"
    return {"profile": SSH_OBSERVATION, "operation_id": record["id"], "request_digest": record["request_digest"],
        "target": record["target"], "state": state,
        "remote_identity": {"boot_id": None if unknown else "00000000-0000-4000-8000-000000000001",
            "unit": unit_name(record["id"]), "invocation_id": None if unknown else "c" * 32},
        "remote_started_at": None if unknown else 1, "remote_finished_at": 2 if stopped else None,
        "exit_code": 0 if stopped else None, "signal": None, "remote_stopped": stopped,
        "stdout": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest(), "truncated": False},
        "stderr": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest(), "truncated": False},
        "reason": "NOT_FOUND" if unknown else "EXIT_OBSERVED" if stopped else "ACTIVE"}


def test_legacy_environment_dumps_never_add_an_implicit_executable_access_or_change_old_digest():
    legacy = Environment(name="Legacy SSH metadata", connection="SSH", host="host.example.invalid", user="diag", host_key=PUBLIC)
    assert "ssh_access" not in legacy.model_dump(mode="json")
    assert "cloud_access_policy" not in legacy.model_dump(mode="json")
    assert legacy.ssh_access is None


@pytest.mark.parametrize("change", [{"user": "root"}, {"host": "host.example.invalid"}, {"port": None}, {"credential_version_id": None}])
def test_executable_profile_requires_exact_nonroot_ip_port_and_key_version(change):
    environment = {**ssh_environment("00000000-0000-4000-8000-000000000002"), **change}
    with pytest.raises(ValidationError):
        Environment.model_validate(environment)


@pytest.mark.parametrize("missing", ["target", "network", "action", "expiry"])
def test_execution_authorization_requires_all_exact_ssh_boundaries(missing):
    task_inputs = inputs()
    authorization = task_inputs["authorization"]
    authorization["targets"].append(TARGET)
    authorization["network_targets"] = [TARGET]
    authorization["permitted_actions"].append("environment:read")
    if missing == "target":
        authorization["targets"].remove(TARGET)
    elif missing == "network":
        authorization["network_targets"] = ["192.0.2.30"]  # A host is not its canonical SSH URI.
    elif missing == "action":
        authorization["permitted_actions"].remove("environment:read")
    else:
        authorization["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(HTTPException):
        authorize_environment(SimpleNamespace(inputs=task_inputs), ssh_environment(), datetime.now(UTC))


@pytest.mark.parametrize(("policy", "connection", "code"), [
    ("LOCAL_ONLY", "NONE", "LOCAL_MODE_REQUIRED"),
    ("LOCAL_ONLY", "HTTPS", "LOCAL_MODE_REQUIRED"),
    ("WEB_ONLY", "NONE", "CLOUD_WEB_ONLY"),
    ("WEB_ONLY", "SSH", "CLOUD_WEB_ONLY"),
])
async def test_restrictive_environment_can_be_saved_but_never_creates_a_cloud_task(cloud_context, policy, connection, code):
    environment = {"name": "Route-only metadata", "connection": connection, "cloud_access_policy": policy}
    if connection == "SSH":
        environment.update(host="host.example.invalid", user="diag", host_key=PUBLIC)
    configured = await post(cloud_context, "CONFIGURE", configuration=configuration(environment=environment))
    assert configured.status_code == 200, configured.text
    created = await post(cloud_context, "CREATE_TASK", title="Must remain Local or Web-only",
        config_id=configured.json()["config_id"], inputs=inputs())
    assert created.status_code == 403 and created.json()["detail"] == code
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(service.CloudTask).where(
            service.CloudTask.project_id == UUID(cloud_context["project_id"]))) == 0


def test_route_restrictions_precede_input_resolution_authority_and_do_not_enable_https_runtime():
    for environment, code in (({"cloud_access_policy": "LOCAL_ONLY", "connection": "NONE"}, "LOCAL_MODE_REQUIRED"),
            ({"cloud_access_policy": "WEB_ONLY", "connection": "SSH"}, "CLOUD_WEB_ONLY")):
        with pytest.raises(HTTPException, match=code):
            service._authorize_input_reads(inputs(), configuration(environment=environment), datetime.now(UTC))
    # Passing this subtractive gate grants no network or execution capability.
    assert service.authorize_cloud_environment(configuration(environment={
        "cloud_access_policy": "WEB_ONLY", "connection": "HTTPS"})) is None


async def test_sent_is_committed_before_start_and_same_key_cannot_start_or_change_action_again(ssh_context):
    authority = ssh_context["authority"]
    first = await authority.prepare_start("one", "inspect")
    assert first["allow_send"] is True and first["state"] == "SENT"
    assert first["request_digest"] == digest(first["request"])
    assert first["hard_deadline"] <= int(time.time()) + 10
    async with AsyncSessionLocal() as db:
        row = await db.get(CloudRemoteOperation, UUID(first["id"]))
        assert row is not None and row.state == "SENT" and row.request == first["request"]
    repeated = await authority.prepare_start("one", "inspect")
    assert repeated["id"] == first["id"] and repeated["allow_send"] is False
    with pytest.raises(HTTPException, match="KEY_CONFLICT"):
        await authority.prepare_start("one", "different")
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await authority.prepare_start("two", "inspect")
    assert SECRET not in json.dumps(first)
    with pytest.raises((HTTPException, CloudBlocked)):
        await authority.validate_output(SECRET.encode(), b"")
    material = await service_material(ssh_context)
    assert material["ENVIRONMENT"] == SECRET.encode()  # Real Cipher.decrypt returns bytes.


async def service_material(context):
    async with AsyncSessionLocal() as db:
        return await service.materialize_credentials(db, UUID(context["current"]["task_id"]),
            UUID(context["current"]["attempt_id"]), context["identity"])


async def test_not_found_stays_unknown_query_only_and_blocks_budget_reconcile_and_completion(ssh_context):
    context = ssh_context
    authority = context["authority"]
    record = await authority.prepare_start("uncertain", "inspect")
    updated = await authority.record_observation(record["id"], observation(record, "NOT_FOUND"))
    assert updated["state"] == "UNKNOWN" and updated["allow_send"] is False
    assert await authority.remote_closed() is False
    assert (await authority.prepare_start("uncertain", "inspect"))["allow_send"] is False
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        async with AsyncSessionLocal() as db:
            await ensure_remote_closed(db, task_id=UUID(context["current"]["task_id"]))
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        async with AsyncSessionLocal() as db:
            task = await service._task(db, UUID(context["current"]["task_id"]))
            attempt = await db.get(service.CloudAttempt, UUID(context["current"]["attempt_id"]))
            await service._finish(db, task, attempt, None)
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await worker_submit(context, context["identity"], context["current"], "TRANSITION", status="FAILED")
    with pytest.raises(HTTPException, match="UNRECONCILED"):
        await worker_submit(context, context["identity"], context["current"], "TRANSITION", status="RECOVERY_REQUIRED",
            usage_seconds=1, cost_microunits=0, budget_settlement={"accounting_unit": "CONSERVATIVE_MICROUNITS",
                "observed_seconds": 1, "namespace_stopped": True, "brokers_drained": True,
                "requests": [{"scope": "ROOT", "requests": 0}]})
    async with AsyncSessionLocal() as db:
        attempt = await db.get(service.CloudAttempt, UUID(context["current"]["attempt_id"]))
        assert attempt.runtime_metadata["budget_reservation"]["state"] == "HELD"


async def test_fenced_original_owner_can_only_control_original_operation_and_revoked_key_blocks_new_transport(ssh_context):
    context = ssh_context
    authority = context["authority"]
    record = await authority.prepare_start("cancel-me", "inspect")
    cancelled = await post(context, "CANCEL_ATTEMPT", context["current"]["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], reason="Synthetic cancel")
    assert cancelled.status_code == 200
    control = await authority.admit_control(record["id"], "STOP")
    assert control["authority_mode"] == "CLEANUP" and control["ticket_generation"] > record["generation"]
    assert control["lease_expires_at"] is None
    with pytest.raises(HTTPException):
        await authority.assert_current()
    with pytest.raises(HTTPException, match="CANNOT_START"):
        await authority.admit_control(record["id"], "START")
    with pytest.raises(HTTPException):
        await authority.prepare_start("new-after-fence", "inspect")
    revoked = await post(context, "REVOKE_CREDENTIAL", 1, credential_id=context["credential"]["credential_id"], reason="Revoke fixture")
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(HTTPException, match="revoked"):
        await authority.admit_control(record["id"], "QUERY")
    assert await authority.remote_closed() is False
    refused = await post(context, "RECONCILE_ATTEMPT", cancelled.json()["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], status="FAILED",
        reason="Cannot erase unknown remote operation", reconciliation={"old_owner_fenced": True,
            "local_processes_stopped": True, "external_operations_reconciled": True, "observations": "Insufficient self report"})
    assert refused.status_code == 409


async def test_terminal_observation_and_result_are_immutable_and_only_later_snapshots_include_the_result(ssh_context):
    context = ssh_context
    authority = context["authority"]
    frozen = await read_all(context, context["current"]["task_id"], context["current"]["version"])
    record = await authority.prepare_start("observed", "inspect")
    await authority.record_observation(record["id"], observation(record))
    terminal = observation(record, "COMPLETED", stopped=True)
    await authority.record_observation(record["id"], terminal)
    await authority.record_observation(record["id"], terminal)  # Deduplicated metadata only.
    assert await authority.remote_closed() is True
    assert await read_all(context, context["current"]["task_id"], context["current"]["version"]) == frozen
    reported = await worker_submit(context, context["identity"], context["current"], "SUBMIT_ASSETS", assets=[{
        "kind": "REPORT", "key": "ssh-closed", "title": "Remote diagnostic stopped", "markdown": "No SUT test conclusion inferred"}])
    latest = await read_all(context, reported["task_id"], reported["version"])
    assert len(latest["remote_operation_results"]) == 1
    assert latest["remote_operation_results"][0]["operation_id"] == record["id"]
    assert latest["task"]["reported_result"] == "NOT_RUN"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudRemoteObservation).where(
            CloudRemoteObservation.operation_id == UUID(record["id"]))) == 2
        result = await db.scalar(select(CloudRemoteOperationResult).where(CloudRemoteOperationResult.operation_id == UUID(record["id"])))
        assert result.observation == terminal
        result_id = result.id
    for table, row_id in (("cloud_remote_operations", record["id"]), ("cloud_remote_operation_results", str(result_id))):
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": UUID(row_id)})
            await db.rollback()
    changed = deepcopy(terminal)
    changed["reason"] = "STOP_OBSERVED"
    with pytest.raises(HTTPException, match="IMMUTABLE"):
        await authority.record_observation(record["id"], changed)


async def test_wrong_target_authorization_cannot_acquire_a_remote_intent(ssh_context):
    context = ssh_context
    fake = service.WorkerIdentity(context["identity"].worker_id, context["identity"].lease_token,
        context["identity"].generation, "wrong-original-capability")
    other = WorkerSshAuthority(AsyncSessionLocal, task_id=context["current"]["task_id"],
        attempt_id=context["current"]["attempt_id"], identity=fake)
    with pytest.raises(HTTPException):
        await other.prepare_start("not-authorized", "inspect")


async def test_changed_remote_boot_or_invocation_never_creates_an_immutable_closed_result(ssh_context):
    authority = ssh_context["authority"]
    record = await authority.prepare_start("identity-conflict", "inspect")
    await authority.record_observation(record["id"], observation(record))
    terminal = observation(record, "COMPLETED", stopped=True)
    terminal["remote_identity"]["invocation_id"] = "d" * 32
    result = await authority.record_observation(record["id"], terminal)
    assert result["state"] == "UNKNOWN" and await authority.remote_closed() is False
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(CloudRemoteOperationResult.id).where(
            CloudRemoteOperationResult.operation_id == UUID(record["id"]))) is None


async def test_observation_cannot_bind_a_different_request_and_history_cannot_be_updated(ssh_context):
    authority = ssh_context["authority"]
    record = await authority.prepare_start("bound-observation", "inspect")
    wrong = observation(record)
    wrong["request_digest"] = "f" * 64
    with pytest.raises(CloudBlocked):
        await authority.record_observation(record["id"], wrong)
    await authority.record_observation(record["id"], observation(record))
    statements = [
        "UPDATE cloud_remote_operations SET request_digest=:digest WHERE id=:id",
        "UPDATE cloud_remote_observations SET observation_digest=:digest WHERE operation_id=:id",
    ]
    for statement in statements:
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement), {"id": UUID(record["id"]), "digest": "e" * 64})
            await db.rollback()


async def test_project_revocation_blocks_new_cleanup_transport_and_output_but_not_safe_terminal_observation(ssh_context):
    context, authority = ssh_context, ssh_context["authority"]
    record = await authority.prepare_start("before-project-revoke", "inspect")
    revoked = await context["client"].post(
        "/api/v1/interactive/grants/" + context["grant"]["grant_id"] + "/revoke",
        headers=context["operator_headers"])
    assert revoked.status_code == 200, revoked.text
    with pytest.raises(HTTPException, match="revoked"):
        await authority.admit_control(record["id"], "STOP")
    with pytest.raises(HTTPException, match="revoked"):
        await authority.validate_output(b"benign but no longer authorized", b"")
    await authority.record_observation(record["id"], observation(record, "CANCELLED", stopped=True))
    assert await authority.remote_closed() is True


async def test_fenced_owner_can_record_stop_proof_but_cannot_release_remote_output_to_agent(ssh_context):
    context, authority = ssh_context, ssh_context["authority"]
    record = await authority.prepare_start("before-output-fence", "inspect")
    cancelled = await post(context, "CANCEL_ATTEMPT", context["current"]["version"],
        task_id=context["current"]["task_id"], attempt_id=context["current"]["attempt_id"], reason="Synthetic output fence")
    assert cancelled.status_code == 200, cancelled.text
    with pytest.raises(HTTPException, match="stale"):
        await authority.validate_output(b"benign but old lease", b"")
    await authority.record_observation(record["id"], observation(record, "CANCELLED", stopped=True))
    assert await authority.remote_closed() is True
