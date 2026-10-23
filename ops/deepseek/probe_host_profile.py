"""No-prompt acceptance of the dedicated non-root host Worker profile.

This checks effective outer isolation before using the unchanged production
bubblewrap probe. It never starts a model broker or installs a service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

from probe_cloud_sandbox import probe

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.resources import inspect_resource_envelope

_ENVIRONMENT_KEYS = frozenset({"PATH", "HOME", "LANG", "LC_CTYPE", "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "TMPDIR", "CREDENTIALS_DIRECTORY"})
_CAPABILITIES = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")


def inspect_outer_profile() -> dict:
    if sys.platform != "linux":
        raise CloudBlocked("OUTER_PROFILE_LINUX_REQUIRED", "The dedicated host profile requires Linux")
    uid, gid = os.getuid(), os.getgid()
    if uid == 0 or uid != os.geteuid() or gid != os.getegid():
        raise CloudBlocked("OUTER_PROFILE_IDENTITY_UNSAFE", "Use a fixed non-root service identity without set-id transitions")
    with Path("/proc/self/status").open() as stream:
        status = stream.read(65537)
    if len(status) > 65536:
        raise CloudBlocked("OUTER_PROFILE_STATUS_UNAVAILABLE", "Process status exceeds its observation bound")
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if fields.get("NoNewPrivs", "").strip() != "1":
        raise CloudBlocked("OUTER_PROFILE_PRIVILEGES_UNSAFE", "No-new-privileges must be effective")
    try:
        capabilities_empty = all(int(fields[name].strip(), 16) == 0 for name in _CAPABILITIES)
    except (KeyError, ValueError):
        capabilities_empty = False
    if not capabilities_empty:
        raise CloudBlocked("OUTER_PROFILE_CAPABILITIES_UNSAFE", "All outer process capability sets must be empty")
    if set(os.environ) - _ENVIRONMENT_KEYS:
        raise CloudBlocked("OUTER_PROFILE_ENVIRONMENT_UNSAFE", "Launch the probe with the documented empty environment")
    if not os.statvfs("/").f_flag & os.ST_RDONLY:
        raise CloudBlocked("OUTER_PROFILE_ROOT_WRITABLE", "The dedicated root filesystem must be readonly")
    if not os.statvfs("/sys/fs/cgroup").f_flag & os.ST_RDONLY:
        raise CloudBlocked("OUTER_PROFILE_CGROUP_WRITABLE", "The resource hierarchy must be readonly and not delegated")
    temporary = Path("/tmp").stat()
    temporary_mode = stat.S_IMODE(temporary.st_mode)
    private_owner = temporary.st_uid == uid and temporary_mode == 0o700
    sticky_root = temporary.st_uid == 0 and temporary_mode == 0o1777
    if not stat.S_ISDIR(temporary.st_mode) or not (private_owner or sticky_root) or not os.access("/tmp", os.W_OK | os.X_OK):
        raise CloudBlocked("OUTER_PROFILE_TMP_UNWRITABLE", "Use a private writable temporary filesystem with safe ownership and mode")
    temporary_flags = os.statvfs("/tmp").f_flag
    if temporary_flags & (os.ST_RDONLY | os.ST_NOEXEC) or (temporary_flags & (os.ST_NOSUID | os.ST_NODEV)) != (os.ST_NOSUID | os.ST_NODEV):
        raise CloudBlocked("OUTER_PROFILE_TMP_FLAGS_UNSAFE", "Native-addon temporary files require exec, nosuid and nodev")
    envelope = inspect_resource_envelope()
    return {"profile": "dedicated-nonroot-systemd-rootdirectory/v1alpha1",
        "uid": uid, "gid": gid, "no_new_privileges": True,
        "capabilities_empty": True, "root_readonly": True, "cgroup_readonly": True,
        "temporary_writable": True, "temporary_exec": True, "resource_envelope": envelope}


async def run_probe(*, timeout_seconds: int) -> dict:
    try:
        outer = inspect_outer_profile()
    except Exception as error:
        code = getattr(error, "code", "OUTER_PROFILE_OBSERVATION_FAILED")
        return {"status": "BLOCKED", "reason": code, "runtime_started": False,
            "runtime_closed": True, "model_prompt_sent": False,
            "production_namespace_proven": False, "test_result": "NOT_RUN"}
    try:
        result = await probe(backend="sandbox", address_space_gib=4, timeout=timeout_seconds)
    except Exception:
        # Do not expose native paths/errors or infer cleanup from a lost result.
        result = {"status": "BLOCKED", "reason": "OUTER_PROFILE_PROBE_FAILED",
            "runtime_closed": False, "model_prompt_sent": False,
            "production_namespace_proven": False, "test_result": "NOT_RUN"}
    return {**result, "outer_profile": outer}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-protocol-probe", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, choices=range(5, 61), default=30)
    args = parser.parse_args(argv)
    if not args.allow_protocol_probe:
        print(json.dumps({"status": "NOT_RUN", "reason": "EXPLICIT_PROTOCOL_PROBE_FLAG_REQUIRED"}))
        return 1
    result = asyncio.run(run_probe(timeout_seconds=args.timeout_seconds))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
