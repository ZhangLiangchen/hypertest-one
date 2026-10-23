"""Namespace client for frozen public API resources; no URL/header/credential API."""
from __future__ import annotations

import argparse
import asyncio
import json

from .http_operations import WIRE_LIMIT
from .http_profile import HTTPS_SOCKET, canonical_bytes


async def request(payload):
    reader, writer = await asyncio.open_unix_connection(HTTPS_SOCKET, limit=WIRE_LIMIT + 1)
    try:
        async with asyncio.timeout(25):
            writer.write(canonical_bytes(payload) + b"\n")
            await writer.drain()
            raw = await reader.readline()
            if len(raw) > WIRE_LIMIT or not raw.endswith(b"\n"):
                raise ValueError
            return json.loads(raw)
    finally:
        writer.close()


def main():
    parser = argparse.ArgumentParser(description="Invoke a frozen public HTTPS resource or query its original operation")
    subs = parser.add_subparsers(dest="command", required=True)
    invoke = subs.add_parser("invoke")
    invoke.add_argument("--key", required=True)
    invoke.add_argument("--resource", required=True)
    query = subs.add_parser("query")
    identity = query.add_mutually_exclusive_group(required=True)
    identity.add_argument("--operation")
    identity.add_argument("--key")
    args = parser.parse_args()
    payload = ({"verb": "INVOKE", "key": args.key, "resource_key": args.resource}
               if args.command == "invoke" else
               {"verb": "QUERY", "key": args.key} if args.key else {"verb": "QUERY", "operation_id": args.operation})
    try:
        response = asyncio.run(request(payload))
    except Exception:
        response = {"status": "UNKNOWN", "code": "HTTPS_BROKER_UNAVAILABLE"}
    print(json.dumps(response, sort_keys=True))
    return 0 if response.get("status") == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
