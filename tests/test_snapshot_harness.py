from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.agent.snapshot import SnapshotHarness, cleanup_managed_agent_workspace
from hypertest.api.delivery_schemas import RunBootstrap
from hypertest.api.schemas import ProjectCreate
from hypertest.application import runtime
from hypertest.application.bootstrap import bootstrap_run
from hypertest.application.planner import plan_next_mission
from hypertest.application.services import create_project
from hypertest.common.ids import public_key
from hypertest.config import get_settings
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.enums import MissionAttemptStatus, MissionStatus
from hypertest.domain.models import AgentSessionRecord, MissionAttempt, Requirement
from hypertest.runner.source import validate_checkout


@pytest.fixture
def source_snapshot(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    tracked = {
        "src/arithmetic.py": "def add(a, b):\n    return a + b\n",
        "README.md": "A minimal integer addition library.\n",
        ".env.example": "EXAMPLE_SETTING=replace-me\n",
        ".env.sample": "EXAMPLE_SETTING=replace-me\n",
        ".env.template": "EXAMPLE_SETTING=replace-me\n",
        ".env": "SYNTHETIC_FIXTURE_ONLY=not-a-real-secret\n",
        ".env.production": "SYNTHETIC_FIXTURE_ONLY=not-a-real-secret\n",
        "nested/.env": "SYNTHETIC_FIXTURE_ONLY=not-a-real-secret\n",
        ".aws/credentials": "synthetic-fixture-only\n",
        ".ssh/id_ed25519": "synthetic-fixture-only\n",
        ".codex/config.toml": "# synthetic fixture only\n",
        ".npmrc": "# synthetic fixture only\n",
        ".netrc": "# synthetic fixture only\n",
    }
    for relative, content in tracked.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    repository = "https://example.invalid/agent-source-snapshot.git"
    for args in (
        ["init", "--initial-branch=main"],
        ["config", "user.name", "Snapshot Harness Integration"],
        ["config", "user.email", "snapshot@example.invalid"],
        ["remote", "add", "origin", repository],
        ["add", "."],
        ["commit", "-m", "Add source and synthetic credential filtering fixtures"],
    ):
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (source / "untracked_credentials.txt").write_text("synthetic-untracked-fixture-only\n")
    return source, commit, repository


class RecordingProvider:
    def __init__(self, mode: str = "normal") -> None:
        self.mode = mode
        self.workspace: Path | None = None
        self.contract: dict[str, Any] | None = None
        self.closed = 0
        self.interrupted = 0

    async def create_session(self, workspace: str) -> AgentSession:
        self.workspace = Path(workspace)
        if self.mode == "create_failure":
            raise RuntimeError("provider session creation failed")
        return AgentSession(id=public_key("AS"), provider="snapshot-test-provider")

    async def execute(
        self, session: AgentSession, mission: dict[str, Any]
    ) -> AsyncIterator[AgentEvent]:
        self.contract = mission
        assert self.workspace is not None
        (self.workspace / "scratch.txt").write_text("ephemeral agent work\n")
        baseline = self.workspace / "src/arithmetic.py"
        if self.mode == "rewrite":
            baseline.write_text("def add(a, b):\n    return 0\n")
        elif self.mode == "delete":
            baseline.unlink()
        elif self.mode == "symlink":
            baseline.unlink()
            baseline.symlink_to(self.workspace / "README.md")
        elif self.mode == "execute_failure":
            raise RuntimeError("provider execution failed")
        yield AgentEvent(type="ACTIVITY", payload={"phase": "proposal"})
        yield AgentEvent(
            type="RESULT_SUBMITTED",
            payload={
                "protocol": "hypertest.tmp/v1alpha1",
                "mission_id": mission["mission_id"],
                "status": "COMPLETED",
                "summary": "One atomic addition requirement proposed",
                "proposals": [
                    {
                        "proposal_type": "REQUIREMENT",
                        "operation": "CREATE",
                        "idempotency_key": "arithmetic.add:v1",
                        "object_payload": {
                            "title": "Add two integer values",
                            "description": "add(a, b) returns the mathematical sum of two integers.",
                            "requirement_type": "FUNCTIONAL",
                            "priority": "P0",
                            "source_type": "PRD",
                            "source_ref": "PRD#add",
                        },
                    }
                ],
            },
        )

    async def interrupt(self, session: AgentSession) -> None:
        self.interrupted += 1

    async def restore_session(self, session: AgentSession, workspace: str) -> AgentSession:
        self.workspace = Path(workspace)
        return session

    async def resume(self, session: AgentSession, mission: dict) -> AsyncIterator[AgentEvent]:
        async for event in self.execute(session, mission):
            yield event

    async def close(self, session: AgentSession) -> None:
        self.closed += 1
        if self.mode == "close_failure":
            raise RuntimeError("provider cleanup failed")


@pytest.mark.asyncio
async def test_disposable_workspace_contains_tracked_source_without_credentials_or_git(
    source_snapshot: tuple[Path, str, str],
) -> None:
    source, commit, repository = source_snapshot
    files = await validate_checkout(source, commit, repository)
    provider = RecordingProvider()
    harness = SnapshotHarness(provider, source, files)
    session = await harness.create_session(str(source))
    workspace = Path(harness.workspace_for(session))
    temporary_root = workspace.parent
    original = (source / "src/arithmetic.py").read_bytes()
    mission = {"mission_id": "MIS-snapshot", "constraints": {"max_duration_seconds": 5}}
    try:
        assert provider.workspace == workspace
        assert workspace != source
        copied = {
            str(path.relative_to(workspace)) for path in workspace.rglob("*") if path.is_file()
        }
        assert copied == {
            "src/arithmetic.py",
            "README.md",
            ".env.example",
            ".env.sample",
            ".env.template",
        }
        assert not (workspace / ".git").exists()
        events = [event async for event in harness.execute(session, mission)]
        assert [event.type for event in events] == ["ACTIVITY", "RESULT_SUBMITTED"]
        assert provider.contract is not None
        assert provider.contract["constraints"]["workspace_mode"] == "DISPOSABLE_TRACKED_SNAPSHOT"
        assert provider.contract["constraints"]["application_source_immutable"] is True
        assert provider.contract["constraints"]["credential_files_omitted"] is True
        assert mission["constraints"] == {"max_duration_seconds": 5}
        assert (workspace / "scratch.txt").exists()
        assert not (source / "scratch.txt").exists()
        assert (source / "src/arithmetic.py").read_bytes() == original
        await harness.interrupt(session)
        assert provider.interrupted == 1
    finally:
        await harness.close(session)
    assert provider.closed == 1
    assert not workspace.exists()
    assert not temporary_root.exists()
    assert (source / ".git").is_dir()
    assert (source / ".env").is_file()
    assert (source / "untracked_credentials.txt").is_file()
    await validate_checkout(source, commit, repository)


@pytest.mark.asyncio
async def test_managed_snapshot_survives_gateway_recreation_and_revalidates_trusted_source(
    source_snapshot, monkeypatch,
):
    import gc

    source, commit, repository = source_snapshot
    monkeypatch.setattr(get_settings(), "workspace_root", str(source.parent))
    files = await validate_checkout(source, commit, repository)
    first = SnapshotHarness(RecordingProvider(), source, files)
    session = await first.create_session(str(source))
    workspace = first.workspace_for(session)
    del first
    gc.collect()
    assert Path(workspace).is_dir()
    restored = SnapshotHarness(RecordingProvider(), source, files)
    await restored.restore_session(session, workspace)
    events = [event async for event in restored.resume(session, {"mission_id": "MIS-resumed"})]
    assert any(event.type == "RESULT_SUBMITTED" for event in events)
    await restored.close(session)
    assert not Path(workspace).exists()

    damaged = SnapshotHarness(RecordingProvider(), source, files)
    session = await damaged.create_session(str(source))
    workspace = damaged.workspace_for(session)
    (Path(workspace) / "src/arithmetic.py").write_text("def add(a,b): return 0\n")
    competitor = SnapshotHarness(RecordingProvider(), source, files)
    with pytest.raises(RuntimeError, match="differs from its pinned source"):
        await competitor.restore_session(session, workspace)
    await damaged.close(session)
    await validate_checkout(source, commit, repository)


def test_managed_cleanup_refuses_operator_directory_and_symlink_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_root", str(tmp_path))
    operator = tmp_path / "operator-repo"
    operator.mkdir()
    (operator / "keep.txt").write_text("operator content")
    assert not cleanup_managed_agent_workspace(str(operator))
    managed = tmp_path / ".hypertest-agent-sessions"
    managed.mkdir()
    (managed / ("1" * 32)).symlink_to(operator, target_is_directory=True)
    assert not cleanup_managed_agent_workspace(str(managed / ("1" * 32) / "repo"))
    assert (operator / "keep.txt").read_text() == "operator content"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["rewrite", "delete", "symlink"])
