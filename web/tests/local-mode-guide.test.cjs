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
  assert.equal(helper.LOCAL_RELEASE_STATE, "PUBLISHED");
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

test("the published descriptor pins only the released Mac target and exact accepted host versions", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(helper.LOCAL_PUBLISHED_TARGETS)), [{
    targetId: "darwin-arm64-py313", python: "3.13", releaseTag: "local-v0.1.0",
    sourceCommit: "874569fa566a137eba77ac4852caa6052cb04a17",
    bootstrapSha256: "cd8a2757e3019d6945f697dc1c8db8b650c2744a6e421bae5ba420b7ef25927a",
    manifestSha256: "ba132292c57c740f0409728e3aa23ce93ecde39b5fa40a6d435dad03fb4531da",
    bundleSha256: "e3c7ac8c5966e086c02e3d4b50abc8cd32787bc276d37c271c9949379255979f",
    hosts: {
      "claude-code": { automaticTrigger: "ACCEPTED", versions: ["2.1.218"] },
      codex: { automaticTrigger: "ACCEPTED", versions: ["0.144.6"] },
      "deepseek-harness": { automaticTrigger: "ACCEPTED", versions: ["0.1.5-rc.1"] },
    },
  }]);
});

test("each released host has MCP-only and opt-in Hooks commands with the same immutable release", () => {
  const target = helper.LOCAL_PUBLISHED_TARGETS[0];
  const { hostConfig, ...shared } = base;
  for (const harness of ["codex", "claude-code", "deepseek-harness"]) {
    const deepseek = harness === "deepseek-harness";
    const options = deepseek
      ? { ...shared, harness, dshHome: "/private/deepseek", profile: "qa-local" }
      : { ...base, harness };
    const mcp = helper.buildPublishedLocalCommand(options, target);
    const hooks = helper.buildPublishedLocalCommand(options, target, {
      workspace: "/private/approved/test-workspace", hookConfig: "/private/selected/hooks.json",
      harnessVersion: target.hosts[harness].versions[0],
    });
    for (const command of [mcp, hooks]) {
      for (const value of [target.releaseTag, target.sourceCommit, target.bootstrapSha256, target.manifestSha256, target.bundleSha256]) assert.ok(command.includes(value));
      assert.equal(/--allow-candidate|latest|--operator-key|\.venv-local/.test(command), false);
      if (deepseek) assert.ok(command.includes("--host-config '/private/deepseek/profiles/qa-local/cordis.patch.yml' --dsh-home '/private/deepseek' --profile 'qa-local'"));
    }
    assert.equal(mcp.includes("--enable-hooks"), false);
    assert.ok(hooks.includes(`--harness-version '${target.hosts[harness].versions[0]}'`));
    assert.equal(hooks.includes("--event-bridge native-root"), deepseek);
    assert.equal(hooks.includes("--hook-config '/private/selected/hooks.json'"), !deepseek);
  }
  assert.throws(() => helper.buildPublishedLocalCommand({ ...shared, harness: "deepseek-harness", dshHome: "/private/deepseek", profile: "qa-local", hostConfig: "/private/wrong.yml" }, target), /profile-target/);
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

const updater = { url: "https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/update-local.py", sha256: "e".repeat(64) };
const setupOptions = { projectId, harness: "codex", channel: "candidate" };
test("the shipped updater command pins the exact updater being released", () => {
  const updaterSource = fs.readFileSync(path.join(__dirname, "../../scripts/update-local.py"));
  const digest = require("node:crypto").createHash("sha256").update(updaterSource).digest("hex");
  assert.equal(helper.LOCAL_UPDATER.sha256, digest);
  assert.ok(helper.buildLocalUpdateCommand(setupOptions).includes(digest));
});
const uiHelper = { ...helper,
  buildLocalSetupPrompt: (options) => helper.buildLocalSetupPrompt(options, updater),
  buildLocalUpdateCommand: (options) => helper.buildLocalUpdateCommand(options, updater),
};
const setupComponent = load("app/tasks/source-client-upgrade.tsx", {
  require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/local-mode-install" ? uiHelper : require(name),
});
const cliRelease = load("lib/cli-release.ts", { URL });
const cliInstall = load("lib/cli-install-prompt.ts", { URL, require: (name) => name === "./cli-release" ? cliRelease : require(name) });
const cliInstallComponent = load("app/cli-authorizations/cli-install-prompt.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/cli-install-prompt" ? cliInstall : require(name) });
const component = load("app/projects/[projectId]/local-mode-guide.tsx", {
  require: (name) => name === "@/lib/i18n" ? i18n : name === "@/app/tasks/source-client-upgrade" ? setupComponent : name === "@/app/cli-authorizations/cli-install-prompt" ? cliInstallComponent : require(name),
});

test("one updater command selects a channel and verifies pinned code before release discovery", () => {
  const command = helper.buildLocalUpdateCommand(setupOptions, updater);
  assert.ok(command.startsWith("python3 -I -c "));
  assert.ok(command.includes(updater.url));
  assert.ok(command.includes(updater.sha256));
  assert.ok(command.includes("hashlib.sha256(b).hexdigest()"));
  assert.ok(command.includes("--harness codex --channel candidate"));
  assert.equal(/pip install|upgrade-owned|--enable-hooks|--operator-key|git clone/.test(command), false);
  assert.equal(command.includes("\n"), false, "the updater command is a single shell command");
  assert.ok(helper.buildLocalUpdateCommand({ ...setupOptions, channel: "stable" }, updater).includes("--channel stable"));
  for (const invalid of [{ ...updater, sha256: "" }, { ...updater, url: "https://example.com/update-local.py" }, { ...updater, url: updater.url.replace("local-v0.1.1-rc.2", "latest") }]) {
    assert.throws(() => helper.buildLocalUpdateCommand(setupOptions, invalid), /pinned-updater-required/);
  }
  assert.throws(() => helper.buildLocalUpdateCommand({ ...setupOptions, channel: "nightly" }, updater), /channel/);
  assert.throws(() => helper.buildLocalUpdateCommand({ ...setupOptions, token: "never-accept-a-token" }, updater), /public-context-only/);
});

test("optional legacy paths preserve shell boundaries and are never required for a prompt", () => {
  const command = helper.buildLocalUpdateCommand({ ...setupOptions, directory: "/private/user's $(id) directory", clientConfig: "/private/client.json" }, updater);
  assert.ok(command.includes("--directory '/private/user'\"'\"'s $(id) directory'"));
  assert.ok(command.includes("--client-config '/private/client.json'"));
  assert.throws(() => helper.buildLocalUpdateCommand({ ...setupOptions, directory: "relative/path" }, updater), /absolute-path/);
  for (const locale of ["en", "zh"]) {
    const prompt = helper.buildLocalSetupPrompt({ ...setupOptions, locale }, updater);
    assert.ok(prompt.includes(projectId));
    assert.ok(prompt.includes("--replace-source"));
    assert.ok(prompt.includes("UNKNOWN"));
    assert.ok(prompt.includes("0.144.6"));
    assert.ok(prompt.includes("--skills-directory"));
    assert.equal((prompt.match(/python3 -I -c/g) || []).length, 1);
  }
});

test("the archive project guide is reachable without blocking archive reads", () => {
  const section = load("app/projects/[projectId]/archive-tasks.tsx", { require: (name) =>
    name === "@/lib/task-url" ? load("lib/task-url.ts") : name === "@/lib/i18n" ? i18n : name === "./local-mode-guide" ? component
      : name === "@tanstack/react-query" ? { useQuery: () => ({ data: { items: [], total: 0 }, isLoading: false, isError: false }) }
      : ["@/lib/api", "@/lib/archive"].includes(name) ? {} : name === "@/app/tasks/task-records" ? { ReportedResultTag: () => null }
      : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(section.ProjectArchiveTasks, { projectId, projectDeleted: false })));
  assert.ok(html.includes("CLI installation prompt &amp; archive guide"));
  assert.ok(html.includes('aria-expanded="false"'));
  assert.ok(html.includes("No local archives yet"));
  assert.equal(html.includes("python3 -I -c"), false);
});

test("both languages guide explicit archives and link global CLI authorization without legacy setup", () => {
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.LocalModeGuide, { projectId, initiallyOpen: true })));
    assert.ok(html.includes(projectId)); assert.ok(html.includes(`/cli-authorizations?projectId=${projectId}`));
    assert.ok(html.includes("hypertest-archive"));
    assert.ok(html.includes(locale === "en" ? "Copy installation prompt" : "复制安装 Prompt"));
    assert.ok(html.includes(cliRelease.CLI_RELEASE.artifactSha256));
    for (const text of locale === "en" ? ["Install and authorize the CLI once", "Task root", "Archive after local testing"] : ["安装 CLI 并完成一次授权", "任务根空间", "本地测试结束后归档"]) {
      if (text === "Task root" || text === "任务根空间") continue;
      assert.ok(html.includes(text), text);
    }
    assert.equal(/task:sync|--channel candidate|update-local.py|0\.144\.6|type="password"|name="token"|RELEASE_READY|VERIFIED/.test(html), false);
  }
});
