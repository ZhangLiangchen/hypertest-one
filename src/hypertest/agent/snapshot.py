"""Disposable, credential-free source copies for replaceable agent workers."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from hypertest.agent.base import AgentEvent, AgentHarness, AgentSession
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.runner.source import copy_tracked_source

_CREDENTIAL_DIRECTORIES = {
    ".git",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".codex",
    ".claude",
    ".kube",
}
_CREDENTIAL_FILES = {
    ".netrc",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
}
_ENVIRONMENT_EXAMPLES = {".env.example", ".env.sample", ".env.template"}


def _managed_agent_root() -> Path:
    root = Path(get_settings().workspace_root).resolve() / ".hypertest-agent-sessions"
    if root.is_symlink():
        raise RuntimeError("managed agent workspace root cannot be a symlink")
    return root


def _managed_workspace_directory(workspace: str) -> Path | None:
    path = Path(workspace)
    root = path.parent
    try:
        managed = _managed_agent_root()
        if (not path.is_absolute() or path.name != "repo" or root.parent != managed
                or path.is_symlink() or root.is_symlink() or path.resolve() != path
                or len(root.name) != 32 or any(c not in "0123456789abcdef" for c in root.name)):
            return None
    except (OSError, RuntimeError):
        return None
    return root


def cleanup_managed_agent_workspace(workspace: str) -> bool:
    """Remove only our exact managed UUID/repo container; never an operator path.

    The caller must finish its ownership/cancellation transaction before filesystem
    cleanup. Missing or unsafe legacy locations are deliberately left untouched.
    """
    root = _managed_workspace_directory(workspace)
    if root is None or not root.is_dir():
        return False
    shutil.rmtree(root)
    return True


def _is_source_file(relative: str) -> bool:
    path = PurePosixPath(relative)
    return not (
        any(part in _CREDENTIAL_DIRECTORIES for part in path.parts)
        or path.name in _CREDENTIAL_FILES
        or (path.name.startswith(".env") and path.name not in _ENVIRONMENT_EXAMPLES)
    )


@dataclass(slots=True)
class _Workspace:
    root: Path
    path: Path
    file_hashes: dict[str, str]


class SnapshotHarness:
    """Forward the agent contract while keeping its filesystem disposable.

    Only validated tracked source enters the copy. New scratch files are allowed;
    changing copied application files invalidates a submitted canonical proposal.
    """

    def __init__(self, harness: AgentHarness, source: Path, tracked_files: list[str]) -> None:
        self.harness = harness
        self.source = source
        self.tracked_files = [item for item in tracked_files if _is_source_file(item)]
        self._workspaces: dict[str, _Workspace] = {}

    def _managed_root(self) -> Path:
        return _managed_agent_root()

    def _expected_hashes(self) -> dict[str, str]:
        return {
            relative: hashlib.sha256((self.source / relative).read_bytes()).hexdigest()
            for relative in self.tracked_files
        }

    async def create_session(self, workspace: str) -> AgentSession:
        if Path(workspace).resolve() != self.source:
            raise RuntimeError("agent source differs from its validated snapshot")
        managed = self._managed_root()
        managed.mkdir(parents=True, mode=0o700, exist_ok=True)
        root = managed / uuid7().hex
        root.mkdir(mode=0o700)
        target = root / "repo"
        try:
            copy_tracked_source(self.source, target, self.tracked_files)
            hashes = self._expected_hashes()
            session = await self.harness.create_session(str(target))
            self._workspaces[session.id] = _Workspace(root, target, hashes)
            return session
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise

    async def restore_session(self, session: AgentSession, workspace: str) -> AgentSession:
        # The database identifies the managed directory, but source integrity is
        # reconstructed from the validated pinned checkout, never agent files.
        path = Path(workspace)
        root = _managed_workspace_directory(workspace)
        if root is None or not path.is_dir():
            raise RuntimeError("persisted managed agent workspace is missing or unsafe")
        self._workspaces[session.id] = _Workspace(root, path, self._expected_hashes())
        if not self._source_unchanged(session):
            self._workspaces.pop(session.id)
            raise RuntimeError("persisted agent workspace differs from its pinned source")
        try:
            return await self.harness.restore_session(session, str(path))
        except BaseException:
            self._workspaces.pop(session.id, None)
            raise

    def workspace_for(self, session: AgentSession) -> str:
        return str(self._workspaces[session.id].path)

    def _source_unchanged(self, session: AgentSession) -> bool:
        workspace = self._workspaces[session.id]
        try:
            for relative, expected in workspace.file_hashes.items():
                path = workspace.path / relative
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or not path.resolve().is_relative_to(workspace.path)
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected
                ):
                    return False
        except OSError:
            return False
        return True

    async def execute(
        self,
        session: AgentSession,
        mission: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        async for event in self._run(session, mission, resume=False):
            yield event

    async def resume(
        self, session: AgentSession, mission: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        async for event in self._run(session, mission, resume=True):
            yield event

    async def _run(
        self, session: AgentSession, mission: dict[str, Any], *, resume: bool,
    ) -> AsyncIterator[AgentEvent]:
        contract = dict(mission)
        constraints = dict(contract.get("constraints", {}))
        constraints.update(
            workspace_mode="DISPOSABLE_TRACKED_SNAPSHOT",
            source_metadata_in_context=True,
            application_source_immutable=True,
            credential_files_omitted=True,
        )
        contract["constraints"] = constraints
        stream = self.harness.resume(session, contract) if resume else self.harness.execute(session, contract)
        async for event in stream:
            if event.type == "RESULT_SUBMITTED" and not self._source_unchanged(session):
                yield AgentEvent(
                    type="ERROR",
                    payload={
                        "error_code": "SOURCE_CHANGED",
                        "message": "agent modified immutable source inside its disposable workspace",
                    },
                )
                return
            yield event

    async def interrupt(self, session: AgentSession) -> None:
        await self.harness.interrupt(session)

    async def close(self, session: AgentSession) -> None:
        try:
            await self.harness.close(session)
        finally:
            workspace = self._workspaces.pop(session.id, None)
            if workspace is not None:
                cleanup_managed_agent_workspace(str(workspace.path))
