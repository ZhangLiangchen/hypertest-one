#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
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
  .venv/bin/python -c 'from hypertest.main import app; assert app.openapi()["paths"]; print("API import and database migrations verified")'
  exit 0
fi

exec .venv/bin/python scripts/dev-services.py
