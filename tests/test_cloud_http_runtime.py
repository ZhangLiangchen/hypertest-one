"""HTTP admission/prompt boundaries without any model, network or SUT."""
import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from hypertest.api.cloud_schemas import CloudDispatch, CloudTaskCreate, Environment, TaskInputs
from hypertest.application.cloud_tasks import (
    _check_run_entrypoint,
    _task_inputs_with_runtime_defaults,
)
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_profile import HTTPS_SOCKET, digest, validate_profile
from hypertest.cloud.manifests import task_prompt
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy


def environment():
    access = {"profile": "HTTPS_CONTROLLED_API_V1", "allowed_addresses": ["1.1.1.1"],
        "resources": [{"key": "status", "method": "GET", "path": "/status", "timeout_seconds": 5,
                       "response_limit_bytes": 1024}], "max_operations": 2}
    access["catalog_sha256"] = digest({**access, "target": "https://api.example.test:443"})
    return {"name": "Synthetic public fixture", "connection": "HTTPS", "host": "api.example.test",
        "port": 443, "cloud_access_policy": "WEB_ONLY", "https_access": access}


def manifest():
    return {"configuration": {"environment": environment()}, "inputs": {"framework_runtime": {"profile": "fixture"},
        "authorization": {"targets": ["https://api.example.test:443"],
            "network_targets": ["https://api.example.test:443"],
            "permitted_actions": ["git:read", "framework:execute", "environment:read"]},
        "budgets": {"total_seconds": 60}}}


def test_old_schema_serialization_never_adds_null_runtime_or_https_fields():
    from test_cloud_tasks import inputs
    old = inputs()
    assert "https_access" not in Environment(name="old").model_dump(mode="json")
    assert TaskInputs.model_validate(old).model_dump(mode="json")["framework_entrypoints"] == old["framework_entrypoints"]
    assert "framework_runtime" not in TaskInputs.model_validate(old).model_dump(mode="json")


def test_task_draft_inherits_local_only_runtime_envelope():
    from test_cloud_tasks import configuration, inputs
    draft = inputs()
    for key in ("framework_entrypoints", "authorization", "budgets"):
        draft.pop(key)
    result = _task_inputs_with_runtime_defaults(TaskInputs.model_validate(draft), configuration(), datetime.now(UTC))
    assert result["framework_entrypoints"] == []
    assert result["authorization"]["targets"] == [configuration()["sut"]["url"], configuration()["framework"]["url"]]
    assert result["authorization"]["permitted_actions"] == ["git:read", "framework:execute"]
    assert result["authorization"]["network_targets"] == []
    assert result["budgets"] is None


def test_existing_explicit_task_envelope_is_preserved():
    from test_cloud_tasks import configuration, inputs
    draft = inputs()
    result = _task_inputs_with_runtime_defaults(TaskInputs.model_validate(draft), configuration(), datetime.now(UTC))
    assert result["authorization"]["permitted_actions"] == draft["authorization"]["permitted_actions"]
    assert result["authorization"]["targets"] == draft["authorization"]["targets"]
    assert result["budgets"]["total_seconds"] == draft["budgets"]["total_seconds"]


def test_update_without_envelope_regenerates_source_authorization_and_removes_old_draft_budget():
    from test_cloud_tasks import configuration, inputs
    original = TaskInputs.model_validate(inputs()).model_dump(mode="json")
    edited = dict(original)
    edited.pop("authorization")
    edited.pop("budgets")
    result = _task_inputs_with_runtime_defaults(TaskInputs.model_validate(edited), configuration(), datetime.now(UTC), original=original)
    assert result["authorization"]["targets"] == original["authorization"]["targets"]
    assert result["authorization"]["expires_at"] is None
    assert result["budgets"] is None


