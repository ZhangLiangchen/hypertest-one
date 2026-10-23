"""Freeze a remotely prepared, locked official npm closure. Never downloads/runs it.

Run only in an authorized image-preparation environment after reviewing the
full registry lock and running npm ci --ignore-scripts --no-audit --no-fund.
The runtime/Worker never invokes npm, downloads plugins or selects host CLIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

from hypertest.cloud.delegation import (
    BUNDLE_VERSION,
    CODEX_VERSION,
    HARNESS_SOURCE,
    NPM_PINS,
    PAYLOAD_PROFILE,
    validate_lock,
    verify_payload,
)


def freeze_payload(staging: Path, node: Path, node_sha256: str, output: Path) -> str:
    validate_lock(json.loads((staging / "package-lock.json").read_bytes()))
    if (node.is_symlink() or not stat.S_ISREG(node.stat().st_mode)
            or hashlib.sha256(node.read_bytes()).hexdigest() != node_sha256):
        raise ValueError("Node must match an independently trusted deployment digest")
    output.mkdir(mode=0o755)  # Never overwrite a prior payload or manifest.
    (output / "bin").mkdir(mode=0o755)
    shutil.copyfile(node, output / "bin/node")
    os.chmod(output / "bin/node", 0o755)
    for name in ("package.json", "package-lock.json"):
        shutil.copyfile(staging / name, output / name)
        os.chmod(output / name, 0o644)
    modules = staging / "node_modules"
    if modules.is_symlink() or not modules.is_dir():
        raise ValueError("Expected an ordinary installed npm closure")
    for directory, directories, filenames in os.walk(modules, followlinks=False):
        # npm executable aliases are unused; only package-local absolute paths
        # and the manifest's trusted Node are selected by the profile.
        directories[:] = [name for name in directories if name != ".bin"]
        source_root = Path(directory)
        if source_root.is_symlink() or any((source_root / name).is_symlink() for name in directories):
            raise ValueError("Delegate closure must not contain directory symlinks")
        destination = output / source_root.relative_to(staging)
        destination.mkdir(mode=0o755, parents=True, exist_ok=True)
        for name in filenames:
            source = source_root / name
            if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
                raise ValueError("Delegate closure must contain ordinary files only")
            shutil.copyfile(source, destination / name)
            os.chmod(destination / name, 0o755 if source.stat().st_mode & 0o111 else 0o644)
    files = {}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            value = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    value.update(block)
            files[path.relative_to(output).as_posix()] = value.hexdigest()
    manifest = {"profile": PAYLOAD_PROFILE, "source_commit": HARNESS_SOURCE,
        "bundle_version": BUNDLE_VERSION, "codex_version": CODEX_VERSION,
        "npm_registry": "https://registry.npmjs.org", "official_tarballs": NPM_PINS,
        "node_sha256": node_sha256, "files": files}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (output / "manifest.json").write_bytes(raw)
    os.chmod(output / "manifest.json", 0o644)
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    verify_payload(output, manifest_sha256)
    return manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--node-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest_digest = freeze_payload(args.staging, args.node, args.node_sha256, args.output)
    except Exception:
        # Installation/path diagnostics can expose operator context; no raw error.
        print(json.dumps({"status": "UNAVAILABLE", "code": "DELEGATE_PREPARATION_FAILED"}))
        return 1
    print(json.dumps({"status": "FROZEN", "manifest_sha256": manifest_digest,
        "source_commit": HARNESS_SOURCE, "bundle_version": BUNDLE_VERSION,
        "codex_version": CODEX_VERSION, "model_started": False, "delegation_observed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
