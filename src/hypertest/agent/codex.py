from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.common.ids import public_key


class CodexCliAdapter:
    """Thin Codex CLI adapter with an explicit TMP result boundary.

    Provider JSONL remains operational telemetry. The only final result exposed
    to the HyperTest runtime is the validated JSON object written to the
    mission-scoped result file.
    """

    def __init__(self, binary: str = "codex", extra_args: tuple[str, ...] = ()) -> None:
        self.binary = binary
        self.extra_args = extra_args
        self._workspaces: dict[str, str] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def create_session(self, workspace: str) -> AgentSession:
        session = AgentSession(id=public_key("AS"), provider="codex")
        self._workspaces[session.id] = workspace
        return session

    async def execute(
        self,
        session: AgentSession,
        mission: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]:
        workspace = self._workspaces.get(session.id)
        if workspace is None:
            raise RuntimeError(f"unknown agent session: {session.id}")

        workspace_path = Path(workspace)
        if not workspace_path.is_dir():
            raise RuntimeError(f"workspace does not exist: {workspace}")

        result_dir = workspace_path / ".hypertest" / "results"
        if not result_dir.resolve().is_relative_to(workspace_path.resolve()):
            raise RuntimeError("mission result directory must remain inside its workspace")
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{session.id}.json"
        result_path.unlink(missing_ok=True)

        mission_json = json.dumps(mission, ensure_ascii=False, sort_keys=True)
        prompt = (
            "Execute the following HyperTest Test Mission as an immutable task contract. "
            "Use available repository and tools, do not redefine the mission. "
            "Your final action MUST write exactly one valid JSON object matching the mission "
            f"output contract to {result_path}. Do not use stdout as the final result channel.\n\n"
            f"TEST_MISSION_JSON:\n{mission_json}"
        )

        process = await asyncio.create_subprocess_exec(
            self.binary,
            "exec",
            "--json",
            "--skip-git-repo-check",
            *self.extra_args,
            prompt,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        self._processes[session.id] = process
        stderr_task = None
        if process.stderr is not None:
            stderr_task = asyncio.create_task(process.stderr.read())

        yield AgentEvent(type="MISSION_STARTED", payload={"provider": "codex"})

        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                provider_event = json.loads(line)
            except json.JSONDecodeError:
                provider_event = {"raw": line}

            yield AgentEvent(
                type="ACTIVITY",
                payload={
                    "provider": "codex",
                    "provider_event": provider_event,
                },
            )

        return_code = await process.wait()
        self._processes.pop(session.id, None)
        stderr = ""
        if stderr_task is not None:
            stderr = (await stderr_task).decode("utf-8", errors="replace")

        if return_code != 0:
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "return_code": return_code,
                    "stderr": stderr,
                },
            )
            return

        if not result_path.is_file():
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "error_code": "RESULT_MISSING",
                    "message": f"mission result file not found: {result_path}",
                },
            )
            return

        try:
            if result_path.stat().st_size > 2_000_000:
                raise ValueError("mission result exceeds the 2 MB structured output limit")
            result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "error_code": "RESULT_INVALID",
                    "message": str(exc),
                },
            )
            return

        yield AgentEvent(type="RESULT_SUBMITTED", payload=result_payload)
        yield AgentEvent(type="MISSION_FINISHED", payload={"provider": "codex"})

    async def interrupt(self, session: AgentSession) -> None:
        process = self._processes.get(session.id)
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            except ProcessLookupError:
                await process.wait()

    async def close(self, session: AgentSession) -> None:
        await self.interrupt(session)
        self._processes.pop(session.id, None)
        self._workspaces.pop(session.id, None)
