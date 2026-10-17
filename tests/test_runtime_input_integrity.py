"""Materialized immutable inputs cannot silently disappear from Agent context."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from test_delivery_loop import PRD_TEXT, configure_workspace
from test_test_design import ProposalHarness, create_run, requirement_proposal

from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import MissionCreate, ProjectCreate
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.planner import _mark_ready, plan_next_mission
from hypertest.application.runtime import (
    MissionRuntimeError,
    _hydrate_source_context,
    build_mission_contract,
    execute_mission,
)
from hypertest.application.services import create_mission, create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionStatus, MissionType
from hypertest.domain.models import MissionAttempt, SourceSnapshot


class InputHarness(ProposalHarness):
    def __init__(self):
        super().__init__([requirement_proposal()])
        self.sessions_created = 0

    async def create_session(self, workspace):
        self.sessions_created += 1
        return await super().create_session(workspace)


async def materialized_run(session, repository_url, commit, configuration):
    project = await create_project(session, ProjectCreate(
        key=f"INPUT_{public_key('IT')[-12:]}", name="Immutable input integrity",
    ))
    return await bootstrap_run(session, project.id, RunBootstrap(
        repository_url=repository_url, commit_sha=commit, prd_text=PRD_TEXT,
        configuration_text=configuration,
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "modified"])
async def test_materialized_configuration_failure_blocks_before_agent_session(
    tmp_path, monkeypatch, damage,
):
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    async with AsyncSessionLocal() as session:
        run = await materialized_run(session, repository_url, commit, '{"region":"中文测试"}')
        snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
        assert snapshot.prd_artifact_uri is not None
        configuration = Path(get_settings().artifact_root) / "inputs" / (
            f"{snapshot.configuration_sha256}.txt"
        )
        assert configuration.is_file()
        if damage == "missing":
            configuration.unlink()
        else:
            configuration.write_text('{"region":"changed"}')
        plan = await plan_next_mission(session, run.id)
        harness = InputHarness()
        with pytest.raises(MissionRuntimeError, match="configuration artifact"):
            await execute_mission(session, plan.mission.id, str(source), harness=harness)
        assert harness.sessions_created == 0
        assert plan.mission.status is MissionStatus.READY
        assert await session.scalar(select(func.count()).select_from(MissionAttempt).where(
            MissionAttempt.mission_id == plan.mission.id,
        )) == 0


@pytest.mark.asyncio
async def test_materialized_configuration_enters_context_with_exact_original_text(
    tmp_path, monkeypatch,
):
    source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    configuration = ' {"region": "中文测试", "feature": true}\n'
    async with AsyncSessionLocal() as session:
        run = await materialized_run(session, repository_url, commit, configuration)
        plan = await plan_next_mission(session, run.id)
        harness = InputHarness()
        result = await execute_mission(session, plan.mission.id, str(source), harness=harness)
        assert result.mission.status is MissionStatus.COMPLETED
        assert harness.contract["context"]["configuration_text"] == configuration
        assert harness.contract["context"]["prd_text"] == PRD_TEXT


@pytest.mark.asyncio
async def test_execution_scope_uses_snapshot_identity_without_rewriting_frozen_inputs(
    tmp_path, monkeypatch,
):
    _source, commit, repository_url = configure_workspace(tmp_path, monkeypatch)
    configuration = ' {"region": "中文测试"}\r\n'
    async with AsyncSessionLocal() as session:
        run = await materialized_run(session, repository_url, commit, configuration)
        for mission_type in (
            MissionType.ANALYZE_REQUIREMENTS, MissionType.ANALYZE_RISKS,
            MissionType.DESIGN_TESTS, MissionType.IMPLEMENT_TESTS,
        ):
            mission = await create_mission(session, run.id, MissionCreate(
                mission_type=mission_type, objective="Inspect the pinned application",
                spec={
                    "context": {
                        "repository_url": "https://example.invalid/untrusted-context",
                        "commit_sha": "0" * 40,
                        "testing_scope": {"repository_url": "https://example.invalid/other"},
                    },
                    "constraints": {"application_source_immutable": True},
                },
                idempotency_key=f"scope:{mission_type.value}",
            ))
            mission = await _mark_ready(session, mission)
            original_spec, original_hash = deepcopy(mission.spec), mission.spec_sha256
            contract = build_mission_contract(mission, run)
            await _hydrate_source_context(session, run, contract)
            context = contract["context"]
            for identity in (context, context["testing_scope"]):
                assert identity["repository_url"] == repository_url
                assert identity["commit_sha"] == commit
            assert context["prd_text"].encode("utf-8") == PRD_TEXT.encode("utf-8")
            assert context["configuration_text"].encode("utf-8") == configuration.encode("utf-8")
            assert contract["constraints"] == original_spec["constraints"]
            assert mission.status is MissionStatus.READY
            assert mission.spec == original_spec
            assert mission.spec_sha256 == original_hash
            await session.commit()
            await session.refresh(mission)
            assert mission.spec == original_spec
            assert mission.spec_sha256 == original_hash


@pytest.mark.asyncio
async def test_legacy_hash_only_snapshot_retains_optional_unmaterialized_context():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
        assert snapshot.prd_artifact_uri is None
        assert not (Path(get_settings().artifact_root) / "inputs" / (
            f"{snapshot.configuration_sha256}.txt"
        )).exists()
        plan = await plan_next_mission(session, run.id)
        harness = InputHarness()
        result = await execute_mission(session, plan.mission.id, ".", harness=harness)
        assert result.mission.status is MissionStatus.COMPLETED
        assert "prd_text" not in harness.contract["context"]
        assert "configuration_text" not in harness.contract["context"]
