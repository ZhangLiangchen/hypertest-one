"""Namespace client for fixed SSH actions. No target, key, shell or environment API."""

from __future__ import annotations

import argparse
import asyncio
import json

from .ssh_profile import SSH_SOCKET, canonical_bytes


async def request(payload: dict) -> dict:
    reader, writer = await asyncio.open_unix_connection(SSH_SOCKET, limit=256 * 1024 + 1)
    try:
        async with asyncio.timeout(40):
            writer.write(canonical_bytes(payload) + b"\n")
            await writer.drain()
            raw = await reader.readline()
            if len(raw) > 256 * 1024 or not raw.endswith(b"\n"):
                raise ValueError
            return json.loads(raw)
    finally:
        writer.close()


def main():
    parser = argparse.ArgumentParser(description="Invoke one fixed SSH diagnostic or query its original operation")
    subs = parser.add_subparsers(dest="command", required=True)
    invoke = subs.add_parser("invoke")
    invoke.add_argument("--key", required=True)
    invoke.add_argument("--action", required=True)
    query = subs.add_parser("query")
    query.add_argument("--operation", required=True)
    args = parser.parse_args()
    payload = ({"verb": "INVOKE", "key": args.key, "action_key": args.action}
               if args.command == "invoke" else {"verb": "QUERY", "operation_id": args.operation})
    try:
        response = asyncio.run(request(payload))
    except Exception:
        response = {"status": "UNKNOWN", "code": "SSH_BROKER_UNAVAILABLE"}
    print(json.dumps(response, sort_keys=True))
    return 0 if response.get("status") == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
