const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const helper = load("lib/local-mode-install.ts");
const i18n = load("lib/i18n.tsx", { require });
const { buildLocalModeCommands, localManifestTemplate, localConfigTemplate } = helper;
const projectId = "01a15807-6162-7759-a0cf-614d34f977af";
const base = { projectId, harness: "codex", directory: "/private/local/install", clientConfig: "/private/local/client.json", hostConfig: "/private/codex/config.toml" };

test("candidate commands use the implemented Local CLI without secrets, implicit Hooks or legacy setup", () => {
  const commands = buildLocalModeCommands(base);
  assert.equal(helper.LOCAL_RELEASE_STATE, "UNPUBLISHED_SOURCE_CANDIDATE");
  assert.ok(commands.prepare.includes("-e '.[interactive]'"));
  assert.ok(commands.install.includes("-m hypertest.local_sync install"));
  assert.ok(commands.install.includes(`--version ${helper.LOCAL_CANDIDATE_VERSION}`));
  assert.ok(commands.install.includes("--client-config '/private/local/client.json'"));
  assert.ok(commands.doctor.includes("-m hypertest.local_sync doctor"));
  assert.ok(commands.submit.includes("-m hypertest.local_sync submit-manifest --config"));
  assert.ok(commands.daemon.includes("-m hypertest.interactive_client daemon --config"));
  for (const command of Object.values(commands)) {
    assert.equal(/--enable-hooks|--operator-key|\bsetup\b|mcp-v0\.1\.0|curl|https:\/\/.*download|latest|git clone/.test(command), false);
  }
  assert.equal(commands.submit.includes("--manifest"), false, "the selected private config owns the manifest path");
});

test("each host is explicit and DeepSeek uses only an existing selected home/profile", () => {
  assert.ok(buildLocalModeCommands({ ...base, harness: "claude-code", hostConfig: "/private/claude/.mcp.json" }).install.includes("--harness claude-code"));
  const { hostConfig, ...shared } = base;
  const commands = buildLocalModeCommands({ ...shared, harness: "deepseek-harness", dshHome: "/private/deepseek", profile: "qa-local" });
  assert.ok(commands.install.includes("--host-config '/private/deepseek/profiles/qa-local/cordis.patch.yml'"));
  assert.ok(commands.install.includes("--dsh-home '/private/deepseek' --profile 'qa-local'"));
  for (const profile of ["../other", "qa;whoami", "qa\nprofile", ""]) {
    assert.throws(() => buildLocalModeCommands({ ...shared, harness: "deepseek-harness", dshHome: "/private/deepseek", profile }), /profile/);
  }
  assert.throws(() => buildLocalModeCommands({ ...base, harness: "deepseek-harness", dshHome: "/private/deepseek", profile: "qa" }), /profile-target/);
  assert.throws(() => buildLocalModeCommands({ ...base, harness: "all" }), /harness/);
});

test("public setup context rejects credential values, malformed identities and unsafe path framing", () => {
  for (const key of ["token", "integrationToken", "operatorKey", "apiUrl", "releaseUrl"]) {
    assert.throws(() => buildLocalModeCommands({ ...base, [key]: "do-not-copy-a-secret" }), /public-context-only/);
  }
  for (const project of ["not-a-project", `${projectId}\nrun this`, `${projectId};id`]) {
    assert.throws(() => buildLocalModeCommands({ ...base, projectId: project }), /project-id/);
  }
  for (const directory of ["relative/path", "/", "/tmp/line\nbreak", "/tmp/with\0null", " /tmp/private"]) {
    assert.throws(() => buildLocalModeCommands({ ...base, directory }));
  }
  assert.throws(() => buildLocalModeCommands({ ...base, hostConfig: base.clientConfig }), /distinct-private-paths/);
  const unusual = "/private/user's $(id) `whoami` directory";
  const commands = buildLocalModeCommands({ ...base, directory: unusual });
  assert.ok(commands.install.includes("--directory '/private/user'\"'\"'s $(id) `whoami` directory'"), "shell syntax stays inside a single quoted argument");
});

test("templates bind the selected Project and provider but cannot fabricate a real session or result", () => {
  for (const [harness, provider] of [["codex", "codex"], ["claude-code", "claude_code"], ["deepseek-harness", "deepseek_harness"]]) {
    const manifest = JSON.parse(localManifestTemplate(projectId, harness));
    const config = JSON.parse(localConfigTemplate(projectId, harness)).local_sync;
    assert.equal(manifest.identity.project_id, projectId);
    assert.equal(manifest.identity.provider, provider);
    assert.match(manifest.identity.parent_session_id, /^<ACTUAL_PARENT_SESSION/);
    assert.equal(typeof manifest.base_version, "string", "version placeholder must be replaced before submission");
    assert.equal(manifest.set.reported_result, "NOT_RUN");
    assert.equal(manifest.set.status, "IN_PROGRESS");
    assert.match(manifest.artifacts[0].sha256, /^<SHA256_/);
    assert.equal(config.hooks_enabled, false);
    assert.equal(config.host, harness);
    assert.equal(config.project_id, projectId);
    assert.deepEqual(config.allowed_roots, ["/absolute/private/approved-artifacts"]);
  }
});

