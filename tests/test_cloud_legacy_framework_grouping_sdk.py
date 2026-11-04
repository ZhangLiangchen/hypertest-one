"""Original sessions can change native project membership without being opened."""
import hashlib
import json
import time
from pathlib import Path

import yaml
from test_cloud_native_cordis_sdk import _client
from test_cloud_native_cordis_sdk import fake_provider as fake_provider
from test_cloud_native_cordis_sdk import sdk as sdk


def test_legacy_grouping_survives_restart_without_changing_original_sessions(sdk, fake_provider):
    _, home, private, _ = sdk
    old, framework, personal = [(private / name).resolve() for name in ("old-task", "hypervise_pure", "personal")]
    for path in (old, framework, personal):
        path.mkdir()
    output = private / "legacy-grouping.json"
    plugin = Path(__file__).resolve().parents[1] / "src/hypertest/cloud/harness_workspace_sync.mjs"
    probe = private / "legacy-grouping-probe.mjs"
    probe.write_text('''import {writeFileSync} from "node:fs";
export const name = "legacy-grouping-probe";
export const inject = ["tools", "agents", "workspaceRegistry", "sessionPersistence"];
export function apply(ctx) {
  ctx.on("agent/pre-step", () => Promise.resolve({kind:"reject"}));
  async function observe(root) {
    try {
      if (root) {
        await ctx.tools.execute({agent:root,calls:[{name:"spawn_teammate",callId:"legacy-child",
          arguments:{name:"legacy-child",description:"synthetic only",prompt:"blocked before provider"}}],
          signal:new AbortController().signal});
        await ctx.agents.create({sessionId:"personal-original",meta:{cwd:process.env.PROBE_PERSONAL},
          agentOptions:{provider:"deepseek-official",model:"deepseek-flash",reasoningEffort:"max"}});
      }
      const deadline=Date.now()+8000;
      while(Date.now()<deadline) {
        const snapshots=await ctx.sessionPersistence.list();
        const child=snapshots.find(({header})=>header.parentSession==="cloud-synthetic-root");
        const target=await ctx.workspaceRegistry.resolveByPath(process.env.PROBE_TARGET);
        const personal=await ctx.workspaceRegistry.resolveByPath(process.env.PROBE_PERSONAL);
        const prior=await ctx.workspaceRegistry.resolveByPath(process.env.PROBE_OLD);
        if(child && target?.sessionIds.includes("cloud-synthetic-root") &&
           target.sessionIds.includes(child.header.id) && personal?.sessionIds.includes("personal-original")) {
          // Restart first publishes the persisted membership once to refresh
          // native UI subscribers. Observe later polling after it has settled.
          await new Promise(resolve=>setTimeout(resolve,1200));
          const updatedAt=target.updatedAt;
          await new Promise(resolve=>setTimeout(resolve,1200));
          writeFileSync(process.env.PROBE_OUT,JSON.stringify({headers:snapshots.map(({header})=>header),
            target:{id:target.id,sessionIds:target.sessionIds,updatedAt:target.updatedAt},
            prior:prior.sessionIds,personal:personal.sessionIds,unchangedOnRepeat:updatedAt===target.updatedAt}));
          return;
        }
        await new Promise(resolve=>setTimeout(resolve,50));
      }
      const matcher=ctx.workspaceRegistry.host.candidateMatches.toString();
      const workspace=ctx.workspaceRegistry.list()[0];
      throw new Error("grouping timeout "+JSON.stringify({matcher,mutate:workspace?.mutate.toString(),
        detach:workspace?.detachSession.toString()}));
    } catch(error) { writeFileSync(process.env.PROBE_OUT,JSON.stringify({error:String(error)})); }
  }
  if(process.env.PROBE_PHASE==="seed") {
    ctx.on("agent/created",({agent})=>{if(agent.id==="cloud-synthetic-root")setTimeout(()=>observe(agent),0);});
  } else setTimeout(()=>observe(null),0);
}
''')
    projects = [{"path": str(old), "title": "old"}, {"path": str(framework), "title": "hypervise"},
                {"path": str(personal), "title": "personal"}]
    patch = private / "legacy-grouping.yml"

    def run(phase):
        config = {"projects": projects, "pollIntervalMs": 1000}
        if phase != "seed":
            config["legacyMemberships"] = [{"sessionId": "cloud-synthetic-root", "originCwd": str(old),
                                             "projectPath": str(framework)}]
        patch.write_text(yaml.safe_dump([{"insert": [
            {"id": "workspace", "name": "@deepseek-ai/dsh-workspace"},
            {"id": "hypertest-framework-workspaces", "name": str(plugin), "config": config},
            {"id": "legacy-grouping-probe", "name": str(probe)},
        ]}], sort_keys=False))
        output.unlink(missing_ok=True)
        (private / "ready").unlink(missing_ok=True)
        with _client(sdk, fake_provider, (str(patch),), {
            "PROBE_PHASE": phase, "PROBE_OLD": str(old), "PROBE_PERSONAL": str(personal),
            "PROBE_TARGET": str(old if phase == "seed" else framework), "PROBE_OUT": str(output),
        }) as client:
            client.initialize(cwd=str(old), provider="deepseek-official", model="deepseek-flash", reasoning_effort="max")
            if phase == "seed":
                assert client.get_working_directory("cloud-synthetic-root") == str(old)
            deadline = time.monotonic() + 10
            while not output.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert output.exists(), "Native legacy grouping observation timed out"
            result = json.loads(output.read_text())
            assert "error" not in result, result
            assert result["unchangedOnRepeat"]
        return result

    def original_logs():
        return {str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (home / "sessions").rglob("*.jsonl.zstd")}

    before = run("seed")
    logs = original_logs()
    assert len(logs) >= 3
    grouped = run("group")
    assert grouped["headers"] == before["headers"]
    assert set(grouped["target"]["sessionIds"]) == set(before["target"]["sessionIds"])
    assert grouped["prior"] == []
    assert grouped["personal"] == ["personal-original"]
    assert original_logs() == logs
    restarted = run("restart")
    assert restarted["headers"] == before["headers"]
    assert restarted["target"]["sessionIds"] == grouped["target"]["sessionIds"]
    assert restarted["personal"] == grouped["personal"]
    assert original_logs() == logs
    assert fake_provider.request_count == 0
