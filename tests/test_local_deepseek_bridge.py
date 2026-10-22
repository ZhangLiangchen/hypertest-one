"""Contract tests for configuration only; these are not native host acceptance."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hypertest.interactive_client.errors import ClientError
from hypertest.local_sync.deepseek_bridge import (
    BRIDGES,
    SUPPORTED_COMPONENT_VERSION,
    SUPPORTED_VERSION,
    bridge_capability,
    bridge_descriptor,
    root_bridge_descriptor,
)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "install" / "node_modules" / "@deepseek-ai" / "dsh"
    (root / "lib").mkdir(parents=True)
    entry = root / "lib" / "bin.js"
    entry.write_text("// fake CLI fixture: never executed\n")
    (root / "package.json").write_text(json.dumps({
        "name": "@deepseek-ai/dsh", "version": SUPPORTED_VERSION,
    }))
    for package in [*BRIDGES.values(), "@deepseek-ai/dsh-agent", "@deepseek-ai/dsh-llm"]:
        target = root / "node_modules" / package
        (target / "lib").mkdir(parents=True)
        (target / "package.json").write_text(json.dumps({
            "name": package, "version": SUPPORTED_COMPONENT_VERSION,
        }))
        (target / "lib" / "index.js").write_text("// fake bridge fixture\n")
    home = tmp_path / "private-home"
    profile = home / "profiles" / "acceptance"
    profile.mkdir(parents=True)
    (profile / "package.json").write_text(json.dumps({
        "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]}},
    }))
    monkeypatch.setattr("hypertest.local_sync.deepseek_bridge.shutil.which", lambda _: str(entry))
    return root, home, entry


@pytest.mark.parametrize("bridge", ["claude-code", "codex"])
def test_existing_official_bridge_is_configured_without_initializing_profile(installation, bridge):
    root, home, _ = installation
    hooks = home / "local" / "dedicated-hooks.json"
    before = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    row = bridge_descriptor(dsh_home=home, profile="acceptance", hook_config=hooks, bridge=bridge)
    assert row["name"] == BRIDGES[bridge]
    assert row["config"]["configPath"] == str(hooks)
    assert not hooks.exists()
    assert before == {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    capability = bridge_capability(bridge=bridge)
    assert capability["supported_events"] == ["SessionStart", "PostToolUse", "Stop"]
    assert capability["native_hooks"] is False
    assert capability["native_acceptance"] == "NOT_OBSERVED"
    assert capability["package_origin"] == "NOT_VERIFIED_BY_METADATA"
    assert capability["session_end"] == "UNAVAILABLE"
    assert len(capability["bridge_entry_sha256"]) == 64


@pytest.mark.parametrize("version", ["0.1.4", "0.2.1rc2", "0.1.5", None])
def test_unknown_cli_or_sdk_version_cannot_enable_automatic_bridge(installation, version):
    root, _, _ = installation
    (root / "package.json").write_text(json.dumps({"name": "@deepseek-ai/dsh", "version": version}))
    with pytest.raises(ClientError, match="DEEPSEEK_BRIDGE_VERSION_UNSUPPORTED"):
        bridge_capability()


def test_bridge_and_cli_versions_must_match(installation):
    root, _, _ = installation
    (root / "node_modules" / BRIDGES["claude-code"] / "package.json").write_text(json.dumps({
        "name": BRIDGES["claude-code"], "version": "0.2.0",
    }))
    with pytest.raises(ClientError, match="DEEPSEEK_BRIDGE_VERSION_UNSUPPORTED"):
        bridge_capability()


@pytest.mark.parametrize("profile", ["../web", "", "a/b", "..", "x y"])
def test_profile_path_cannot_escape_explicit_home(installation, profile):
    _, home, _ = installation
    with pytest.raises(ClientError, match="DEEPSEEK_HOME_PROFILE_REQUIRED"):
        bridge_descriptor(dsh_home=home, profile=profile, hook_config=home / "hooks.json")


@pytest.mark.parametrize("metadata", [{}, {"dsh": "bad"}, {"dsh": {"profile": "bad"}},
                                        {"dsh": {"profile": {"bundles": []}}}])
def test_no_profile_reconstruction_or_inferred_default(installation, metadata):
    _, home, _ = installation
    profile = home / "profiles" / "acceptance" / "package.json"
    profile.write_text(json.dumps(metadata))
    with pytest.raises(ClientError, match="DEEPSEEK_EXISTING_PROFILE_REQUIRED"):
        bridge_descriptor(dsh_home=home, profile="acceptance", hook_config=home / "hooks.json")


def test_installer_cannot_point_hook_config_at_profile_source(installation):
    _, home, _ = installation
    with pytest.raises(ClientError, match="DEEPSEEK_DEDICATED_HOOK_CONFIG_REQUIRED"):
        bridge_descriptor(dsh_home=home, profile="acceptance",
                          hook_config=home / "profiles" / "acceptance" / "cordis.patch.yml")


def test_symlinked_profile_is_not_silently_modified(installation):
    _, home, _ = installation
    (home / "profiles" / "linked").symlink_to(home / "profiles" / "acceptance", target_is_directory=True)
    with pytest.raises(ClientError, match="DEEPSEEK_EXISTING_PROFILE_REQUIRED"):
        bridge_descriptor(dsh_home=home, profile="linked", hook_config=home / "hooks.json")


def test_absent_cli_does_not_probe_auth_or_start_npm(monkeypatch):
    monkeypatch.setattr("hypertest.local_sync.deepseek_bridge.shutil.which", lambda _: None)
    with pytest.raises(ClientError, match="DEEPSEEK_EXECUTABLE_NOT_FOUND"):
        bridge_capability()


def test_missing_bridge_entry_cannot_be_reported_as_configured(installation):
    root, _, _ = installation
    (root / "node_modules" / BRIDGES["claude-code"] / "lib" / "index.js").unlink()
    with pytest.raises(ClientError, match="DEEPSEEK_BRIDGE_ENTRY_MISSING"):
        bridge_capability()


def test_unrelated_executable_cannot_impersonate_supported_layout(installation):
    _, home, _ = installation
    other = home / "dsh"
    other.write_text("not a published npm layout")
    with pytest.raises(ClientError, match="DEEPSEEK_INSTALL_LAYOUT_UNSUPPORTED"):
        bridge_capability(executable=other)


def test_root_adapter_uses_pinned_asset_and_fixed_private_handler(installation):
    _, home, entry = installation
    command = ["/private/python", "-I", "-m", "hypertest.local_sync", "hook", "--config", "/private/client.json"]
    row = root_bridge_descriptor(dsh_home=home, profile="acceptance", handler_command=command,
                                 workspace=home / "workspace", executable=entry)
    assert row["name"].endswith("/deepseek_root_bridge.mjs")
    assert row["config"]["handlerCommand"] == command
    assert row["config"]["workspace"] == str(home / "workspace")
    assert row["config"]["harnessVersion"] == SUPPORTED_VERSION
    assert len(row["config"]["adapterSha256"]) == 64


@pytest.mark.parametrize("command", [
    ["/bin/sh", "-c", "echo arbitrary"],
    ["python", "-I", "-m", "hypertest.local_sync", "hook", "--config", "/private/client.json"],
    ["/private/python", "-I", "-m", "arbitrary", "hook", "--config", "/private/client.json"],
    ["/private/python", "-I", "-m", "hypertest.local_sync", "hook", "--config", "relative.json"],
    ["/private/python", "-m", "hypertest.local_sync", "hook", "--config", "/private/client.json"],
])
def test_root_adapter_cannot_be_repurposed_as_arbitrary_shell(installation, command):
    _, home, _ = installation
    with pytest.raises(ClientError, match="DEEPSEEK_FIXED_HOOK_HANDLER_REQUIRED"):
        root_bridge_descriptor(dsh_home=home, profile="acceptance", handler_command=command,
                               workspace=home / "workspace")


def test_root_registry_must_have_the_same_supported_version(installation):
    root, home, _ = installation
    package = root / "node_modules" / "@deepseek-ai" / "dsh-agent" / "package.json"
    package.write_text(json.dumps({"name": "@deepseek-ai/dsh-agent", "version": "0.2.1-rc.2"}))
    with pytest.raises(ClientError, match="DEEPSEEK_ROOT_REGISTRY_VERSION_UNSUPPORTED"):
        root_bridge_descriptor(dsh_home=home, profile="acceptance",
            handler_command=["/python", "-I", "-m", "hypertest.local_sync", "hook", "--config", "/client.json"],
            workspace=home / "workspace")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for the native adapter contract")
def test_native_root_adapter_filters_children_and_never_passes_raw_tool_payloads(tmp_path):
    """Fake registry exercises the guard; real-host acceptance is separate."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log = workspace / "observations.jsonl"
    helper = tmp_path / "fixed-python"
    helper.write_text("#!" + sys.executable + "\n" + (
        "import json,sys\n"
        "from pathlib import Path\n"
        "event=json.load(sys.stdin)\n"
        f"with Path({str(log)!r}).open('a') as stream: stream.write(json.dumps(event)+'\\n')\n"
        "if event['hook_event_name']=='SessionStart':\n"
        " print(json.dumps({'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':'approved paths only'}}))\n"
    ))
    helper.chmod(0o700)
    llm = tmp_path / "llm.mjs"
    llm.write_text("export function createUserMessage(value) { return {id:'context-fixture', ...value}; }\n")
    asset = Path(__file__).parents[1] / "src/hypertest/local_sync/deepseek_root_bridge.mjs"
    script = tmp_path / "probe.mjs"
    script.write_text("""
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {apply}=await import(pathToFileURL(ASSET).href);
const handlers={}, warnings=[];
const root={id:'real-root',session:{header:{id:'real-root',cwd:WORKSPACE}}};
const child={id:'child',session:{header:{id:'child',cwd:WORKSPACE,parentSession:'real-root',origin:'subagent'}}};
let roots=[root], current=new Map([[root.id,root],[child.id,child]]);
const ctx={agents:{roots:()=>roots,get:id=>current.get(id)},logger:{warn:value=>warnings.push(value)},
 on:(event,fn)=>{handlers[event]=fn;},effect:()=>{}};
await apply(ctx,{handlerCommand:[HANDLER,'-I','-m','hypertest.local_sync','hook','--config',CONFIG],
 workspace:WORKSPACE,createMessageModule:LLM});
handlers['agent/session-start']({agent:root});
handlers['agent/session-start']({agent:child});
const enter=()=>Promise.resolve({kind:'enter',messages:[]});
const first=await handlers['agent/pre-step']({agent:root,messages:[{id:'user-fixture'}]},enter);
assert.equal(first.messages.length,1);
assert.equal(first.messages[0].content[0].text,'approved paths only');
const again=await handlers['agent/pre-step']({agent:root,messages:[{id:'user-fixture'}]},enter);
assert.equal(again.messages.length,0);
await handlers['tools/post-execute']({agent:root,name:'write',arguments:{secret:'NEVER_FORWARD'}},
 {content:[{text:'RAW_TOOL_OUTPUT'}]},()=>Promise.resolve({kind:'accept'}));
await handlers['tools/post-execute']({agent:child,name:'write'}, {},()=>Promise.resolve({kind:'accept'}));
await handlers['agent/turn-stopping']({agent:root});
await handlers['agent/turn-stopping']({agent:child});
// Even an externally resumed child listed as a runtime root is not auto-bound.
roots=[child];
handlers['agent/session-start']({agent:child});
await handlers['agent/pre-step']({agent:child,messages:[{id:'user-fixture'}]},enter);
// Same ID in the registry is insufficient: exact live object identity is required.
roots=[root];current.set(root.id,{...root});
handlers['agent/session-start']({agent:root});
const text=await readFile(LOG,'utf8');
assert.ok(!text.includes('NEVER_FORWARD')&&!text.includes('RAW_TOOL_OUTPUT'));
const rows=text.trim().split('\\n').map(JSON.parse);
assert.deepEqual(rows.map(row=>row.hook_event_name),['SessionStart','PostToolUse','Stop']);
assert.ok(rows.every(row=>row.session_id==='real-root'));
assert.ok(rows.every(row=>Object.keys(row).every(key=>['session_id','hook_event_name','cwd','tool_name'].includes(key))));
assert.equal(warnings.length,0);
console.log('native adapter contract passed');
""".replace("ASSET", json.dumps(str(asset))).replace("WORKSPACE", json.dumps(str(workspace)))
        .replace("HANDLER", json.dumps(str(helper))).replace("CONFIG", json.dumps(str(tmp_path / "config.json")))
        .replace("LLM", json.dumps(str(llm))).replace("LOG", json.dumps(str(log))))
    result = subprocess.run([shutil.which("node"), str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "native adapter contract passed"