def test_update_cannot_add_or_change_a_task_budget():
    from test_cloud_tasks import configuration, inputs
    original = TaskInputs.model_validate(inputs()).model_dump(mode="json")
    changed = deepcopy(original)
    changed["budgets"]["max_attempts"] += 1
    with pytest.raises(HTTPException, match="budget cannot be configured or changed"):
        _task_inputs_with_runtime_defaults(TaskInputs.model_validate(changed), configuration(), datetime.now(UTC), original=original)
    original["budgets"] = None
    with pytest.raises(HTTPException, match="budget cannot be configured or changed"):
        _task_inputs_with_runtime_defaults(TaskInputs.model_validate(changed), configuration(), datetime.now(UTC), original=original)


async def test_create_rejects_new_platform_budget_but_original_receipt_still_recovers(monkeypatch):
    from test_cloud_tasks import inputs

    from hypertest.application import cloud_tasks
    payload = CloudTaskCreate(project_id=uuid4(), operation_key="fixture-create", expected_version=0,
        title="fixture", expected_project_version=1, inputs={**inputs(), "authorization": None,
            "mr_url": "https://git.example.invalid/sut/-/merge_requests/1"})
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    monkeypatch.setattr(cloud_tasks, "project", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "_lock", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "_reject_secrets", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "enabled", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await cloud_tasks.mutate(db, payload, "original-actor")
    assert exc.value.status_code == 422 and exc.value.detail == "Cloud Task budget is not accepted"
    original = {"status": "ACCEPTED", "task_id": str(uuid4())}
    db.scalar.return_value = SimpleNamespace(actor_ref="original-actor", operation="CREATE_TASK",
        input_digest=cloud_tasks.canonical_json_sha256(cloud_tasks._safe_payload(payload)), response=original)
    assert await cloud_tasks.mutate(db, payload, "original-actor") == original


async def test_frozen_legacy_task_rejects_new_attempt_before_reusing_old_input(monkeypatch):
    from hypertest.application import cloud_tasks
    task_id, project_id = uuid4(), uuid4()
    payload = CloudDispatch(project_id=project_id, operation_key="fixture-retry", expected_version=1,
        task_id=task_id, retry_of_attempt_id=uuid4(), retry_scope_confirmed=True, retry_authorization_confirmed=True, reason="explicit synthetic retry")
    task = SimpleNamespace(id=task_id, project_id=project_id, version=1, status="COMPLETED", inputs={"budgets": {}})
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), get=AsyncMock(return_value=None))
    monkeypatch.setattr(cloud_tasks, "project", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "_lock", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "_task", AsyncMock(return_value=task))
    monkeypatch.setattr(cloud_tasks, "_reject_secrets", AsyncMock())
    monkeypatch.setattr(cloud_tasks, "enabled", lambda: None)
    with pytest.raises(HTTPException) as exc:
        await cloud_tasks.mutate(db, payload, "original-actor")
    assert exc.value.status_code == 409
    assert "requires new scope and authorization" in exc.value.detail


@pytest.mark.parametrize("kind", ["ssh", "http", "action"])
async def test_lease_only_remote_start_rejected_before_writing_intent(monkeypatch, kind):
    from hypertest.application import cloud_actions, cloud_http, cloud_ssh, cloud_tasks
    task = SimpleNamespace(inputs={"budgets": None})
    attempt = SimpleNamespace(status="RUNNING", id=uuid4(), execution_manifest=None)
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=AsyncMock(), commit=AsyncMock())

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    if kind == "action":
        monkeypatch.setattr(cloud_actions, "controlled_actions_enabled", lambda: True)
        monkeypatch.setattr(cloud_tasks, "enabled", lambda: None)
        monkeypatch.setattr(cloud_tasks, "worker_authority", AsyncMock())
        authority = cloud_actions.WorkerActionAuthority(Session, task_id=str(uuid4()), attempt_id=str(uuid4()), identity=None)
        call = authority._authorized(db, task, attempt, "fixture")
        expected = "CLOUD_ACTION_LEASE_ONLY_UNSUPPORTED"
    else:
        cls = cloud_ssh.WorkerSshAuthority if kind == "ssh" else cloud_http.WorkerHttpAuthority
        authority = cls(Session, task_id=str(uuid4()), attempt_id=str(uuid4()), identity=None)
        monkeypatch.setattr(authority, "_task_attempt", AsyncMock(return_value=(task, attempt)))
        call = authority.prepare_start("original-key", "fixture")
        expected = "SSH_LEASE_ONLY_UNSUPPORTED" if kind == "ssh" else "HTTPS_LEASE_ONLY_UNSUPPORTED"
    with pytest.raises(HTTPException) as exc:
        await call
    assert exc.value.status_code == 409 and exc.value.detail == expected
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_run_entrypoint_allows_unrestricted_reporting_but_keeps_explicit_list():
    _check_run_entrypoint({"framework_entrypoints": []}, "python -m pytest")
    _check_run_entrypoint({"framework_entrypoints": ["python -m pytest"]}, "python -m pytest")
    with pytest.raises(HTTPException) as exc:
        _check_run_entrypoint({"framework_entrypoints": ["python -m pytest"]}, "other command")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("field", ["target", "network", "action", "framework"])
