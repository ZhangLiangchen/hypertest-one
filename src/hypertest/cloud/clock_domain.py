"""Bind watchdog monotonic timestamps to the shared Linux clock namespace."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


def clock_domain_digest() -> str:
    """Return a bounded identity for this Linux boot and time offsets.

    This is a runtime identity, not a secret or a claim about wall-clock sync.
    A caller must compare both processes' values before accepting heartbeats.
    """
    if sys.platform != "linux":
        raise ValueError("Linux shared clock domain required")
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        raw = Path("/proc/self/timens_offsets").read_text(encoding="ascii")
        if len(raw) > 1024 or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot) is None:
            raise ValueError
        offsets = {}
        for line in raw.splitlines():
            parts = line.split()
            if len(parts) != 3 or parts[0] not in {"monotonic", "boottime"} or parts[0] in offsets:
                raise ValueError
            if re.fullmatch(r"-?[0-9]{1,18}", parts[1]) is None or re.fullmatch(r"[0-9]{1,9}", parts[2]) is None:
                raise ValueError
            seconds, nanos = int(parts[1]), int(parts[2])
            if nanos >= 1_000_000_000:
                raise ValueError
            offsets[parts[0]] = [seconds, nanos]
        if set(offsets) != {"monotonic", "boottime"}:
            raise ValueError
        encoded = json.dumps({"boot_id": boot, "offsets": offsets}, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
    except (OSError, ValueError, UnicodeError):
        raise ValueError("Linux shared clock domain unavailable") from None