async def test_modified_copied_source_rejects_proposal_without_changing_original(
    source_snapshot: tuple[Path, str, str],
    mutation: str,
) -> None:
    source, commit, repository = source_snapshot
    files = await validate_checkout(source, commit, repository)
    provider = RecordingProvider(mutation)
    harness = SnapshotHarness(provider, source, files)
    session = await harness.create_session(str(source))
    workspace = Path(harness.workspace_for(session))
    original = (source / "src/arithmetic.py").read_bytes()
    try:
        events = [event async for event in harness.execute(session, {"mission_id": "MIS-mutation"})]
        assert "RESULT_SUBMITTED" not in {event.type for event in events}
        assert events[-1].type == "ERROR"
        assert events[-1].payload["error_code"] == "SOURCE_CHANGED"
        assert (source / "src/arithmetic.py").read_bytes() == original
    finally:
        await harness.close(session)
    assert not workspace.exists()
    await validate_checkout(source, commit, repository)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["create_failure", "close_failure"])
async def test_disposable_workspace_is_removed_when_provider_creation_or_close_fails(
    source_snapshot: tuple[Path, str, str],
    failure: str,
) -> None:
    source, commit, repository = source_snapshot
    files = await validate_checkout(source, commit, repository)
    provider = RecordingProvider(failure)
    harness = SnapshotHarness(provider, source, files)
    if failure == "create_failure":
        with pytest.raises(RuntimeError, match="session creation failed"):
            await harness.create_session(str(source))
    else:
        session = await harness.create_session(str(source))
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await harness.close(session)
    assert provider.workspace is not None
    assert not provider.workspace.exists()
    assert not provider.workspace.parent.exists()
    await validate_checkout(source, commit, repository)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_mode", ["normal", "execute_failure", "rewrite"])
