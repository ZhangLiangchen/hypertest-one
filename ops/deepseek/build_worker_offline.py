#!/usr/bin/env python3
"""Build the Worker from a pushed commit, reusing the reviewed runtime image.

The separate wheelhouse contains only the six pinned public build-backend
wheels, not credentials. No build step has network access. This script never
starts a Worker, model, database or SUT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

BASE_TAG = "hypertest-mac-cloud-worker:9556f2a"
BASE_ID = "sha256:0bd3f2109268a4c7b77ba940031d5d31d920d9b5b9ede36499cc90d90e0ec3ee"
BASE_COMMIT = "9556f2a4e82d7ae164dc2a90fe62c6f157d51492"
WHEELS = {
    "hatchling-1.32.4-py3-none-any.whl": "08ecf7548fb48205e7f213d70c71e67b8271b7242093dc3f1da578b42c734a2c",
    "packaging-26.1-py3-none-any.whl": "5d9c0669c6285e491e0ced2eee587eaf67b670d94a19e94e3984a481aba6802f",
    "pathspec-1.1.1-py3-none-any.whl": "a00ce642f577bf7f473932318056212bc4f8bfdf53128c78bbd5af0b9b20b189",
    "pluggy-1.7.0-py3-none-any.whl": "7dd7b0d8832ba3cb632c306926ded123429211b83641b35dc5c41ad2d34f9bec",
    "tomlkit-0.15.2-py3-none-any.whl": "05562412163a3037b94497385fb7f9204c637bc605af7a48199e41cf2272f437",
    "trove_classifiers-2026.9.21.13-py3-none-any.whl": "8b1ff4f9c191b1040b71c37f1e445ab99732911e3cd91de52838453a854d7a17",
}
RUNTIME_WHEELS = {
    "requests-2.34.2-py3-none-any.whl": "2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0",
    "urllib3-2.7.0-py3-none-any.whl": "9fb4c81ebbb1ce9531cce37674bbc6f1360472bc18ca9a553ede278ef7276897",
    "charset_normalizer-3.4.7-py3-none-any.whl": "3dce51d0f5e7951f8bb4900c257dad282f49190fdbebecd4ba99bcc41fef404d",
    "pytest-8.4.2-py3-none-any.whl": "872f880de3fc3a5bdc88a11b39c9710c3497a547cfa9320bc3c5e62fbf272e79",
    "iniconfig-2.1.0-py3-none-any.whl": "9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760",
    "packaging-26.1-py3-none-any.whl": "5d9c0669c6285e491e0ced2eee587eaf67b670d94a19e94e3984a481aba6802f",
    "pluggy-1.7.0-py3-none-any.whl": "7dd7b0d8832ba3cb632c306926ded123429211b83641b35dc5c41ad2d34f9bec",
    "pygments-2.19.2-py3-none-any.whl": "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b",
}
RUNTIME_PACKAGES = {"requests==2.34.2", "urllib3==2.7.0", "charset-normalizer==3.4.7",
                    "pytest==8.4.2", "iniconfig==2.1.0", "packaging==26.1",
                    "pluggy==1.7.0", "Pygments==2.19.2"}


def run(command: list[str], *, cwd: Path, timeout: int = 120) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True, timeout=timeout).strip()


def inspect(image: str, cwd: Path) -> dict:
    rows = json.loads(run(["docker", "image", "inspect", image], cwd=cwd))
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("image identity unavailable")
    return rows[0]


def freeze(image: str, cwd: Path) -> list[str]:
    raw = run(["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "997:0",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--entrypoint",
        "/opt/hypertest-cloud/venv/bin/pip", image, "freeze", "--all"], cwd=cwd)
    return sorted(line for line in raw.splitlines() if not line.lower().startswith("hypertest-one "))


def build(*, checkout: Path, commit: str, remote_ref: str, wheelhouse: Path, runtime_wheelhouse: Path) -> dict:
    if (not checkout.is_absolute() or checkout.resolve(strict=True) != checkout
            or not wheelhouse.is_absolute() or wheelhouse.resolve(strict=True) != wheelhouse
            or not runtime_wheelhouse.is_absolute() or runtime_wheelhouse.resolve(strict=True) != runtime_wheelhouse
            or not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"origin/[A-Za-z0-9_./-]+", remote_ref)
            or ".." in remote_ref):
        raise ValueError("invalid fixed build inputs")
    if (run(["git", "rev-parse", "HEAD"], cwd=checkout) != commit
            or run(["git", "rev-parse", "refs/remotes/" + remote_ref], cwd=checkout) != commit
            or run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=checkout)):
        raise ValueError("checkout must be clean at the pushed remote commit")
    result = subprocess.run(["git", "diff", "--quiet", BASE_COMMIT, commit, "--", "pyproject.toml", "README.md",
        "requirements/cloud-runtime.lock", "skills"], cwd=checkout, check=False)
    if result.returncode != 0:
        raise ValueError("runtime dependencies or packaged skills changed")
    if set(p.name for p in wheelhouse.iterdir()) != set(WHEELS):
        raise ValueError("wheelhouse must contain only the pinned wheels")
    for filename, expected in WHEELS.items():
        p = wheelhouse / filename
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError("offline build wheel integrity mismatch")
    if set(p.name for p in runtime_wheelhouse.iterdir()) != set(RUNTIME_WHEELS):
        raise ValueError("runtime wheelhouse must contain only the pinned wheels")
    for filename, expected in RUNTIME_WHEELS.items():
        p = runtime_wheelhouse / filename
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError("offline runtime wheel integrity mismatch")
    base = inspect(BASE_TAG, checkout)
    if base["Id"] != BASE_ID or base["Config"]["Labels"].get("org.opencontainers.image.revision") != BASE_COMMIT:
        raise ValueError("runtime base differs from the reviewed image")
    before = freeze(BASE_ID, checkout)
    with tempfile.TemporaryDirectory(prefix="hypertest-offline-image-") as directory:
        iid = Path(directory) / "image.id"
        env = {**os.environ, "DOCKER_BUILDKIT": "1"}
        subprocess.run(["docker", "build", "--pull=false", "--network", "none", "--build-context",
            "wheelhouse=" + str(wheelhouse), "--build-context", "runtime_wheelhouse=" + str(runtime_wheelhouse),
            "--build-arg", "DEPENDENCY_IMAGE=" + BASE_TAG,
            "--build-arg", "SOURCE_COMMIT=" + commit, "--iidfile", str(iid),
            "-f", "ops/deepseek/Dockerfile.worker.offline", "."], cwd=checkout, env=env, check=True, timeout=1800)
        image_id = iid.read_text().strip()
    built = inspect(image_id, checkout)
    base_after = inspect(BASE_TAG, checkout)
    layers = base["RootFS"]["Layers"]
    after = freeze(image_id, checkout)
    if (base_after["Id"] != BASE_ID or built["Id"] != image_id
            or built["Config"]["Labels"].get("org.opencontainers.image.revision") != commit
            or built["RootFS"]["Layers"][:len(layers)] != layers or set(after) != set(before) | RUNTIME_PACKAGES):
        raise ValueError("built image ancestry or runtime dependency set differs")
    return {"source_commit": commit, "base_image_id": BASE_ID, "image_id": image_id,
            "network": "DISABLED", "runtime_dependencies": "BASE_PLUS_PINNED_FRAMEWORK", "worker_started": False,
            "model_started": False, "work_claimed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--remote-ref", required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--runtime-wheelhouse", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(checkout=args.checkout, commit=args.commit, remote_ref=args.remote_ref,
                       wheelhouse=args.wheelhouse, runtime_wheelhouse=args.runtime_wheelhouse)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"status": "BLOCKED", "code": "DOCKER_OFFLINE_BUILD_FAILED"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
