const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const row = { scope_id: "scope", artifact_id: "artifact", revision: 1, kind: "fact", content: "Existing project lesson", content_digest: "sha256:exact", historical: false };
function components(observed = []) {
  return load("app/projects/[projectId]/memory/knowledge-browser.tsx", { require: (name) => name === "@/lib/i18n" ? i18n
    : name === "@/lib/memory" ? { memoryBrowse: (...args) => { observed.push(args); } }
      : name === "@tanstack/react-query" ? { useQuery: (options) => { observed.push(options); return { data: { configured: true, history_available: true, items: [row], next_cursor: "next" }, refetch() {} }; } } : require(name) });
}
const render = (type, props) => renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "zh" }, React.createElement(type, props)));

test("project knowledge loads main inventory immediately and separates historical browsing from platform approval", async () => {
  const observed = [], { KnowledgeBrowser } = components(observed);
  const html = render(KnowledgeBrowser, { projectId: "project", enabled: true });
  assert.equal(observed[0].enabled, true);
  await observed[0].queryFn();
  assert.deepEqual(observed[1], ["project", "main", undefined, ""]);
  for (const text of ["项目主经验", "历史记忆", "Existing project lesson", "未经平台审核", "下一页"]) assert.ok(html.includes(text), text);
});

test("history details retain original date, fragment identity and corrections without treating migration as review", () => {
  const { KnowledgeRecords } = components();
  const history = { ...row, historical: true, kind: "historical_technical_record", content: "<script>old diagnosis</script>", history_metadata: {
    original_date: "2026-08-21T06:25:25Z", legacy_record_id: "3205", part_index: 1, part_count: 2, correction_notice: "已知后续更正/补充：old_id=3208" } };
  const html = render(KnowledgeRecords, { records: [history] });
  for (const text of ["非当前事实", "2026-08-21T06:25:25Z", "3205", "1/2", "old_id=3208", "查看全文", "scope/artifact@1", "sha256:exact"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("<script>"), false);
  assert.equal(html.includes("审阅并发布"), false);
  const missing = render(KnowledgeRecords, { records: [{ ...history, history_metadata: null }] });
  assert.ok(missing.includes("原文未提供"));
});
