"""Container-side client. A disconnected start is never automatically replayed."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Any

from hypertest.harness_bridge.protocol import (
    MAX_MESSAGE,
    PROFILE,
    PROTOCOL,
    TRANSPORT,
    BridgeError,
    ExecutionContext,
    canonical,
    sign,
)


class BridgeClient:
    def __init__(self, socket_path: str, execution_key: bytes, management_key: bytes,
                 *, timeout: float = 10) -> None:
        if len(execution_key) < 32 or len(management_key) < 32 or execution_key == management_key:
            raise ValueError("Bridge requires separate execution/management keys of at least 32 bytes")
        self.socket_path = socket_path
        self.execution_key = execution_key
        self.management_key = management_key
        self.timeout = timeout

    @classmethod
    def from_files(cls, socket_path: str, execution_key_file: str, management_key_file: str) -> BridgeClient:
        return cls(socket_path, Path(execution_key_file).read_bytes().strip(),
                   Path(management_key_file).read_bytes().strip())

    async def request(self, operation: str, payload: dict[str, Any] | None = None,
                      *, management: bool = False) -> dict[str, Any]:
        request = {
            "transport": TRANSPORT, "protocol": PROTOCOL, "profile": PROFILE,
            "operation": operation, "authority": "management" if management else "execution",
            "issued_at": time.time(), "nonce": secrets.token_hex(16), "payload": payload or {},
        }
        request["signature"] = sign(request, self.management_key if management else self.execution_key)
        data = canonical(request) + b"\n"
        if len(data) > MAX_MESSAGE:
            raise BridgeError("REQUEST_TOO_LARGE")
        writer = None
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_unix_connection(self.socket_path, limit=MAX_MESSAGE)
                writer.write(data)
                await writer.drain()
                response = json.loads(await reader.readline())
        except (TimeoutError, OSError, ValueError) as exc:
            # A start may already have happened: the caller must query its fixed call_id.
            raise BridgeError("OUTCOME_UNKNOWN", "Bridge response unavailable; reconcile call before retry") from exc
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
        if not response.get("ok"):
            raise BridgeError(response.get("error", "BRIDGE_ERROR"))
        return response["result"]

    async def capabilities(self) -> dict[str, Any]:
        return await self.request("capabilities", management=True)

    async def create_session(self, context: ExecutionContext) -> dict[str, Any]:
        return await self.request("create_session", {"context": context.to_dict()})

    async def start_call(self, context: ExecutionContext, contract: dict[str, Any], *,
                         call_id: str, resume: bool = False) -> dict[str, Any]:
        return await self.request("resume" if resume else "execute", {
            "context": context.to_dict(), "contract": contract, "call_id": call_id,
            "idempotency_key": call_id,
        })

    async def get_call(self, context: ExecutionContext, call_id: str, *, cursor: int = 0,
                       management: bool = False) -> dict[str, Any]:
        return await self.request("get_call", {"context": context.to_dict(), "call_id": call_id,
                                              "cursor": cursor}, management=management)

    async def renew(self, context: ExecutionContext, call_id: str) -> dict[str, Any]:
        return await self.request("renew", {"context": context.to_dict(), "call_id": call_id})

    async def respond_tool(self, context: ExecutionContext, call_id: str, tool_call_id: str,
                           result: dict[str, Any]) -> dict[str, Any]:
        return await self.request("respond_tool", {"context": context.to_dict(), "call_id": call_id,
                                                   "tool_call_id": tool_call_id, "result": result})

    async def restore_session(self, context: ExecutionContext) -> dict[str, Any]:
        return await self.request("restore_session", {"context": context.to_dict()}, management=True)

    async def interrupt(self, context: ExecutionContext, call_id: str) -> dict[str, Any]:
        return await self.request("interrupt", {"context": context.to_dict(), "call_id": call_id}, management=True)

    async def recover(self, context: ExecutionContext, call_id: str, *, new_epoch: int) -> dict[str, Any]:
        return await self.request("recover", {"context": context.to_dict(), "call_id": call_id,
                                             "new_epoch": new_epoch}, management=True)

    async def close(self, context: ExecutionContext, call_id: str | None, *, terminal: bool) -> dict[str, Any]:
        return await self.request("close", {"context": context.to_dict(), "call_id": call_id,
                                           "terminal": terminal}, management=True)
