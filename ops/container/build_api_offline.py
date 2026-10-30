#!/usr/bin/env python3
"""Build a Cloud-compatible API from the pushed source and fixed local images.

This reuses the existing API's third-party dependencies and uses the verified
Worker image only to build the project wheel; no model SDK enters the API.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

API_TAG = "hypertest-mac-api:903c9bd"
API_ID = "sha256:29523edc1b3ef0956c93c9f0f42a54cb7eee89e00980cc49b839602a42f39168"
API_COMMIT = "903c9bd81ad262f11c60aee68eddada1d8dee929"


def run(command: list[str], *, cwd: Path, timeout: int = 120) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True, timeout=timeout).strip()


def inspect(image: str, cwd: Path) -> dict:
    values = json.loads(run(["docker", "image", "inspect", image], cwd=cwd))
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError("image unavailable")
    return values[0]


def freeze(image: str, cwd: Path) -> list[str]:
    raw = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "501:20",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint", "pip",
        image, "freeze", "--all"], cwd=cwd)
    return sorted(line for line in raw.splitlines() if not line.lower().startswith("hypertest-one"))


def build(*, checkout: Path, commit: str, remote_ref: str, wheelhouse: Path, worker_id: str, worker_tag: str) -> dict:
    if (not checkout.is_absolute() or checkout.resolve(strict=True) != checkout
            or not wheelhouse.is_absolute() or wheelhouse.resolve(strict=True) != wheelhouse
            or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or not re.fullmatch(r"origin/[A-Za-z0-9_./-]+", remote_ref) or ".." in remote_ref
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", worker_id)
            or not re.fullmatch(r"hypertest-mac-cloud-worker:[a-z0-9][a-z0-9_.-]{0,80}", worker_tag)):
        raise ValueError("invalid fixed build inputs")
    if (run(["git", "rev-parse", "HEAD"], cwd=checkout) != commit
            or run(["git", "rev-parse", "refs/remotes/" + remote_ref], cwd=checkout) != commit
            or run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout)):
        raise ValueError("checkout must be clean at pushed commit")
    result = subprocess.run(["git", "diff", "--quiet", API_COMMIT, commit, "--", "pyproject.toml", "README.md",
        "skills", "ops/container/healthcheck.py"], cwd=checkout, check=False)
    if result.returncode != 0:
        raise ValueError("API dependencies or packaged assets changed")
    spec = importlib.util.spec_from_file_location("worker_offline", checkout / "ops/deepseek/build_worker_offline.py")
    if spec is None or spec.loader is None:
        raise ValueError("wheel lock unavailable")
    worker_build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker_build)
    if set(p.name for p in wheelhouse.iterdir()) != set(worker_build.WHEELS):
        raise ValueError("wheelhouse differs from fixed build inputs")
    for name, digest in worker_build.WHEELS.items():
        p = wheelhouse / name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise ValueError("build wheel integrity mismatch")
    api, worker = inspect(API_TAG, checkout), inspect(worker_tag, checkout)
    if (api["Id"] != API_ID or api["Config"]["Labels"].get("org.opencontainers.image.revision") != API_COMMIT
            or worker["Id"] != worker_id or worker["Config"]["Labels"].get("org.opencontainers.image.revision") != commit):
        raise ValueError("fixed image identity mismatch")
    before = freeze(API_ID, checkout)
    with tempfile.TemporaryDirectory(prefix="hypertest-offline-api-") as directory:
        iid = Path(directory) / "image.id"
        subprocess.run(["docker", "build", "--pull=false", "--network", "none", "--build-context",
            "wheelhouse=" + str(wheelhouse), "--build-arg", "WORKER_IMAGE=" + worker_tag,
            "--build-arg", "API_IMAGE=" + API_TAG, "--build-arg", "SOURCE_COMMIT=" + commit,
            "--iidfile", str(iid), "-f", "ops/container/Dockerfile.api.offline", "."], cwd=checkout,
            env={**os.environ, "DOCKER_BUILDKIT": "1"}, check=True, timeout=1800)
        image_id = iid.read_text().strip()
    built = inspect(image_id, checkout)
    if (inspect(API_TAG, checkout)["Id"] != API_ID or inspect(worker_tag, checkout)["Id"] != worker_id
            or built["Id"] != image_id or built["Config"]["Labels"].get("org.opencontainers.image.revision") != commit
            or built["RootFS"]["Layers"][:len(api["RootFS"]["Layers"])] != api["RootFS"]["Layers"]
            or freeze(image_id, checkout) != before):
        raise ValueError("API dependency or image identity changed")
    return {"source_commit": commit, "base_api_id": API_ID, "image_id": image_id,
            "network": "DISABLED", "runtime_dependencies": "MATCHED", "api_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--remote-ref", required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--worker-image-id", required=True)
    parser.add_argument("--worker-image-tag", required=True)
    args = parser.parse_args()
    try:
        result = build(checkout=args.checkout, commit=args.commit, remote_ref=args.remote_ref,
                       wheelhouse=args.wheelhouse, worker_id=args.worker_image_id, worker_tag=args.worker_image_tag)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "code": "DOCKER_OFFLINE_API_BUILD_FAILED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
