#!/usr/bin/env python3
"""Install a locally downloaded, SHA256-pinned CLI without touching Agent configuration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_file(path: Path, data: bytes, mode: int):
    temporary = path.parent / ("." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--install-dir", type=Path, default=Path.home() / ".local/share/hypertest-cli")
    args = parser.parse_args()
    if sys.version_info < (3, 12) or sys.platform not in {"linux", "darwin"}:
        parser.error("requires Python >=3.12 on Linux or macOS")
    if not re.fullmatch(r"[a-f0-9]{64}", args.sha256):
        parser.error("an independently obtained lowercase SHA256 is required")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", args.version):
        parser.error("invalid version")
    if args.artifact.is_symlink() or not args.artifact.is_file() or args.artifact.stat().st_size > 5 * 1024 * 1024:
        parser.error("regular local CLI artifact required")
    data = args.artifact.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.sha256:
        parser.error("artifact SHA256 mismatch")
    executable = str(Path(sys.executable).absolute())
    if any(character.isspace() for character in executable):
        parser.error("Python executable path must not contain whitespace")
    # Execute only after the caller-provided digest has been checked.
    with tempfile.TemporaryDirectory(prefix="hypertest-cli-check-") as temporary:
        frozen = Path(temporary) / "hypertest.pyz"
        frozen.write_bytes(data)
        checked = subprocess.run([executable, str(frozen), "--version"], capture_output=True, text=True)
        if checked.returncode or checked.stdout.strip() != "hypertest " + args.version:
            parser.error("artifact version/runtime check failed")
    directory, bin_dir = args.install_dir.expanduser().absolute(), args.bin_dir.expanduser().absolute()
    for path in (directory, bin_dir):
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            parser.error("installation path contains a symlink")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        parser.error("install directory must be owned by this user with mode 0700")
    bin_dir.mkdir(parents=True, exist_ok=True)
    command, receipt_path = bin_dir / "hypertest", directory / "installation.json"
    if command.exists() or command.is_symlink():
        if (command.is_symlink() or receipt_path.is_symlink() or not receipt_path.is_file()):
            parser.error("existing command has no managed installation receipt")
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("command") != str(command) or receipt.get("command_sha256") != sha256(command):
            parser.error("existing command was modified; preserving it")
    release = directory / "releases" / args.version
    release.mkdir(parents=True, mode=0o700, exist_ok=True)
    installed = release / "hypertest.pyz"
    if installed.exists() and (installed.is_symlink() or sha256(installed) != args.sha256):
        parser.error("version already exists with different bytes; preserving it")
    if not installed.exists():
        write_file(installed, data, 0o600)
    launcher = (f"#!{executable}\nimport runpy, sys\n"
                f"sys.argv[0] = {str(installed)!r}\nrunpy.run_path({str(installed)!r}, run_name='__main__')\n").encode()
    write_file(command, launcher, 0o755)
    write_file(receipt_path, json.dumps({"version": args.version, "artifact_sha256": args.sha256,
               "command": str(command), "command_sha256": hashlib.sha256(launcher).hexdigest(),
               "runtime": executable, "release": str(installed)}, sort_keys=True).encode(), 0o600)
    print(json.dumps({"status": "INSTALLED", "version": args.version, "command": str(command),
                      "path_instruction": f"Add {bin_dir} to PATH", "agent_configuration_modified": False}))


if __name__ == "__main__":
    main()
