#!/usr/bin/env bash
set -euo pipefail

# Explicit operator operation. Runs never invoke this script, pull or install.
# Both approved profiles share the same offline, digest-pinned Dockerfile.
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
profile_id="${1:-python-pytest-v1}"
case "$profile_id" in
  python-pytest-v1) image="${HYPERTEST_RUNNER_CONTROLLED_IMAGE:-hypertest-runner:py312-controlled}" ;;
  python-api-v1) image="${HYPERTEST_RUNNER_API_IMAGE:-hypertest-runner:py312-api-v1}" ;;
  *) printf '%s\n' 'Unsupported trusted Runner profile' >&2; exit 2 ;;
esac
build_context="$(mktemp -d "${TMPDIR:-/tmp}/hypertest-runner-build.XXXXXX")"
trap 'rm -rf -- "$build_context"' EXIT
runner_root="$repo_root/src/hypertest/runner"
cp "$runner_root/Dockerfile" "$build_context/Dockerfile"
cp "$runner_root/locks/$profile_id.txt" "$build_context/requirements.txt"
cp "$runner_root/service_launcher.py" "$build_context/service_launcher.py"
base_image="${HYPERTEST_RUNNER_BASE_IMAGE:-python:3.12-slim}"
# Pin the manifest digest used for this image, even when the operator supplied a tag.
docker pull "$base_image"
base_digest="$(docker image inspect "$base_image" --format '{{index .RepoDigests 0}}')"
if [[ ! "$base_digest" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]]; then
  printf '%s\n' 'Trusted base image requires a registry manifest digest' >&2; exit 2
fi
architecture="$(docker image inspect "$base_image" --format '{{.Architecture}}')"
case "$architecture" in
  amd64) wheel_platform=x86_64 ;;
  arm64) wheel_platform=aarch64 ;;
  *) printf '%s\n' 'Approved wheel locks support only Linux amd64 and arm64' >&2; exit 2 ;;
esac
python -m pip download --disable-pip-version-check --no-cache-dir --only-binary=:all: \
  --platform "manylinux2014_$wheel_platform" --platform "manylinux_2_28_$wheel_platform" \
  --python-version 3.12 --implementation cp --abi cp312 --require-hashes \
  --dest "$build_context/wheels" -r "$build_context/requirements.txt"
lock_sha="$(python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$build_context/requirements.txt")"
launcher_sha="$(python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$build_context/service_launcher.py")"
docker build --network none --tag "$image" \
  --build-arg "BASE_IMAGE=$base_digest" --build-arg "BASE_IMAGE_DIGEST=$base_digest" \
  --build-arg "PROFILE_ID=$profile_id" --build-arg "DEPENDENCY_LOCK_SHA256=$lock_sha" \
  --build-arg "LAUNCHER_SHA256=$launcher_sha" "$build_context"
