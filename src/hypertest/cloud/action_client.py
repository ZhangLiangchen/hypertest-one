"""Invoke one explicitly frozen action or query its original receipt."""
from __future__ import annotations

import argparse
import asyncio
import json

from .http_profile import canonical_bytes

SOCKET = "/run/hypertest-actions.sock"
WIRE_LIMIT = 8192


async def request(verb: str, action_key: str):
    reader, writer = await asyncio.open_unix_connection(SOCKET, limit=WIRE_LIMIT + 1)
    try:
        writer.write(canonical_bytes({"verb": verb, "action_key": action_key}) + b"\n")
        await asyncio.wait_for(writer.drain(), 3)
        raw = await asyncio.wait_for(reader.readline(), 125)
        if not raw.endswith(b"\n") or len(raw) > WIRE_LIMIT:
            raise ValueError
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        return value
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=("invoke", "query", "observe"))
    parser.add_argument("action_key")
    args = parser.parse_args()
    try:
        result = asyncio.run(request(args.verb.upper(), args.action_key))
    except (OSError, ValueError, TimeoutError):
        result = {"status": "UNKNOWN", "code": "CONTROLLED_ACTION_BROKER_UNAVAILABLE"}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("status") in {"ORIGINAL", "HTTP_OBSERVED", "BUSINESS_PENDING", "BUSINESS_TERMINAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
