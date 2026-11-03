"""Pinned native SDK admission checks, with a loopback-only fake provider."""
import hashlib
import http.server
import json
import os
import threading
import time
from pathlib import Path

import pytest

from hypertest.cloud import native_cordis


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    harness = pytest.importorskip("deepseek_harness")
    runtime = pytest.importorskip("deepseek_harness_runtime")
    binary = Path(runtime.resolve_bundled_launch_args()[0])
    with binary.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != native_cordis._RUNTIME_SHA256:
            pytest.skip("the audited native SDK runtime is not installed")
    # The SDK merges env into its parent environment; remove all real secrets.
    monkeypatch.setattr(os, "environ", {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8"})
    home = tmp_path / "dsh"
    profile = home / "profiles" / "sdk"
    profile.mkdir(parents=True)
    bundles = [
        "@deepseek-ai/dsh-base", "@deepseek-ai/dsh-sdk-app",
        "@deepseek-ai/dsh-experimental-agent-team-profile",
        "@deepseek-ai/dsh-experimental-tool-worktree",
        "@deepseek-ai/dsh-experimental-terminal-bundle",
        "@deepseek-ai/dsh-experimental-session-search",
        "@deepseek-ai/dsh-experimental-session-titles-bundle",
        "@deepseek-ai/dsh-experimental-ralph-bundle",
    ]
    (profile / "package.json").write_text(json.dumps({"name": "dsh-profile-sdk", "private": True, "dependencies": {}, "dsh": {"profile": {"bundles": bundles}}}))
    (profile / "cordis.patch.yml").write_text("[]\n")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    overlay = native_cordis.prepare_cordis_overlay(private)
    return harness, home, private, overlay


class _FakeProvider(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.request_count += 1
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"synthetic"}')

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_provider():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeProvider)
    server.request_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _client(sdk, server, extra_patches=(), extra_env=None):
    harness, home, private, overlay = sdk
    env = {"DSH_SDK_CORDIS_ROOT": "cloud-synthetic-root", "DSH_SDK_CORDIS_NONCE": "a" * 64,
           "DSH_SDK_CORDIS_HANDSHAKE": str(private / "ready"), "DEEPSEEK_API_KEY": "synthetic-invalid-key",
           "DEEPSEEK_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}
    env.update(extra_env or {})
    config = harness.HarnessConfig(profile="sdk", dsh_home=str(home), cwd=str(private),
                                   patches=(str(overlay), *extra_patches), env=env, request_timeout_seconds=10)
    return harness.HarnessClient(config)


def _initialize(client, sdk):
    client.initialize(cwd=str(sdk[2]), provider="deepseek-official", model="deepseek-flash", reasoning_effort="max")


def test_real_sdk_rejects_failed_root_selection_before_provider(sdk, fake_provider):
    hook = sdk[2] / "hypertest-cordis-root.mjs"
    hook.write_text(hook.read_text().replace('await ctx.agentPresets.select(agent, "cordis");',
                                             'throw new Error("SYNTHETIC_SELECT_FAILURE");'))
    with _client(sdk, fake_provider) as client:
        _initialize(client, sdk)
        assert json.loads((sdk[2] / "ready").read_text()) == {
            "phase": "registered", "nonce": "a" * 64, "root": "cloud-synthetic-root"}
        with pytest.raises(Exception, match="SYNTHETIC_SELECT_FAILURE"):
            client.session_prompt("cloud-synthetic-root", [{"type": "text", "text": "synthetic"}])
        assert fake_provider.request_count == 0


def test_real_sdk_accepted_root_reaches_only_fake_provider(sdk, fake_provider):
    with _client(sdk, fake_provider) as client:
        _initialize(client, sdk)
        client.session_prompt("cloud-synthetic-root", [{"type": "text", "text": "synthetic"}])
        deadline = time.monotonic() + 8
        while fake_provider.request_count == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert fake_provider.request_count > 0


def test_real_sdk_missing_listener_does_not_issue_registration(sdk, fake_provider):
    disable = sdk[2] / "disable-listener.yml"
    disable.write_text("- id: hypertest-cordis-root\n  disabled: true\n")
    with _client(sdk, fake_provider, (str(disable),)) as client:
        _initialize(client, sdk)
        assert not (sdk[2] / "ready").exists()
        assert fake_provider.request_count == 0


def test_real_sdk_root_and_spawned_child_inherit_cordis(sdk, fake_provider):
    private = sdk[2]
    # This probe observes the child during creation and aborts before any child
    # prompt is enqueued.  The root selector must not run on the child.
    probe = private / "observe-child.mjs"
    probe.write_text('''import {writeFileSync} from "node:fs";
export const name="observe-child";
export const inject=["agents","tools","agentPresets","sessionProjections"];
export function apply(ctx) {
  let child = null;
  ctx.on("agent/created", async ({agent}) => {
    if (agent.id === "cloud-synthetic-root") return;
    child = {preset:ctx.agentPresets.composedPreset(agent.ctx) ?? null,
      projection:ctx.sessionProjections.stateOf(agent.session,"agentPreset") ?? null,
      tools:ctx.tools.schemas(agent).map(x => x.name)};
    throw new Error("STOP_BEFORE_CHILD_PROMPT");
  });
  setTimeout(async () => {
    let result = {};
    try {
      const h = await ctx.agents.create({sessionId:"cloud-synthetic-root",
        meta:{cwd:process.env.PROBE_CWD},
        agentOptions:{provider:"deepseek-official",model:"deepseek-flash",reasoningEffort:"max"}});
      const agent = h.agent ?? h;
      result.root = {preset:ctx.agentPresets.composedPreset(agent.ctx),
        projection:ctx.sessionProjections.stateOf(agent.session,"agentPreset"),
        tools:ctx.tools.schemas(agent).map(x => x.name)};
      try {
        await ctx.tools.execute({agent,calls:[{name:"spawn_teammate",callId:"synthetic-spawn",
          arguments:{name:"synthetic-child",description:"isolated",prompt:"never submitted"}}],
          signal:new AbortController().signal});
      } catch (error) { result.spawnError = String(error); }
      result.child = child;
    } catch (error) { result.error = String(error); }
    writeFileSync(process.env.PROBE_OUT, JSON.stringify(result));
  }, 200);
}
''')
    patch = private / "observe-child.yml"
    patch.write_text("- insert:\n    - id: observe-child\n      name: " + json.dumps(str(probe)) + "\n")
    audit = private / "root-selections"
    hook = private / "hypertest-cordis-root.mjs"
    hook.write_text(hook.read_text().replace(
        'await ctx.agentPresets.select(agent, "cordis");',
        'writeFileSync(process.env.PROBE_AUDIT, agent.id + "\\n", {flag:"a"});\n    await ctx.agentPresets.select(agent, "cordis");'))
    out = private / "result.json"
    with _client(sdk, fake_provider, (str(patch),),
                 {"PROBE_CWD": str(private), "PROBE_OUT": str(out), "PROBE_AUDIT": str(audit)}) as client:
        _initialize(client, sdk)
        deadline = time.monotonic() + 10
        while not out.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert out.exists(), "SDK child probe did not finish"
        result = json.loads(out.read_text())
        assert "error" not in result, result
        assert result["root"]["preset"] == result["root"]["projection"] == "cordis"
        assert result["child"]["preset"] == result["child"]["projection"] == "cordis"
        assert {"bash", "read", "write", "grep", "glob", "web_search", "skill"}.issubset(result["child"]["tools"])
        assert {"spawn_teammate", "create_worktree", "terminal_open", "session_search", "ralph"}.issubset(result["root"]["tools"])
        assert audit.read_text().splitlines() == ["cloud-synthetic-root"]
        assert fake_provider.request_count == 0
