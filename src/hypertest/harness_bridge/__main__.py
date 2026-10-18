"""Host service entry point; reads only explicit Bridge environment variables."""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from hypertest.harness_bridge.provider import PersistentCodex
from hypertest.harness_bridge.server import BridgeServer


def build_server() -> BridgeServer:
    def required(name: str) -> str:
        value = os.environ.get("HYPERTEST_BRIDGE_" + name, "")
        if not value:
            raise ValueError("missing HYPERTEST_BRIDGE_" + name)
        return value

    socket_path = Path(required("SOCKET"))
    return BridgeServer(
        socket_path=socket_path,
        tool_socket_path=Path(os.environ.get("HYPERTEST_BRIDGE_TOOL_SOCKET", str(socket_path.with_name("relay.sock")))),
        state_dir=Path(required("STATE_DIR")), workspace_root=Path(required("WORKSPACE_ROOT")),
        host_id=required("HOST_ID"), execution_key=Path(required("EXECUTION_KEY_FILE")).read_bytes().strip(),
        management_key=Path(required("MANAGEMENT_KEY_FILE")).read_bytes().strip(),
        provider=PersistentCodex(os.environ.get("HYPERTEST_BRIDGE_CODEX_BINARY", "codex")),
        max_concurrent=int(os.environ.get("HYPERTEST_BRIDGE_MAX_CONCURRENT", "2")),
    )


async def main() -> None:
    server = build_server()
    stopping = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)
    await server.start()
    try:
        await stopping.wait()
    finally:
        await server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
