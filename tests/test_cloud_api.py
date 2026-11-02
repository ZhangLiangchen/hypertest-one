"""Strict Cloud boundary contracts; these fixtures never invoke an SDK/runtime."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from hypertest.api.cloud_schemas import Authorization, CloudDispatch, Repository, Selector
from hypertest.api.interactive_schemas import RegisterIntegration
from hypertest.config import get_settings
from hypertest.main import app


@pytest.mark.parametrize("url", ["https://user:secret@git.invalid/repo", "https://git.invalid/repo?token=secret",
                                      "file:///etc/passwd", "file:/etc/passwd", "http://git.invalid/repo", "ssh://root:secret@git.invalid/repo",
                                      "https://git.invalid", "ssh://@git.invalid/repo", "https://git.invalid:99999/repo"])
def test_repository_contract_refuses_secret_or_local_url(url):
    with pytest.raises(ValidationError):
        Repository(url=url, default_selector={"value": "main"})


def test_repository_contract_accepts_scp_style_ssh():
    assert Repository(url="git@gitlab.example:team/project.git").url == "git@gitlab.example:team/project.git"
    assert Repository(url="ssh://alice@gitlab.example/team/project.git").url == "ssh://alice@gitlab.example/team/project.git"


def test_mr_has_explicit_base_and_exact_checkout_strategy():
    with pytest.raises(ValidationError):
        Selector(kind="MR", value="10")
    selector = Selector(kind="MR", value="10", base_ref="refs/heads/main", checkout_strategy="MERGE")
    assert selector.base_ref == "refs/heads/main" and selector.checkout_strategy == "MERGE"
    with pytest.raises(ValidationError):
        Selector(kind="MR", value="10", base_ref="../hidden")


def test_cloud_work_cannot_be_issued_as_an_interactive_user_scope():
    from uuid import uuid4
    with pytest.raises(ValidationError):
        RegisterIntegration(actor_ref="fixture", client_instance_id=uuid4(), project_id=uuid4(), scopes=["cloud:work"])
    configured = RegisterIntegration(actor_ref="fixture", client_instance_id=uuid4(), project_id=uuid4(), scopes=[
        "cloud:configure", "credential:manage", "cloud:dispatch", "cloud:control", "cloud:read", "task:sync", "run:read"])
    assert "task:sync" in configured.scopes


def test_dispatch_never_chooses_between_an_implicit_retry_and_a_resolution():
    from uuid import uuid4
    values = {"project_id": uuid4(), "task_id": uuid4(), "operation_key": "fixture", "expected_version": 1}
    with pytest.raises(ValidationError):
        CloudDispatch(**values)
    with pytest.raises(ValidationError):
        CloudDispatch(**values, resolution_id=uuid4(), retry_of_attempt_id=uuid4())
    with pytest.raises(ValidationError):
        CloudDispatch(**values, retry_of_attempt_id=uuid4())
    with pytest.raises(ValidationError):
        CloudDispatch(**values, retry_of_attempt_id=uuid4(), reason="reviewed",
                      retry_scope_confirmed="true", retry_authorization_confirmed=True)
    CloudDispatch(**values, retry_of_attempt_id=uuid4(), reason="reviewed",
                  retry_scope_confirmed=True, retry_authorization_confirmed=True)
    CloudDispatch(**values, resolution_id=uuid4())


def test_dispatch_digest_preserves_original_resolution_request_shape():
    from uuid import uuid4

    from hypertest.application.cloud_tasks import _safe_payload

    payload = CloudDispatch(project_id=uuid4(), task_id=uuid4(), operation_key="fixture",
                            expected_version=1, resolution_id=uuid4())
    safe = _safe_payload(payload)
    assert "retry_scope_confirmed" not in safe
    assert "retry_authorization_confirmed" not in safe
    old_retry = CloudDispatch(project_id=uuid4(), task_id=uuid4(), operation_key="old",
                              expected_version=1, retry_of_attempt_id=uuid4(), reason="original")
    assert "retry_scope_confirmed" not in _safe_payload(old_retry)
    assert "retry_authorization_confirmed" not in _safe_payload(old_retry)


def test_authorization_does_not_accept_ambiguous_naive_expiration():
    base = {"targets": ["https://git.invalid/repo"], "permitted_actions": ["git:read"],
            "side_effect_limits": "Fixture only"}
    assert Authorization(**base).expires_at is None
    assert Authorization(**base).model_dump(mode="json")["expires_at"] is None
    with pytest.raises(ValidationError):
        Authorization(**base, expires_at=datetime.now())
    assert Authorization(**base, expires_at=datetime.now(UTC) + timedelta(hours=1)).expires_at.tzinfo


def test_authorization_expiry_preserves_explicit_deadlines_and_rejects_invalid_values():
    from hypertest.application.cloud_tasks import authorization_expiry

    assert authorization_expiry({}) is None
    assert authorization_expiry({"expires_at": None}) is None
    explicit = datetime.now(UTC) + timedelta(minutes=1)
    assert authorization_expiry({"expires_at": explicit.isoformat()}) == explicit
    with pytest.raises(HTTPException):
        authorization_expiry({"expires_at": "not-a-time"})
    with pytest.raises(HTTPException):
        authorization_expiry({"expires_at": "2026-01-01T00:00:00"})


async def test_capabilities_are_default_off_and_explicit_about_unsupported_execution(monkeypatch):
    monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    monkeypatch.setattr(get_settings(), "cloud_worker_enabled", False)
    monkeypatch.setattr(get_settings(), "cloud_codex_enabled", False)
    monkeypatch.setattr(get_settings(), "cloud_ssh_enabled", False)
    monkeypatch.setattr(get_settings(), "cloud_https_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        response = await client.get("/api/v1/cloud/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False and data["worker_enabled"] is False
    assert data["supported"]["execution"] == "WORKSPACE_LOCAL"
    assert not data["supported"]["ssh"] and not data["supported"]["remote_ci"]
    assert data["supported"]["codex_delegation"] and not data["supported"]["claude_code_delegation"]
    assert data["supported"]["ssh_fixed_diagnostics"]
    assert data["supported"]["ssh_profile"] == "SSH_FIXED_DIAGNOSTICS_V1"
    assert data["configuration"] == {"cloud_enabled": False, "worker_enabled": False,
                                     "codex_enabled": False, "ssh_fixed_diagnostics_enabled": False,
                                     "https_controlled_api_enabled": False}
    assert data["support_semantics"] == "IMPLEMENTATION_NOT_ADMISSION"
    assert data["admission"] == {"state": "NOT_CHECKED", "scope": "PER_ATTEMPT", "checked_by": "WORKER"}
    assert "model_execution" in data["not_proven"]


@pytest.mark.parametrize("enabled", [False, True])
async def test_capability_flags_never_claim_runtime_or_credential_admission(monkeypatch, enabled):
    from types import SimpleNamespace

    from hypertest.api import cloud_routes

    # Only these five configuration booleans are available: no identity, file,
    # runtime/payload path, model credential or Worker probe can be consulted.
    monkeypatch.setattr(cloud_routes, "get_settings", lambda: SimpleNamespace(
        cloud_enabled=enabled, cloud_worker_enabled=enabled,
        cloud_codex_enabled=enabled, cloud_ssh_enabled=enabled, cloud_https_enabled=enabled))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        response = await client.get("/api/v1/cloud/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert all(value is enabled for value in data["configuration"].values())
    assert data["supported"]["codex_delegation"] is True
    assert data["supported"]["claude_code_delegation"] is False
    assert data["supported"]["environment_connections"] == ["NONE"]
    assert data["admission"]["state"] == "NOT_CHECKED"
    assert "provider_authentication" in data["not_proven"]
