"""Disposable, credential-free source copies for replaceable agent workers."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from hypertest.agent.base import AgentEvent, AgentHarness, AgentSession
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


def _is_source_file(relative: str) -> bool:
    path = PurePosixPath(relative)
    return not (
        any(part in _CREDENTIAL_DIRECTORIES for part in path.parts)
        or path.name in _CREDENTIAL_FILES
        or (path.name.startswith(".env") and path.name not in _ENVIRONMENT_EXAMPLES)
    )


@dataclass(slots=True)
class _Workspace:
    temporary: tempfile.TemporaryDirectory
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

    async def create_session(self, workspace: str) -> AgentSession:
        if Path(workspace).resolve() != self.source:
            raise RuntimeError("agent source differs from its validated snapshot")
        temporary = tempfile.TemporaryDirectory(prefix="hypertest-agent-")
        # macOS exposes its temporary root through /var -> /private/var.
        # Use one canonical root for both containment checks and provider paths.
        target = (Path(temporary.name) / "repo").resolve()
        try:
            copy_tracked_source(self.source, target, self.tracked_files)
            hashes = {
                relative: hashlib.sha256((target / relative).read_bytes()).hexdigest()
                for relative in self.tracked_files
            }
            session = await self.harness.create_session(str(target))
            self._workspaces[session.id] = _Workspace(temporary, target, hashes)
            return session
        except BaseException:
            temporary.cleanup()
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
        contract = dict(mission)
        constraints = dict(contract.get("constraints", {}))
        constraints.update(
            workspace_mode="DISPOSABLE_TRACKED_SNAPSHOT",
            source_metadata_in_context=True,
            application_source_immutable=True,
            credential_files_omitted=True,
        )
        contract["constraints"] = constraints
        async for event in self.harness.execute(session, contract):
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
                workspace.temporary.cleanup()
