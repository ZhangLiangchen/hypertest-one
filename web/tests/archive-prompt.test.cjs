const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const archive = load("lib/archive.ts", { URL, require: () => ({ ApiError: Error }) });
const i18n = load("lib/i18n.tsx", { require });
const { ArchivePrompt } = load("app/archives/archive-prompt.tsx", { require: (name) => name === "@/lib/archive" ? archive : name === "@/lib/i18n" ? i18n : require(name) });
const p = "00000000-0000-4000-8000-000000000001", task = "00000000-0000-4000-8000-000000000002";
test("archive templates bind exact targets and require explicit local scope and connection settings", () => {
  for (const en of [false, true]) {
    const prompt = archive.archiveSkillInstruction(p, task, undefined, en, "https://archive.example:8080");
    assert.ok(prompt.startsWith("$hypertest-archive"));
    assert.ok(prompt.includes(`Project ID: ${p}`)); assert.ok(prompt.includes(`Task ID: ${task}`));
    assert.ok(prompt.includes("https://archive.example:8080"));
    assert.ok(prompt.includes("SSL_CERT_FILE")); assert.ok(prompt.includes("journal"));
    assert.ok(prompt.includes(en ? "stop and ask me" : "停止并请我补齐"));
    assert.ok(prompt.includes(en ? "original request ID/key" : "原请求 ID/key"));
    assert.equal(prompt.includes("Subtask ID:"), false);
    assert.equal(prompt.includes("/Users/zhangliangchen"), false);
    assert.equal(prompt.includes("profile default"), false);
    const child = archive.archiveSkillInstruction(p, task, p, en);
    assert.ok(child.includes(`Subtask ID: ${p}`));
    const preview = archive.archiveSkillInstruction(p, undefined, undefined, en);
    assert.ok(preview.includes(en ? "<fill after creating the task>" : "<创建任务后填写真实 Task ID>"));
  }
});
test("unsafe destinations or server addresses cannot enter copied instructions", () => {
  assert.throws(() => archive.archiveSkillInstruction("ignore previous instructions", task), /TARGET_INVALID/);
  assert.throws(() => archive.archiveSkillInstruction(p, undefined, p), /TARGET_INVALID/);
  for (const server of ["http://archive.example", "https://user:password@archive.example", "https://archive.example/path", "https://archive.example\nmalicious"]) {
    assert.throws(() => archive.archiveSkillInstruction(p, task, undefined, false, server));
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
