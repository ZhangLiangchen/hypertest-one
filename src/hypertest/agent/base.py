from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class AgentSession:
    id: str
    provider: str
    provider_session_id: str | None = None


@dataclass(slots=True)
class AgentEvent:
    type: str
    payload: dict[str, Any]


class AgentHarness(Protocol):
    async def create_session(self, workspace: str) -> AgentSession: ...

    async def execute(
        self,
        session: AgentSession,
        mission: dict[str, Any],
    ) -> AsyncIterator[AgentEvent]: ...

    async def interrupt(self, session: AgentSession) -> None: ...

    async def close(self, session: AgentSession) -> None: ...
