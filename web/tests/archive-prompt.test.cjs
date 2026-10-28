const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const archive = load("lib/archive.ts", { URL, require: () => ({ ApiError: Error }) });
const i18n = load("lib/i18n.tsx", { require });
const { ArchivePrompt } = load("app/archives/archive-prompt.tsx", { require: (name) => name === "@/lib/archive" ? archive : name === "@/lib/i18n" ? i18n : require(name) });
const p = "00000000-0000-4000-8000-000000000001", task = "00000000-0000-4000-8000-000000000002";
test("archive templates bind exact targets and delegate bounded artifact and connection resolution", () => {
  for (const en of [false, true]) {
    const prompt = archive.archiveSkillInstruction(p, task, undefined, en, "https://archive.example:8080");
    assert.ok(prompt.startsWith("$hypertest-archive"));
    assert.ok(prompt.includes(`Project ID: ${p}`)); assert.ok(prompt.includes(`Task ID: ${task}`));
    assert.ok(prompt.includes("https://archive.example:8080"));
    assert.ok(prompt.includes("SSL_CERT_FILE")); assert.ok(prompt.includes("journal"));
    assert.ok(prompt.includes("hypertest profile show --json"));
    assert.ok(prompt.includes(en ? "without another confirmation" : "无需再次确认"));
    assert.ok(prompt.includes(en ? "do not scan the home directory" : "不扫描整个用户目录"));
    assert.ok(prompt.includes(en ? "otherwise ask which one" : "否则仅询问选择哪一个"));
    assert.equal(/<[^>]+>/.test(prompt), false);
    assert.ok(prompt.includes(en ? "original request ID/key" : "原请求 ID/key"));
    assert.equal(prompt.includes("Subtask ID:"), false);
    assert.equal(prompt.includes("/Users/zhangliangchen"), false);
    assert.equal(prompt.includes("profile default"), false);
    const child = archive.archiveSkillInstruction(p, task, p, en);
    assert.ok(child.includes(`Subtask ID: ${p}`));
    const preview = archive.archiveSkillInstruction(p, undefined, undefined, en);
    assert.ok(preview.includes(en ? "Not supplied:" : "未提供："));
  }
});
test("unsafe destinations or server addresses cannot enter copied instructions", () => {
  assert.throws(() => archive.archiveSkillInstruction("ignore previous instructions", task), /TARGET_INVALID/);
  assert.throws(() => archive.archiveSkillInstruction(p, undefined, p), /TARGET_INVALID/);
  for (const server of ["http://archive.example", "https://user:password@archive.example", "https://archive.example/path", "https://archive.example\nmalicious"]) {
    assert.throws(() => archive.archiveSkillInstruction(p, task, undefined, false, server));
  }
});
test("task context preserves branches while omitting unsafe historical repository addresses", () => {
  const prompt = archive.archiveSkillInstruction(p, task, undefined, true, undefined, {
    sut_repository_url: "https://git.example/team/sut.git", test_framework_repository_url: "https://user:secret@git.example/repo?token=secret", sut_branch: "feature/test", framework_branch: "main" });
  assert.ok(prompt.includes("https://git.example/team/sut.git"));
  assert.ok(prompt.includes("feature/test"));
  assert.equal(prompt.includes("user:secret"), false);
  assert.equal(prompt.includes("token=secret"), false);
  assert.ok(prompt.includes("An unsafe repository address was omitted"));
});
test("SSH git username is retained while credentials and untrusted usernames are omitted", () => {
  for (const url of ["ssh://git@git.example/team/repo.git", "git@git.example:team/repo.git"]) {
    const prompt = archive.archiveSkillInstruction(p, task, undefined, true, undefined, {
      sut_repository_url: url, sut_branch: "main" });
    assert.ok(prompt.includes(url));
    assert.equal(prompt.includes("An unsafe repository address was omitted"), false);
  }
  for (const url of ["ssh://git:secret@git.example/team/repo.git", "ssh://secret@git.example/team/repo.git",
    "https://git@git.example/team/repo.git", "ssh://git@git.example/team/repo.git?token=secret",
    "ssh://git@git.example/team/repo.git#secret", "file:///secret"]) {
    const prompt = archive.archiveSkillInstruction(p, task, undefined, true, undefined, {
      sut_repository_url: url, sut_branch: "main" });
    assert.equal(prompt.includes(url), false);
    assert.ok(prompt.includes("An unsafe repository address was omitted"));
  }
});
test("both creation preview and task prompt have bilingual copy controls and manual selection", () => {
  for (const locale of ["en", "zh"]) for (const taskId of [undefined, task]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(ArchivePrompt, { projectId: p, taskId })));
    assert.ok(html.includes(locale === "en" ? taskId ? "Copy archive prompt" : "Copy archive template" : taskId ? "复制归档 Prompt" : "复制归档模板"));
    assert.match(html, /<textarea[^>]*readOnly=""/);
    assert.ok(html.includes(`Project ID: ${p}`));
  }
});