def test_https_policy_requires_exact_frozen_permission_and_framework(field):
    frozen = manifest()
    if field == "target":
        frozen["inputs"]["authorization"]["targets"] = ["api.example.test"]
    elif field == "network":
        frozen["inputs"]["authorization"]["network_targets"].append("https://other.example.test:443")
    elif field == "action":
        frozen["inputs"]["authorization"]["permitted_actions"].remove("environment:read")
    else:
        frozen["inputs"].pop("framework_runtime")
    with pytest.raises(CloudBlocked) as error:
        SandboxPolicy(60, 1, 1024, http_profile=validate_profile(environment())).validate(frozen)
    assert error.value.code == "HTTPS_AUTHORIZATION_MISMATCH"


def test_https_environment_schema_rejects_catalog_changes_credentials_and_local_only():
    for change in ({"credential_version_id": "00000000-0000-4000-8000-000000000001"},
                   {"cloud_access_policy": "LOCAL_ONLY"}, {"port": None}):
        with pytest.raises(ValidationError):
            Environment.model_validate({**environment(), **change})
    changed = deepcopy(environment())
    changed["https_access"]["resources"][0]["method"] = "POST"
    with pytest.raises(ValidationError):
        Environment.model_validate(changed)
    assert Environment.model_validate(environment()).https_access["profile"] == "HTTPS_CONTROLLED_API_V1"


async def test_http_mount_is_only_readonly_unix_socket_and_requires_matching_policy(tmp_path):
    socket = tmp_path / "https.sock"
    server = await asyncio.start_unix_server(lambda *_: None, path=socket)
    try:
        sandbox = BubblewrapSandbox(workspace=tmp_path, dsh_home=tmp_path, broker_socket=tmp_path / "model.sock",
            policy=SandboxPolicy(60, 1, 1024, http_profile=validate_profile(environment())), http_socket=socket)
        assert sandbox.http_mounts() == ["--ro-bind", str(socket), HTTPS_SOCKET]
        sandbox.policy = SandboxPolicy(60, 1, 1024)
        with pytest.raises(CloudBlocked) as error:
            sandbox.http_mounts()
        assert error.value.code == "HTTPS_SOCKET_UNAVAILABLE"
    finally:
        server.close()
        await server.wait_closed()


def test_prompt_declares_exact_resources_and_original_key_recovery_without_general_network():
    task = {"id": str(uuid4()), "frozen_manifest": manifest()}
    prompt = json.loads(task_prompt(task, {"id": str(uuid4())}, http_profile=validate_profile(environment())))
    assert prompt["capabilities"]["remote_network"] is False
    assert prompt["capabilities"]["https_controlled_api"]["resources"] == environment()["https_access"]["resources"]
    assert "query --key ORIGINAL_KEY" in " ".join(prompt["instructions"])
    assert "UNKNOWN" in " ".join(prompt["instructions"])
