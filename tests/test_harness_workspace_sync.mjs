import assert from "node:assert/strict";
import {mkdtemp, mkdir, realpath, rm, symlink, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {apply, frameworkProjects, legacyGrouping, legacyMemberships, syncFrameworkWorkspaces} from "../src/hypertest/cloud/harness_workspace_sync.mjs";

async function fixture(t) {
  const root = await realpath(await mkdtemp(join(tmpdir(), "framework-grouping-")));
  t.after(() => rm(root, {recursive: true, force: true}));
  const path = join(root, "hypervise_pure");
  await mkdir(path);
  return {root, path};
}

function host(headers) {
  const calls = {listed: 0, attached: [], created: [], warnings: []};
  const workspace = {
    title: "user-owned title", sessionIds: ["existing"],
    async attachSession(id) { calls.attached.push(id); this.sessionIds.push(id); },
  };
  const ctx = {
    sessionPersistence: {async list() { calls.listed++; return headers.map(header => ({header})); }},
    workspaceRegistry: {async create(path, title) { calls.created.push({path, title}); return workspace; }},
    logger: {warn(message) { calls.warnings.push(message); }},
    effect(effect) { ctx.dispose = effect(); },
  };
  return {ctx, calls, workspace};
}

test("groups matching roots and children without touching unrelated or historical origins", async t => {
  const {path} = await fixture(t);
  const projects = await frameworkProjects({projects: [{path, title: "hypervise"}]});
  const {ctx, calls, workspace} = host([
    {id: "existing", cwd: path}, {id: "cloud-root", cwd: path},
    {id: "child", cwd: path, parentId: "cloud-root"},
    {id: "old", cwd: path + "/old-attempt"}, {id: "other", cwd: "/another/project"},
    {id: "missing-origin"},
  ]);
  const signal = new AbortController().signal;
  await syncFrameworkWorkspaces(ctx, projects, signal);
  await syncFrameworkWorkspaces(ctx, projects, signal);
  assert.deepEqual(calls.attached, ["cloud-root", "child"]);
  assert.equal(workspace.title, "user-owned title");
  assert.equal(calls.listed, 2);
});

test("rejects ambiguous, nonexistent and symlink project paths", async t => {
  const {root, path} = await fixture(t);
  await symlink(path, join(root, "alias"));
  for (const projects of [
    [{path: "relative", title: "hypervise"}],
    [{path: join(root, "missing"), title: "hypervise"}],
    [{path: join(root, "alias"), title: "hypervise"}],
    [{path, title: "one"}, {path, title: "two"}],
  ]) await assert.rejects(frameworkProjects({projects}));
});

test("discovers only immediate managed project records and notices newly prepared projects", async t => {
  const {root} = await fixture(t);
  const managedRoot = join(root, "framework-projects");
  assert.deepEqual(await frameworkProjects({managedRoot}), []);
  const directory = join(managedRoot, "a".repeat(64));
  const path = join(directory, "hypervise_pure");
  await mkdir(path, {recursive: true});
  await writeFile(join(directory, "project.json"), JSON.stringify({
    profile: "hypertest-framework-project/v1", repository: "https://example.test/hypervise_pure",
    path, title: "hypervise",
  }));
  await mkdir(join(managedRoot, "unrelated"));
  await writeFile(join(managedRoot, "unrelated", "project.json"), "not a managed record");
  assert.deepEqual(await frameworkProjects({managedRoot}), [{path, title: "hypervise"}]);
  await writeFile(join(directory, "project.json"), JSON.stringify({
    profile: "hypertest-framework-project/v1", path: root, title: "outside",
  }));
  await assert.rejects(frameworkProjects({managedRoot}));
});

test("initial host sync has lifecycle cleanup and never logs exception contents", async t => {
  const {path} = await fixture(t);
  const {ctx, calls} = host([]);
  ctx.sessionPersistence.list = async () => { throw new Error("private error payload"); };
  await apply(ctx, {projects: [{path, title: "hypervise"}]});
  await ctx.dispose();
  assert.deepEqual(calls.warnings, ["HyperTest framework grouping will retry"]);
  assert.deepEqual(calls.created, []);
});

test("disposing aborts pending header reads before registry changes", async t => {
  const {path} = await fixture(t);
  const {ctx, calls} = host([]);
  let entered;
  const started = new Promise(resolve => { entered = resolve; });
  ctx.sessionPersistence.list = ({signal}) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), {once: true});
    entered();
  });
  const applying = apply(ctx, {projects: [{path, title: "hypervise"}]});
  await started;
  await ctx.dispose();
  await applying;
  assert.deepEqual(calls.created, []);
  assert.deepEqual(calls.warnings, []);
});


test("legacy membership follows native parents and leaves original headers and personal sessions alone", async t => {
  const {path} = await fixture(t);
  const headers = [{id: "cloud-old", cwd: "/old/attempt/workspace"},
    {id: "native-child", cwd: "/old/attempt/workspace", parentSession: "cloud-old"},
    {id: "nested-child", cwd: "/old/worktree", parentSession: "native-child"},
    {id: "personal", cwd: "/personal/repo"}];
  const before = JSON.stringify(headers);
  const members = legacyMemberships([{sessionId: "cloud-old", originCwd: headers[0].cwd, projectPath: path}],
    [{path, title: "hypervise"}], headers.map(header => ({header})));
  assert.deepEqual([...members.keys()], ["cloud-old", "native-child", "nested-child"]);
  assert.equal(members.get("nested-child").projectPath, path);
  assert.equal(JSON.stringify(headers), before);
});

test("legacy membership rejects wrong original cwd, absent IDs, unknown projects and duplicate bindings", async t => {
  const {path} = await fixture(t);
  const row = {sessionId: "cloud-old", originCwd: "/old/workspace", projectPath: path};
  const headers = [{header: {id: row.sessionId, cwd: row.originCwd}}];
  for (const configured of [[{...row, originCwd: "/wrong"}], [{...row, sessionId: "absent"}],
    [{...row, projectPath: "/other/project"}], [row, row]]) {
    assert.throws(() => legacyMemberships(configured, [{path, title: "hypervise"}], headers));
  }
});

test("legacy membership refuses an unreviewed native matcher before registry writes", async t => {
  const {path} = await fixture(t);
  const {ctx, calls} = host([]);
  ctx.workspaceRegistry.host = {candidateMatches: () => true};
  const legacy = legacyGrouping(ctx, [{sessionId: "cloud-old", originCwd: "/old/workspace", projectPath: path}]);
  await assert.rejects(legacy.sync([{path, title: "hypervise"}],
    [{header: {id: "cloud-old", cwd: "/old/workspace"}}], new AbortController().signal), /Unsupported/);
  assert.equal(calls.created.length, 0);
  assert.equal(ctx.workspaceRegistry.host.candidateMatches(), true);
});
