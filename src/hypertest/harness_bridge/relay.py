"""Private stdio MCP relay. Standalone stdlib module launched with Python -I.

Only a call-scoped token reaches this process. It cannot launch calls, manage
sessions, access Canonical DB, or select its own Run or execution claim.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import uuid

MAX_MESSAGE = 4_000_000


def exchange(operation: str, payload: dict) -> dict:
    request = {
        "call_id": os.environ["HYPERTEST_RELAY_CALL_ID"],
        "token": os.environ["HYPERTEST_RELAY_TOKEN"],
        "operation": operation, "payload": payload,
    }
    with socket.socket(socket.AF_UNIX) as stream:
        stream.connect(os.environ["HYPERTEST_RELAY_SOCKET"])
        stream.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        with stream.makefile("rb") as reader:
            raw = reader.readline(MAX_MESSAGE + 1)
        if len(raw) > MAX_MESSAGE:
            raise RuntimeError("response too large")
        result = json.loads(raw)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "relay rejected"))
        return result["result"]


def main() -> None:
    for line in sys.stdin.buffer:
        request = {}
        try:
            if len(line) > MAX_MESSAGE:
                raise ValueError
            request = json.loads(line)
            if "id" not in request:
                continue
            method = request.get("method")
            params = request.get("params", {})
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "hypertest-run-relay", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = exchange("list", {})
            elif method == "tools/call":
                result = exchange("call", {"name": params.get("name"),
                                          "arguments": params.get("arguments", {}),
                                          "tool_call_id": uuid.uuid4().hex})
                result = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                          "isError": bool(result.get("isError", False))}
            else:
                raise ValueError
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (ValueError, KeyError, OSError, RuntimeError):
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32603, "message": "HyperTest tool request unavailable"}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
