"""Deployment opt-ins remain separate from operation authority."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from hypertest.application import cloud_actions, cloud_tasks
from hypertest.config import Settings


def test_opt_ins_are_default_closed_and_independent(monkeypatch):
    monkeypatch.delenv("HYPERTEST_CLOUD_CONTAINER_INTENTS_ENABLED", raising=False)
    monkeypatch.delenv("HYPERTEST_CLOUD_CONTROLLED_ACTIONS_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    monkeypatch.setattr(cloud_tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(cloud_actions, "get_settings", lambda: settings)
    assert not cloud_tasks.container_intents_enabled()
    assert not cloud_actions.controlled_actions_enabled()
    settings.cloud_container_intents_enabled = True
    assert cloud_tasks.container_intents_enabled() and not cloud_actions.controlled_actions_enabled()
    settings.cloud_controlled_actions_enabled = True
    assert cloud_actions.controlled_actions_enabled()


@pytest.mark.asyncio
async def test_container_opt_in_does_not_bypass_engine_or_recovery_authority(monkeypatch):
    settings = Settings(_env_file=None, cloud_container_intents_enabled=True)
    monkeypatch.setattr(cloud_tasks, "get_settings", lambda: settings)
    with pytest.raises(HTTPException, match="CLOUD_CONTAINER_RECOVERY_CAPABILITY_REQUIRED"):
        await cloud_tasks.mutate(None, SimpleNamespace(operation="PREPARE_CONTAINER_CREATE"), "worker:fixture")
    with pytest.raises(HTTPException, match="CLOUD_CONTAINER_ENGINE_OBSERVATION_REQUIRED"):
        await cloud_tasks.mutate(None, SimpleNamespace(operation="CONFIRM_CONTAINER_ID"), "worker:fixture")
