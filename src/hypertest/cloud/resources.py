"""Read-only admission of an existing dedicated cgroup-v2 resource envelope.

No cgroup is created, modified or delegated here. A container's cgroup namespace
may expose its own leaf at /sys/fs/cgroup; cgroup.procs must attest membership.
Unsupported hierarchy layouts fail closed instead of guessing a host path.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import CloudBlocked


def inspect_resource_envelope(*, root: Path = Path("/sys/fs/cgroup"),
                              membership: Path = Path("/proc/self/cgroup"), pid: int | None = None,
                              max_memory_bytes: int = 4 * 1024 ** 3,
                              max_processes: int = 256) -> dict[str, int | str]:
    """Require effective finite memory+swap and pid limits for this Worker.

    The Worker is single-attempt/serial. Its SDK, PID namespace, model broker and
    all descendants inherit this aggregate envelope. Deployment must dedicate the
    cgroup to the Worker; this check does not prove isolation from sibling services.
    """
    try:
        if not (root / "cgroup.controllers").is_file():
            raise CloudBlocked("CGROUP_V2_REQUIRED", "Cloud execution requires a preconfigured cgroup-v2 envelope")
        entries = membership.read_text().splitlines()
        unified = next((line[3:] for line in entries if line.startswith("0::")), None)
        if unified is None or not unified.startswith("/") or ".." in Path(unified).parts:
            raise CloudBlocked("CGROUP_SCOPE_UNVERIFIED", "Worker cgroup membership is not verifiable")
        candidates = (root / unified.lstrip("/"), root)
        own_pid = str(os.getpid() if pid is None else pid)
        leaf = None
        for candidate in candidates:
            try:
                with (candidate / "cgroup.procs").open() as stream:
                    contents = stream.read(65537)
                if len(contents) > 65536:
                    continue
                processes = contents.splitlines()
                if own_pid in processes:
                    leaf = candidate
                    break
            except OSError:
                continue
        if leaf is None:
            raise CloudBlocked("CGROUP_SCOPE_UNVERIFIED", "Worker is not in the inspected resource scope")
        values: dict[str, list[int]] = {"memory.max": [], "memory.swap.max": [], "pids.max": []}
        current = leaf
        for _ in range(64):
            for name in values:
                file = current / name
                if not file.exists():
                    continue
                with file.open() as stream:
                    value = stream.read(128).strip()
                if value != "max":
                    if not value.isdecimal():
                        raise CloudBlocked("CGROUP_RESOURCE_LIMIT_UNAVAILABLE", "Resource envelope contains an unsupported limit")
                    values[name].append(int(value))
            if current == root:
                break
            current = current.parent
        else:
            raise CloudBlocked("CGROUP_SCOPE_UNVERIFIED", "Resource scope ancestry exceeds its verification bound")
        if any(not observed for observed in values.values()):
            raise CloudBlocked("CGROUP_RESOURCE_LIMIT_UNBOUNDED", "Finite aggregate memory, swap and pid limits are required")
        memory, swap, pids = (min(values[name]) for name in values)
        if memory < 1 or pids < 1 or memory + swap > max_memory_bytes or pids > max_processes:
            raise CloudBlocked("CGROUP_RESOURCE_LIMIT_EXCEEDED", "Existing resource envelope exceeds the supported worker limits")
        return {"kind": "CGROUP_V2", "memory_max_bytes": memory,
                "swap_max_bytes": swap, "pids_max": pids}
    except OSError:
        raise CloudBlocked("CGROUP_RESOURCE_LIMIT_UNAVAILABLE", "Existing resource envelope cannot be read") from None
