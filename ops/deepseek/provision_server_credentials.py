#!/usr/bin/env python3
"""Explicit server-only, same-identity private copies for API/Web bind mounts.

Never prints, hashes, rotates or broadens the source secrets. Worker keeps using
the original wrapping/model files via PID1 LoadCredential. No service is started.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
from pathlib import Path

from release_files import canonical_directory, json_new, write_new


def private_read(path: Path, *, maximum: int, group_read: bool = False) -> bytes:
    if (not path.is_absolute() or path.resolve(strict=True) != path
            or any(parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022
                   for parent in (path.parent, *path.parent.parents))):
        raise ValueError("unsafe source location")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        allowed = {0o400, 0o600, 0o640} if group_read else {0o400, 0o600}
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) not in allowed or not 0 < before.st_size <= maximum):
            raise ValueError("unsafe source permissions")
        content = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if ((before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_gid,
         before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_gid,
                after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(content) != before.st_size):
        raise ValueError("source changed")
    return content


def operator_from_env(content: bytes) -> bytes:
    found = []
    for line in content.decode().splitlines():
        key, separator, value = line.partition("=")
        if separator and key == "HYPERTEST_CONNECTOR_OPERATOR_KEY":
            found.append(value.strip())
    if (len(found) != 1 or not 32 <= len(found[0]) <= 512
            or not re.fullmatch(r"[!-~]+", found[0]) or any(char in found[0] for char in "'\"`$")):
        raise ValueError("existing operator identity unavailable")
    return found[0].encode()


def provision(args: argparse.Namespace) -> dict:
    canonical_directory(args.output.parent)
    if any(path.stat().st_uid != 0 or path.stat().st_mode & 0o022
           for path in (args.output.parent, *args.output.parent.parents)):
        raise ValueError("private destination must have trusted root-owned ancestors")
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("new credential leaf required; preserve existing files")
    wrapping = private_read(args.wrapping_key, maximum=128)
    if len(base64.b64decode(wrapping.strip(), validate=True)) != 32:
        raise ValueError("invalid existing wrapping identity")
    operator = operator_from_env(private_read(args.platform_env, maximum=65536, group_read=True))
    if (args.public_ca.resolve(strict=True) != args.public_ca or args.public_ca.is_symlink()
            or not args.public_ca.is_file() or args.public_ca.stat().st_uid != 0
            or args.public_ca.stat().st_mode & 0o022):
        raise ValueError("trusted public CA source required")
    ca = args.public_ca.read_bytes()
    if not 0 < len(ca) <= 1024 * 1024 or b"PRIVATE KEY" in ca or b"BEGIN CERTIFICATE" not in ca:
        raise ValueError("public certificate only")
    args.output.mkdir(mode=0o700)
    json_new(args.output / "intent.json", {"profile": "hypertest-cloud-private-copy/v1",
        "action": "SAME_IDENTITY_COPIES", "service_started": False})
    for name, content, uid, gid, mode in (
        ("api-wrapping-key", wrapping, args.api_uid, args.api_gid, 0o600),
        ("web-operator-key", operator, 1000, 1000, 0o600),
        ("issuer-ca.crt", ca, 0, 0, 0o444)):
        path = args.output / name
        write_new(path, content, mode=mode)
        os.chown(path, uid, gid)
    result = {"profile": "hypertest-cloud-private-copy/v1", "status": "PREPARED",
        "same_wrapping_identity": True, "same_operator_identity": True,
        "source_permissions_changed": False, "credential_values_emitted": False,
        "service_started": False, "api_uid": args.api_uid, "api_gid": args.api_gid,
        "web_uid": 1000, "web_gid": 1000}
    json_new(args.output / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-private-copies", action="store_true")
    parser.add_argument("--wrapping-key", type=Path, required=True)
    parser.add_argument("--platform-env", type=Path, required=True)
    parser.add_argument("--public-ca", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-uid", type=int, default=999)
    parser.add_argument("--api-gid", type=int, default=989)
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or os.geteuid() != 0 or not args.allow_private_copies:
            raise ValueError("explicit authorized Linux root action required")
        if (args.api_uid, args.api_gid) != (999, 989):
            raise ValueError("fixed server API identity required")
        print(json.dumps(provision(args), sort_keys=True))
        return 0
    except (OSError, ValueError, UnicodeError):
        print(json.dumps({"status": "REFUSED", "code": "CLOUD_PRIVATE_PROVISION_INVALID"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
