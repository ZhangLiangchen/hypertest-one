#!/usr/bin/env bash
set -euo pipefail
# Explicit build-time network access only. No secrets/provider auth enter contexts.
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
output="${1:?usage: build-images.sh /absolute/new-images.env}"
[[ "$output" = /* && ! -e "$output" ]] || { printf '%s\n' 'Output must be a new absolute file' >&2; exit 2; }
resolve_base() {
    docker pull "$1" >&2
    docker image inspect "$1" --format '{{index .RepoDigests 0}}'
}
python_image="$(resolve_base "${HYPERTEST_BUILD_PYTHON_IMAGE:-python:3.12-slim}")"
node_image="$(resolve_base "${HYPERTEST_BUILD_NODE_IMAGE:-node:22-bookworm-slim}")"
cli_image="$(resolve_base "${HYPERTEST_BUILD_DOCKER_CLI_IMAGE:-docker:27-cli}")"
postgres_image="$(resolve_base "${HYPERTEST_BUILD_POSTGRES_IMAGE:-postgres:17}")"
nginx_image="$(resolve_base "${HYPERTEST_BUILD_NGINX_IMAGE:-nginx:stable}")"
for ref in "$python_image" "$node_image" "$cli_image" "$postgres_image" "$nginx_image"; do
    [[ "$ref" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]] || { printf '%s\n' 'Base requires registry digest' >&2; exit 2; }
done
build_dir="$(mktemp -d)"
trap 'rm -rf -- "$build_dir"' EXIT
for target in api worker; do
    docker build --target "$target" --iidfile "$build_dir/$target" \
        --build-arg "PYTHON_IMAGE=$python_image" --build-arg "DOCKER_CLI_IMAGE=$cli_image" "$repo_root"
done
docker build --iidfile "$build_dir/web" --build-arg "NODE_IMAGE=$node_image" \
    --build-arg HYPERTEST_API_ORIGIN=http://api:8000 "$repo_root/web"
# IDs identify exact local contents; no mutable tag is consumed by deployment.
(
    umask 077
    set -o noclobber
    {
        printf 'HYPERTEST_API_IMAGE=%s\n' "$(cat "$build_dir/api")"
        printf 'HYPERTEST_WORKER_IMAGE=%s\n' "$(cat "$build_dir/worker")"
        printf 'HYPERTEST_WEB_IMAGE=%s\n' "$(cat "$build_dir/web")"
        printf 'HYPERTEST_POSTGRES_IMAGE=%s\n' "$(docker image inspect "$postgres_image" --format '{{.Id}}')"
        printf 'HYPERTEST_NGINX_IMAGE=%s\n' "$(docker image inspect "$nginx_image" --format '{{.Id}}')"
    } > "$output"
)
printf 'Built fixed images: %s\n' "$output"
