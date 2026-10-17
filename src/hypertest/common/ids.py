from __future__ import annotations

import secrets
import time
from uuid import UUID


def uuid7() -> UUID:
    """Generate an RFC 9562 UUIDv7 without depending on Python 3.14+.

    Layout: 48-bit Unix epoch milliseconds, version=7, 12 random bits,
    RFC 4122 variant, and 62 random bits.
    """

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return UUID(int=value)


def public_key(prefix: str) -> str:
    """Create a human-readable key retaining UUIDv7's random uniqueness bits.

    The first 12 hex characters contain only milliseconds, so truncating there
    causes every entity created in the same millisecond to share a public key.
    Existing persisted keys remain valid; new keys retain the full UUID.
    """

    return f"{prefix}-{uuid7().hex.upper()}"
