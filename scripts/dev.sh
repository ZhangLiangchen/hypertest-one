#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ -x /workspace/.setup-tools/node_modules/node/bin/node ]]; then
  export PATH="/workspace/.setup-tools/node_modules/node/bin:$PATH"
fi
if [[ ! -x .venv/bin/uvicorn || ! -d web/node_modules ]]; then
  echo "Install Python development dependencies into .venv and run npm ci in web first." >&2
  exit 1
fi
if [[ "$(node -p 'process.versions.node.split(".")[0]')" != 22 ]]; then
  echo "Use Node.js 22 to run the workbench." >&2
  exit 1
fi
.venv/bin/alembic upgrade head
if [[ "${1:-}" == --check ]]; then
  .venv/bin/python -c 'from hypertest.main import app; assert app.openapi()["paths"]; print("API imports and database migrations verified")'
  exit 0
fi

api_port="${HYPERTEST_DEV_API_PORT:-8000}"
web_port="${HYPERTEST_DEV_WEB_PORT:-3000}"
export HYPERTEST_API_ORIGIN="http://127.0.0.1:$api_port"
export NEXT_TELEMETRY_DISABLED=1
api_pid=""
web_pid=""
cleanup() {
  [[ -z "$api_pid" ]] || kill "$api_pid" 2>/dev/null || true
  [[ -z "$web_pid" ]] || kill -- "-$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
.venv/bin/uvicorn hypertest.main:app --host 127.0.0.1 --port "$api_port" &
api_pid=$!
setsid npm --prefix web run dev -- --hostname 127.0.0.1 --port "$web_port" &
web_pid=$!
wait -n "$api_pid" "$web_pid"
