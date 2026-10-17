#!/usr/bin/env bash
set -euo pipefail

# Resolve packages through the host's supported HTTPS route. Docker builds then
# need no PyPI connectivity; the workload containers never install dependencies.
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_context="$(mktemp -d "${TMPDIR:-/tmp}/hypertest-runner-build.XXXXXX")"
trap 'rm -rf -- "$build_context"' EXIT
cp "$repo_root/src/hypertest/runner/Dockerfile" "$build_context/Dockerfile"
python -m pip download --no-cache-dir --only-binary=:all: --dest "$build_context/wheels" 'pytest==8.3.5'
docker build --tag "${HYPERTEST_RUNNER_IMAGE:-hypertest-runner:py312}" "$build_context"
