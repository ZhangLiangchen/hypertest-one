"""Native workspace grouping in one isolated SDK host, without model calls."""
import json
import time
from pathlib import Path

import yaml
from test_cloud_native_cordis_sdk import _client


def test_real_sdk_groups_framework_root_and_child_in_native_workspace(sdk, fake_provider):
    _, home, private, _ = sdk
    framework = (private / "hypervise_pure").resolve()
    framework.mkdir()
    output = private / "framework-grouping.json"
    sync_plugin = Path(__file__).resolve().parents[1] / "src/hypertest/cloud/harness_workspace_sync.mjs"
    probe = private / "observe-framework-grouping.mjs"
    probe.write_text('''import {writeFileSync} from "node:fs";
export const name = "observe-framework-grouping";
export const inject = ["agents", "tools", "workspaceRegistry", "sessionPersistence", "workingDirectory"];
export function apply(ctx) {
  // The child is genuinely spawned by the native teammate tool. Reject its
  // first step before any provider call; no root prompt is ever submitted.
  ctx.on("agent/pre-step", () => Promise.resolve({kind: "reject"}));
  ctx.on("agent/created", ({agent}) => {
    if (agent.id !== "cloud-synthetic-root") return;
    setTimeout(async () => {
      let result;
      try {
        await ctx.tools.execute({agent, calls: [{name: "spawn_teammate",
          callId: "synthetic-framework-child", arguments: {name: "framework-child",
            description: "isolated grouping probe", prompt: "blocked before provider"}}],
          signal: new AbortController().signal});
        const deadline = Date.now() + 8000;
        while (Date.now() < deadline) {
          const snapshots = await ctx.sessionPersistence.list();
          const child = snapshots.find(({header}) => header.parentSession === agent.id);
          const workspace = await ctx.workspaceRegistry.resolveByPath(process.env.PROBE_FRAMEWORK);
          if (child && workspace?.sessionIds.includes(agent.id) &&
              workspace.sessionIds.includes(child.header.id)) {
            result = {root: {id: agent.id, cwd: agent.session.header.cwd,
                workingDirectory: await ctx.workingDirectory.ensure(agent)},
              child: {id: child.header.id, cwd: child.header.cwd,
                parentSession: child.header.parentSession, origin: child.header.origin},
              workspace: {id: workspace.id, path: workspace.path, title: workspace.title,
                sessionIds: workspace.sessionIds}};
            break;
          }
          await new Promise(resolve => setTimeout(resolve, 50));
        }
        if (!result) throw new Error("Native workspace did not group root and child");
      } catch (error) { result = {error: String(error)}; }
      writeFileSync(process.env.PROBE_OUT, JSON.stringify(result));
    }, 0);
  });
}
''')
    patch = private / "framework-grouping.yml"
    # The SDK base already supplies storage-domain and JSONL persistence. This
    # one synthetic process stands in for the sole native workspace host.
    patch.write_text(yaml.safe_dump([{"insert": [
        {"id": "workspace", "name": "@deepseek-ai/dsh-workspace"},
        {"id": "hypertest-framework-workspaces", "name": str(sync_plugin), "config": {
            "projects": [{"path": str(framework), "title": "hypervise"}], "pollIntervalMs": 1000}},
        {"id": "observe-framework-grouping", "name": str(probe)},
    ]}], sort_keys=False))
    with _client(sdk, fake_provider, (str(patch),),
                 {"PROBE_FRAMEWORK": str(framework), "PROBE_OUT": str(output)}) as client:
        client.initialize(cwd=str(framework), provider="deepseek-official",
                          model="deepseek-flash", reasoning_effort="max")
        assert client.get_working_directory("cloud-synthetic-root") == str(framework)
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert output.exists(), "Native SDK grouping probe did not finish"
        result = json.loads(output.read_text())
        assert "error" not in result, result
        assert result["root"]["cwd"] == result["root"]["workingDirectory"] == str(framework)
        assert result["child"]["cwd"] == str(framework)
        assert result["child"]["parentSession"] == "cloud-synthetic-root"
        assert result["child"]["origin"] == "subagent"
        assert result["workspace"]["path"] == str(framework)
        assert result["workspace"]["title"] == "hypervise"
        expected = {"cloud-synthetic-root", result["child"]["id"]}
        assert set(result["workspace"]["sessionIds"]) == expected
        assert fake_provider.request_count == 0
    stored = json.loads((home / "storages/workspace.json").read_text())
    record = stored["tables"]["workspaces"][result["workspace"]["id"]]
    assert record["path"] == str(framework)
    assert set(record["sessionIds"]) == expected
