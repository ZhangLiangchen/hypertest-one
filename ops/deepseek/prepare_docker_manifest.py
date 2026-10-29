#!/usr/bin/env python3
"""Prepare a release manifest for an existing image from an exact pushed Git SHA.

No container is started with secrets, network or a model. The caller must put
this nonsecret file in a root-owned, readonly volume before service admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path

HEX40 = re.compile(r"[a-f0-9]{40}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
REMOTE = re.compile(r"origin/[A-Za-z0-9_./-]+\Z")


def output(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, timeout=60).strip()


def hash_command(args: list[str], cwd: Path) -> str:
    digest = hashlib.sha256()
    process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(120, process.kill)
    timer.start()
    try:
        total = 0
        while chunk := process.stdout.read(1024 * 1024):
            total += len(chunk)
            if total > 4 * 1024**3:
                raise ValueError("archive exceeds limit")
            digest.update(chunk)
        if process.wait(timeout=30):
            raise ValueError("archive failed")
        return digest.hexdigest()
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def prepare(*, checkout: Path, commit: str, remote_ref: str, image_id: str, destination: Path) -> dict:
    if (not checkout.is_absolute() or checkout.resolve(strict=True) != checkout or not HEX40.fullmatch(commit)
            or not IMAGE.fullmatch(image_id) or not REMOTE.fullmatch(remote_ref) or ".." in remote_ref
            or not destination.is_absolute() or destination.exists() or destination.is_symlink()
            or destination.parent.resolve(strict=True) != destination.parent):
        raise ValueError("invalid release identity or output")
    if (output(["git", "rev-parse", "HEAD"], checkout) != commit
            or output(["git", "rev-parse", "refs/remotes/" + remote_ref], checkout) != commit
            or output(["git", "status", "--porcelain", "--untracked-files=all"], checkout)):
        raise ValueError("checkout and fetched origin ref must equal the clean pushed commit")
    image = json.loads(output(["docker", "image", "inspect", image_id], checkout))
    if (not isinstance(image, list) or len(image) != 1 or image[0]["Id"] != image_id
            or image[0]["Config"]["Labels"].get("org.opencontainers.image.revision") != commit):
        raise ValueError("image revision differs from commit")
    base = ["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "997:0",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    sdk = output(base + ["--entrypoint", "/opt/hypertest-cloud/venv/bin/python", image_id, "-I", "-c",
        "import importlib.metadata as m; print(m.version('deepseek-harness-sdk')); print(m.version('deepseek-harness-runtime-bin'))"], checkout)
    if sdk.splitlines() != ["0.2.1rc2", "0.2.1rc2"]:
        raise ValueError("SDK/runtime versions differ")
    source_sha = hash_command(["git", "archive", "--format=tar", commit], checkout)
    venv_sha = hash_command(base + ["--entrypoint", "tar", image_id, "--sort=name", "--mtime=@0", "--owner=0",
        "--group=0", "-cf", "-", "-C", "/opt/hypertest-cloud/venv", "."], checkout)
    manifest = {"profile": "hypertest-cloud-worker-release/v1", "source_commit": commit,
        "source_archive_sha256": source_sha, "rootfs_image_sha256": image_id[7:],
        "venv_archive_sha256": venv_sha, "sdk_version": "0.2.1rc2", "runtime_version": "0.2.1rc2"}
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    try:
        os.fchmod(fd, 0o644)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("manifest write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"source_commit": commit, "image_id": image_id, "release_manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "model_started": False, "work_claimed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--remote-ref", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(checkout=args.checkout, commit=args.commit, remote_ref=args.remote_ref,
                         image_id=args.image_id, destination=args.destination)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "code": "DOCKER_RELEASE_PREPARATION_FAILED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