const published = { targetId: "darwin-arm64-py313", python: "3.13", releaseTag: "local-v0.1.0", sourceCommit: "a".repeat(40),
  bootstrapSha256: "b".repeat(64), manifestSha256: "c".repeat(64), bundleSha256: "d".repeat(64),
  hosts: { codex: { automaticTrigger: "ACCEPTED", versions: ["0.9.0"] } } };

test("published commands verify fixed bootstrap and platform payload digests before installing", () => {
  assert.equal(helper.LOCAL_PUBLISHED_TARGETS.length, 0, "no nonexistent public release is asserted");
  const command = helper.buildPublishedLocalCommand(base, published);
  assert.ok(command.startsWith("python3.13 -I -c "));
  for (const value of [published.releaseTag, published.sourceCommit, published.bootstrapSha256, published.manifestSha256, published.bundleSha256]) assert.ok(command.includes(value));
  assert.ok(command.includes("hypertest-local-v0.1.0-darwin-arm64-py313.zip"));
  assert.equal(/latest|curl|--allow-candidate|--enable-hooks|--operator-key/.test(command), false);
  for (const target of [{ ...published, releaseTag: "latest" }, { ...published, bootstrapSha256: "" },
    { ...published, targetId: "darwin-arm64-py312" }, { ...published, python: "3.14" }]) {
    assert.throws(() => helper.buildPublishedLocalCommand(base, target), /fixed-published-release/);
  }
});

test("automatic published commands require accepted exact versions and an explicit workspace policy", () => {
  const policy = { workspace: "/private/approved/test-workspace", hookConfig: "/private/codex/hooks.json", harnessVersion: "0.9.0" };
  const command = helper.buildPublishedLocalCommand(base, published, policy);
  assert.ok(command.includes("--enable-hooks --workspace '/private/approved/test-workspace' --harness-version '0.9.0'"));
  assert.ok(command.includes("--hook-config '/private/codex/hooks.json'"));
  assert.throws(() => helper.buildPublishedLocalCommand(base, published, { ...policy, harnessVersion: "0.9.1" }), /accepted-hooks-required/);
  assert.throws(() => helper.buildPublishedLocalCommand(base, published, { ...policy, workspace: "relative" }), /absolute-path/);
  assert.throws(() => helper.buildPublishedLocalCommand({ ...base, harness: "claude-code" }, published, policy), /accepted-hooks-required/);
});

const component = load("app/projects/[projectId]/local-mode-guide.tsx", {
  require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/local-mode-install" ? helper : require(name),
});

test("the project guide is reachable without blocking existing task reads", () => {
  const section = load("app/projects/[projectId]/session-tasks.tsx", { require: (name) =>
    name === "@/lib/i18n" ? i18n
      : name === "./local-mode-guide" ? component
      : name === "@tanstack/react-query" ? { useQuery: () => ({ data: { items: [], total: 0 }, isLoading: false, isError: false }) }
      : name === "@/lib/api" ? {}
      : name === "@/app/tasks/task-records" ? { ReportedResultTag: () => null }
      : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) }
      : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(section.ProjectSessionTasks, { projectId })));
  assert.ok(html.includes("Set up local mode"));
  assert.ok(html.includes('aria-expanded="false"'));
  assert.ok(html.includes("No Codex tasks"));
  assert.equal(html.includes("local_sync install"), false, "an unopened guide runs no setup");
});

test("both languages disclose release, authorization and acceptance gaps without claiming sync or readiness", () => {
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.LocalModeGuide, { projectId, initiallyOpen: true })));
    for (const text of ["Codex", "Claude Code", "DeepSeek harness", projectId, "task:sync", "hypertest_get_task", "hypertest_sync_task", "NOT_RUN", "NOT_FOUND"]) assert.ok(html.includes(text), text);
    for (const text of locale === "en" ? ["Local release is not published", "Hooks disabled", "Waiting for existing Project authorization", "Native session not verified", "cannot be submitted as shown"] : ["Local 发行尚未发布", "Hooks 默认关闭", "等待已有项目授权", "真实宿主会话未验收", "不能直接提交"]) assert.ok(html.includes(text), text);
    assert.equal(html.includes("local_sync install"), false, "no commands before private paths and authorization are acknowledged");
    assert.equal(/type="password"|name="token"|READY|RELEASE_READY|VERIFIED/.test(html), false);
  }
  const source = fs.readFileSync(path.join(__dirname, "..", "app/projects/[projectId]/local-mode-guide.tsx"), "utf8");
  assert.equal(/fetch\(|useMutation|localStorage|sessionStorage|dangerouslySetInnerHTML/.test(source), false);
});
