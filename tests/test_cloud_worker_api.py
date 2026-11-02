"""Host Worker admission and target binding; no business DB or model calls."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from hypertest.api import cloud_worker_routes
from hypertest.api.cloud_schemas import CloudNativeFinish
from hypertest.config import get_settings
from hypertest.db.session import get_db
from hypertest.main import app


@pytest.fixture
async def worker_client(monkeypatch, tmp_path):
    token = "worker-fixture-" + "x" * 40
    key = tmp_path / "worker-token"
    key.write_text(token)
    key.chmod(0o600)
    settings = get_settings()
    monkeypatch.setattr(settings, "cloud_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_enabled", True)
    monkeypatch.setattr(settings, "cloud_worker_api_token_file", str(key))
    monkeypatch.setattr(settings, "cloud_worker_api_worker_id", "host-fixture")

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        yield client, {"Authorization": "Bearer " + token}
    app.dependency_overrides.pop(get_db, None)


async def test_claim_requires_dedicated_worker_identity(worker_client, monkeypatch):
    client, headers = worker_client
    calls = []

    async def expire(_db):
        calls.append("expire")

    async def resolution(_db, worker_id, lease_seconds):
        calls.append((worker_id, lease_seconds))
        return None

    async def attempt(_db, worker_id, lease_seconds, *, supports_attempt_manifest=False):
        return None

    monkeypatch.setattr(cloud_worker_routes.service, "expire_leases", expire)
    monkeypatch.setattr(cloud_worker_routes.service, "claim_resolution", resolution)
    monkeypatch.setattr(cloud_worker_routes.service, "claim_attempt", attempt)
    payload = {"worker_id": "host-fixture", "lease_seconds": 90}
    assert (await client.post("/api/v1/cloud/worker/claim", json=payload)).status_code == 401
    assert (await client.post("/api/v1/cloud/worker/claim", headers=headers,
                              json={**payload, "worker_id": "another"})).status_code == 403
    assert not calls
    response = await client.post("/api/v1/cloud/worker/claim", headers=headers, json=payload)
    assert response.status_code == 200 and response.json() == {"kind": "EMPTY", "claim": None}
    assert calls == ["expire", ("host-fixture", 90)]


async def test_auth_observation_requires_worker_and_accepts_only_status(worker_client, monkeypatch):
    from hypertest.application import cloud_agent_auth
    client, headers = worker_client
    seen = []
    async def store(db, worker_id, status):
        seen.append((worker_id, status))
    class DB:
        async def commit(self): pass
    async def db_override():
        yield DB()
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(cloud_agent_auth, "store_worker_auth_status", store)
    try:
        assert (await client.post("/api/v1/cloud/worker/auth-observation", json={"status": "VALID"})).status_code == 401
        assert (await client.post("/api/v1/cloud/worker/auth-observation", headers=headers,
                                  json={"status": "VALID", "secret": "fixture"})).status_code == 422
        response = await client.post("/api/v1/cloud/worker/auth-observation", headers=headers, json={"status": "VALID"})
        assert response.status_code == 200
        assert seen == [("host-fixture", "VALID")]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("message", [
    "Potential secret material is not an accepted testing artifact",
    "Credential material is not an accepted testing artifact",
])
async def test_validate_payload_only_projects_fixed_sensitive_content_rejection(worker_client, monkeypatch, message):
    from fastapi import HTTPException

    client, headers = worker_client
    project, task, attempt = (str(uuid4()) for _ in range(3))
    identity = {"worker_id": "host-fixture", "lease_token": "l" * 32, "work_token": "w" * 32, "generation": 1}
    body = {"project_id": project, "task_id": task, "attempt_id": attempt, "identity": identity,
            "payload": {"operation": "SUBMIT_ASSETS"}}

    async def active(*_args):
        pass

    async def known_rejection(*_args):
        raise HTTPException(422, message)

    monkeypatch.setattr(cloud_worker_routes, "active", active)
    monkeypatch.setattr(cloud_worker_routes.service, "_reject_secrets", known_rejection)
    response = await client.post("/api/v1/cloud/worker/validate-payload", headers=headers, json=body)
    assert response.status_code == 422 and response.json() == {"detail": "REPORT_CONTENT_REJECTED"}

    async def unknown_rejection(*_args):
        raise HTTPException(403, "other authorization error")

    monkeypatch.setattr(cloud_worker_routes.service, "_reject_secrets", unknown_rejection)
    response = await client.post("/api/v1/cloud/worker/validate-payload", headers=headers, json=body)
    assert response.status_code == 403 and response.json() != {"detail": "REPORT_CONTENT_REJECTED"}

    async def unknown_422(*_args):
        raise HTTPException(422, "unclassified failure")

    monkeypatch.setattr(cloud_worker_routes.service, "_reject_secrets", unknown_422)
    response = await client.post("/api/v1/cloud/worker/validate-payload", headers=headers, json=body)
    assert response.status_code == 422 and response.json() != {"detail": "REPORT_CONTENT_REJECTED"}


async def test_worker_cannot_submit_management_or_other_attempt(worker_client, monkeypatch):
    client, headers = worker_client
    project, task, attempt = (str(uuid4()) for _ in range(3))
    identity = {"worker_id": "host-fixture", "lease_token": "l" * 32, "work_token": "w" * 32, "generation": 1}
    body = {"project_id": project, "task_id": task, "attempt_id": attempt, "identity": identity}
    called = []

    async def active(*_args):
        called.append(True)

    monkeypatch.setattr(cloud_worker_routes, "active", active)
    payload = {"profile": "cloud-harness-task/v1alpha1", "operation": "TRANSITION", "project_id": project,
               "task_id": task, "attempt_id": str(uuid4()), "operation_key": "test:1", "expected_version": 1,
               "status": "RUNNING", "reason": "fixture"}
    response = await client.post("/api/v1/cloud/worker/submit", headers=headers, json={**body, "payload": payload})
    assert response.status_code == 403
    assert not called


def test_native_completion_never_claims_unobserved_external_or_process_scope():
    payload = {"project_id": str(uuid4()), "task_id": str(uuid4()), "attempt_id": str(uuid4()),
               "operation_key": "native:1", "expected_version": 1, "final_report_revision": str(uuid4()),
               "reported_result": "NOT_RUN", "usage_seconds": 0, "cost_microunits": 0,
               "runtime_observation": "DIRECT_SDK_PROCESS_EXITED", "completion_manifest": {
                   "required_asset_ids": [str(uuid4())], "scope_and_gaps": "Fixture only",
                   "all_local_processes_stopped": False, "external_operations_reconciled": False,
                   "pending_operation_keys": []}}
    assert CloudNativeFinish.model_validate(payload).runtime_observation == "DIRECT_SDK_PROCESS_EXITED"
    payload["completion_manifest"]["external_operations_reconciled"] = True
    with pytest.raises(ValidationError):
        CloudNativeFinish.model_validate(payload)
