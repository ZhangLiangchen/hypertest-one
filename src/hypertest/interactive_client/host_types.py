"""Trusted host adapter boundary. Model arguments never supply host evidence."""
from pathlib import Path
from typing import Protocol

from hypertest.interactive_client.errors import ClientError


class HostAdapterError(ClientError):
    pass


class HostAdapter(Protocol):
    def capabilities(self) -> dict: ...

    async def attest(self, *, project_id: str, run_id: str, node_id: str,
                     source_transfer_id: str, workspace: Path) -> dict: ...

    async def assert_live(self, attestation: dict) -> None: ...

    async def assert_peer(self, pid: int) -> None: ...
