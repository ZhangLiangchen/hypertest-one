"""Transparent official-SDK MCP console; it never generates test proposals.

Run in the actual supported Agent host launch context. JSON lines on stdin are
either {"tool": name, "arguments": {...}} or {"request_file": owned_file}.
The latter avoids terminal line-size limits for structured Proposal batches.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hypertest.interactive_client.security import private_create, private_directory, private_read


async def run(config: Path, output: Path):
    output = private_directory(output)
    server = StdioServerParameters(command=sys.executable,
        args=["-m", "hypertest.interactive_client", "stdio", "--config", str(config), "--autostart"],
        env=dict(os.environ))
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(json.dumps({"connected": True, "tools": [tool.name for tool in tools.tools]}), flush=True)
            number = 0
            while line := await asyncio.to_thread(sys.stdin.readline):
                request = json.loads(line)
                if "request_file" in request:
                    request = json.loads(private_read(Path(request["request_file"])))
                if request.get("action") == "quit":
                    return
                result = await session.call_tool(request["tool"], request.get("arguments", {}))
                number += 1
                value = result.model_dump(mode="json", exclude_none=True)
                private_create(output / f"response-{number:04}.json", json.dumps(value, ensure_ascii=False).encode())
                print(json.dumps({"response_number": number, "isError": result.isError,
                    "result": result.structuredContent if result.structuredContent is not None
                    else value.get("content", [])}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    asyncio.run(run(options.config.expanduser().resolve(strict=True), options.output))


if __name__ == "__main__":
    main()
