"""Strict Cloud boundary contracts; these fixtures never invoke an SDK/runtime."""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from hypertest.api.cloud_schemas import Authorization, CloudDispatch, Repository, Selector
from hypertest.api.interactive_schemas import RegisterIntegration
from hypertest.config import get_settings
from hypertest.main import app


@pytest.mark.parametrize("url", ["https://user:secret@git.invalid/repo", "https://git.invalid/repo?token=secret",
                                      "file:///etc/passwd", "http://git.invalid/repo", "ssh://root@git.invalid/repo"])
def test_repository_contract_refuses_secret_or_local_url(url):
    with pytest.raises(ValidationError):
        Repository(url=url, default_selector={"value": "main"})


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


def test_authorization_does_not_accept_ambiguous_naive_expiration():
    base = {"targets": ["https://git.invalid/repo"], "permitted_actions": ["git:read"],
            "side_effect_limits": "Fixture only"}
    with pytest.raises(ValidationError):
        Authorization(**base, expires_at=datetime.now())
    assert Authorization(**base, expires_at=datetime.now(UTC) + timedelta(hours=1)).expires_at.tzinfo


async def test_capabilities_are_default_off_and_explicit_about_unsupported_execution(monkeypatch):
    monkeypatch.setattr(get_settings(), "cloud_enabled", False)
    monkeypatch.setattr(get_settings(), "cloud_worker_enabled", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost") as client:
        response = await client.get("/api/v1/cloud/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False and data["worker_enabled"] is False
    assert data["supported"]["execution"] == "WORKSPACE_LOCAL"
    assert not data["supported"]["ssh"] and not data["supported"]["remote_ci"]
    assert not data["supported"]["codex_delegation"] and not data["supported"]["claude_code_delegation"]
    assert "model_execution" in data["not_proven"]
