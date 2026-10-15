from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from hypertest.agent.base import AgentEvent, AgentSession
from hypertest.common.ids import public_key


class CodexCliAdapter:
    """Thin Codex CLI adapter.

    This adapter deliberately does not expose Codex-specific events to the
    HyperTest domain. It is the first implementation of AgentHarness and can
    later be replaced by a Codex SDK/App Server adapter without changing TMP.
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

        mission_json = json.dumps(mission, ensure_ascii=False, sort_keys=True)
        prompt = (
            "Execute the following HyperTest Test Mission as an immutable task contract. "
            "Use available repository and tools, do not redefine the mission, and return the "
            "final result according to the mission output_contract.\n\n"
            f"TEST_MISSION_JSON:\n{mission_json}"
        )

        process = await asyncio.create_subprocess_exec(
            self.binary,
            "exec",
            "--json",
            *self.extra_args,
            prompt,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[session.id] = process

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

        if return_code != 0:
            stderr = ""
            if process.stderr is not None:
                stderr = (await process.stderr.read()).decode("utf-8", errors="replace")
            yield AgentEvent(
                type="ERROR",
                payload={
                    "provider": "codex",
                    "return_code": return_code,
                    "stderr": stderr,
                },
            )
            return

        yield AgentEvent(type="MISSION_FINISHED", payload={"provider": "codex"})

    async def interrupt(self, session: AgentSession) -> None:
        process = self._processes.get(session.id)
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()

    async def close(self, session: AgentSession) -> None:
        await self.interrupt(session)
        self._processes.pop(session.id, None)
        self._workspaces.pop(session.id, None)