async def test_default_runtime_wraps_provider_and_cleans_disposable_workspace(
    source_snapshot: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_mode: str,
) -> None:
    source, commit, repository = source_snapshot
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    provider = RecordingProvider(provider_mode)
    monkeypatch.setattr(runtime, "_select_harness", lambda _: provider)
    async with AsyncSessionLocal() as session:
        project = await create_project(
            session,
            ProjectCreate(
                key=f"SNAPSHOT_{public_key('IT')[-12:]}",
                name="Snapshot runtime integration",
            ),
        )
        run = await bootstrap_run(
            session,
            project.id,
            RunBootstrap(
                repository_url=repository,
                commit_sha=commit,
                prd_text="The add(a, b) function returns the sum of two Python integers.",
            ),
        )
        plan = await plan_next_mission(session, run.id)
        assert plan.mission is not None
        mission = plan.mission
        if provider_mode == "normal":
            # Omit harness= so this exercises the production workspace boundary.
            result = await runtime.execute_mission(session, mission.id, str(source))
            assert result.attempt.status is MissionAttemptStatus.ACCEPTED
            assert len(result.requirements) == 1
            attempt = result.attempt
        else:
            with pytest.raises(runtime.MissionRuntimeError):
                await runtime.execute_mission(session, mission.id, str(source))
            attempt = await session.scalar(
                select(MissionAttempt).where(
                    MissionAttempt.mission_id == mission.id,
                )
            )
            assert attempt is not None
            assert attempt.status is MissionAttemptStatus.FAILED
            assert attempt.error_code == (
                "HARNESS_ERROR" if provider_mode == "execute_failure" else "SOURCE_CHANGED"
            )
            assert mission.status is MissionStatus.RETRYING
        assert await session.scalar(
            select(func.count())
            .select_from(Requirement)
            .where(
                Requirement.source_snapshot_id == run.source_snapshot_id,
            )
        ) == (1 if provider_mode == "normal" else 0)
        agent = await session.get(AgentSessionRecord, attempt.agent_session_id)
        assert agent is not None
        assert agent.harness == "SnapshotHarness"
        assert agent.workspace_id == str(provider.workspace)
    assert provider.closed == 1
    assert provider.workspace is not None
    assert not provider.workspace.exists()
    assert not provider.workspace.parent.exists()
    await validate_checkout(source, commit, repository)
