"""Mechanical public catalog renderer; no secret reads, SSH or process launch."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
from pathlib import Path

from hypertest.cloud.ssh_profile import (
    SSH_ACCESS_PROFILE,
    canonical_target,
    digest,
    public_key,
    validate_profile,
)


def render(*, host: str, port: int, user: str, host_public_file: Path,
           authority_public_file: Path, helper_source: Path, action_source: Path) -> dict:
    host_public = public_key(" ".join(host_public_file.read_text().split()[:2]))
    raw = authority_public_file.read_bytes()
    if len(raw) == 32:
        raw = b"ssh-ed25519 " + base64.b64encode(struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + raw)
    authority = public_key(raw.decode().strip())
    catalog = {"profile": SSH_ACCESS_PROFILE, "target": canonical_target(host, port, user),
        "helper_sha256": hashlib.sha256(helper_source.read_bytes()).hexdigest(),
        "authority_public_key": authority,
        "actions": [{"key": "read-deployment", "script_path": "/opt/hypertest-ssh/actions/read-deployment",
            "script_sha256": hashlib.sha256(action_source.read_bytes()).hexdigest(), "timeout_seconds": 10,
            "stdout_limit_bytes": 65536, "stderr_limit_bytes": 65536}], "max_operations": 8}
    environment = {"name": "Isolated loopback SSH diagnostic fixture", "connection": "SSH",
        "host": host, "port": port, "user": user, "host_key": host_public,
        "expected_deployment": "hypertest-ssh-fixture-r25", "require_matching_deployment": False,
        "ssh_access": {k: v for k, v in catalog.items() if k != "target"}}
    environment["ssh_access"]["catalog_sha256"] = digest(catalog)
    validate_profile(environment)
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--user", default="hypertest-ssh-fixture")
    for name in ("host-public-file", "authority-public-file", "helper-source", "action-source", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    values = vars(args)
    output = values.pop("output")
    data = json.dumps(render(**values), sort_keys=True, indent=2).encode() + b"\n"
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)
    print(json.dumps({"status": "RENDERED_NOT_EXECUTED", "catalog_sha256": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    main()
