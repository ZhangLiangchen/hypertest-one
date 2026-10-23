# HyperTest interactive MCP 0.2.0

Source commit: `5c03e4d90bed69b6420238849cbb3a8bae2f4c42`. Release tag: `mcp-v0.2.0`.
This file describes a fixed build; a locally built asset is not proof of publication.
Use Python 3.12+ on macOS or Linux. The session management tools synchronize
tasks, cases and reports using a narrow task:sync grant; they do not execute tests.
Legacy submit/read/CLOUD tools remain separate. Current-Agent LOCAL execution
still requires the controlled Codex Desktop adapter.

Download this exact release wheel over HTTPS; do not install a moving branch,
`latest`, an unverified script, or an unrelated PyPI package:

```sh
mkdir -p "$HOME/.local/share/hypertest/releases/mcp-v0.2.0"
cd "$HOME/.local/share/hypertest/releases/mcp-v0.2.0"
curl --fail --show-error --proto '=https' --proto-redir '=https' --location \
  --output hypertest_one-0.2.0-py3-none-any.whl \
  'https://github.com/ZhangLiangchen/hypertest-one/releases/download/mcp-v0.2.0/hypertest_one-0.2.0-py3-none-any.whl'
python3.12 - <<'PY'
import hashlib
from pathlib import Path
wheel = Path('hypertest_one-0.2.0-py3-none-any.whl')
raw = wheel.read_bytes()
assert len(raw) == 369859, 'Wheel size mismatch'
assert hashlib.sha256(raw).hexdigest() == 'd7e7bfdbb5a5a25bab343bf695185cc9587c745605c667ba28a9d23d336a6dd3', 'Wheel SHA-256 mismatch'
print('Verified fixed HyperTest wheel')
PY
python3.12 -m venv .venv
.venv/bin/python -m pip install './hypertest_one-0.2.0-py3-none-any.whl[interactive]'
.venv/bin/hypertest-interactive --help
```

The wheel SHA-256 is `d7e7bfdbb5a5a25bab343bf695185cc9587c745605c667ba28a9d23d336a6dd3`. `release-manifest.json` records its
version, source commit, size, supported hosts and profile. `SHA256SUMS` covers the
wheel, manifest and this file. Compare against the independently selected release;
a checksum downloaded from an untrusted location is not independent authorization.

For session management, follow the fixed-source documentation:
https://github.com/ZhangLiangchen/hypertest-one/blob/5c03e4d90bed69b6420238849cbb3a8bae2f4c42/docs/CODEX_SESSION_TASK_SYNC.md
The administrator supplies a private project-scoped task:sync token file; the Agent
never receives an Operator key. Use the bundled session-sync.config.example.json
with private absolute paths and trusted HTTPS. No device pairing, source upload,
execution binding or Runner is required. Run acceptance in the authorized test
environment and reconcile lost write responses by reading the original key.

For legacy controlled execution, use **Create test run → My computer → MCP setup**.
The administrator provides the existing device-management Operator key through a
private owned 0600 file or an interactive secret prompt. Keep it out of Agent chat,
MCP arguments, command arguments, generated client snippets and logs. The local
setup command uses existing operator-authorized pairing and registration APIs;
it is not an MCP tool. It stores narrow device/integration credentials locally
and does not grant source acquisition, issue operations or execution implicitly.

Configure the target host using the generated absolute executable/config paths.
Restart or reload that host when required; do not promise tool-catalog hot reload.
Use the setup doctor's HTTPS/profile and file-permission checks before declaring
installation complete. Preserve existing host MCP entries and private journals.
