const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const antd = require("antd");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function fixture() {
  return {
    runId: id(1),
    requirements: [{ id: id(2), key: "REQ-REVIEW", title: "需求标题", description: "完整需求正文\n第二行", requirement_type: "FUNCTIONAL", priority: "P0", source_type: "PRD", source_ref: "PRD#sum", logical_key: "api.sum", lifecycle_status: "ACTIVE" }],
    risks: [{ id: id(3), key: "RISK-REVIEW", title: "风险标题", description: "完整风险说明", category: "FUNCTIONAL", severity: "HIGH", probability: "LOW", rationale: "独立风险依据", lifecycle_status: "OPEN", requirement_keys: ["REQ-REVIEW"] }],
    testCases: [{ id: id(4), key: "TC-REVIEW", title: "用例标题", description: "完整测试意图", test_type: "FUNCTIONAL", priority: "P0", lifecycle_status: "ACTIVE", preconditions: ["第一项前置条件", "第二项前置条件"], expected_result: "Expected: 2 + 3 = 5 <script>alert('unsafe')</script>", risk_keys: ["RISK-REVIEW"] }],
    implementations: [{ id: id(5), key: "IMP-REVIEW", file_path: "tests/test_sum.py", symbol: "test_sum", framework: "pytest", language: "python", commit_sha: "a".repeat(40), validation_status: "PENDING", source_sha256: "b".repeat(64), artifact_uri: "sha256:" + "b".repeat(64), test_case_keys: ["TC-REVIEW"] }],
    onClose() {}, onSelect() {},
  };
}

function render(props, { locale = "en", query = {}, captured = [], selected = [] } = {}) {
  const hooks = { useQuery(options) { captured.push(options); return { ...query, refetch() {} }; } };
  const ui = { ...antd,
    Drawer: ({ open, title, children }) => open ? React.createElement("aside", { "aria-label": title }, children) : null,
    Button: (props) => { selected.push(props); return React.createElement(antd.Button, props); },
  };
  const { CanonicalDetailsDrawer } = load("app/runs/[runId]/canonical-details.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@tanstack/react-query" ? hooks : name === "@/lib/api" ? { errorText: (error) => error.message } : name === "antd" ? ui : require(name) });
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(CanonicalDetailsDrawer, props)));
}

test("canonical details expose complete requirements, risk rationale and test expectations in both languages", () => {
  const data = fixture();
  const scenarios = [
    ["requirement", id(2), ["完整需求正文", "第二行", "PRD#sum", "api.sum", "RISK-REVIEW"]],
    ["risk", id(3), ["完整风险说明", "独立风险依据", "REQ-REVIEW", "TC-REVIEW"]],
    ["testCase", id(4), ["完整测试意图", "第一项前置条件", "第二项前置条件", "2 + 3 = 5", "RISK-REVIEW", "IMP-REVIEW"]],
  ];
  for (const locale of ["en", "zh"]) for (const [kind, entityId, values] of scenarios) {
    const html = render({ ...data, selection: { kind, id: entityId } }, { locale });
    for (const value of values) assert.ok(html.includes(value), `${locale}/${kind}: ${value}`);
    assert.equal(html.includes("<script>alert"), false);
    if (kind === "testCase") assert.ok(html.includes("&lt;script&gt;"));
    assert.ok(html.includes(locale === "en" ? "Linked risks" : "关联风险") || kind === "risk");
  }
});

test("relationship buttons navigate between accepted entities rather than using unresolved keys", () => {
  const data = fixture();
  const navigated = [];
  for (const [kind, entityId, expected] of [
    ["requirement", id(2), { kind: "risk", id: id(3) }],
    ["risk", id(3), { kind: "testCase", id: id(4) }],
    ["testCase", id(4), { kind: "implementation", id: id(5) }],
    ["implementation", id(5), { kind: "testCase", id: id(4) }],
  ]) {
    const selected = [];
    render({ ...data, selection: { kind, id: entityId }, onSelect: (value) => navigated.push(JSON.parse(JSON.stringify(value))) }, { selected });
    for (const button of selected) if (button.onClick) button.onClick();
    assert.ok(navigated.some((value) => value.kind === expected.kind && value.id === expected.id));
  }
});

test("implementation source review preserves literal code and never presents accepted code as passing execution", () => {
  const props = { ...fixture(), selection: { kind: "implementation", id: id(5) } };
  for (const locale of ["en", "zh"]) {
    const queries = [];
    const html = render(props, { locale, captured: queries, query: { data: '# <script>do not run</script>\ndef test_sum():\n    assert 2 + 3 == 5' } });
    assert.ok(html.includes("def test_sum():"));
    assert.ok(html.includes("&lt;script&gt;do not run&lt;/script&gt;"));
    assert.equal(html.includes("<script>do not run"), false);
    assert.ok(html.includes(locale === "en" ? "official Runner results are separate records" : "正式 Runner 执行结果分别记录"));
    assert.ok(html.includes("b".repeat(64)));
    assert.equal(queries[0].enabled, true);
    assert.deepEqual(Array.from(queries[0].queryKey), ["implementation-content", id(1), id(5)]);
    assert.equal(html.includes("RELEASE_READY"), false);
  }
});

test("integrity/read failures hide stale code and provide a bilingual retry; tracked tests do not request workspace content", () => {
  const props = { ...fixture(), selection: { kind: "implementation", id: id(5) } };
  for (const locale of ["en", "zh"]) {
    const html = render(props, { locale, query: { data: "OLD_UNVERIFIED_SOURCE", error: new Error("artifact unavailable") } });
    assert.equal(html.includes("OLD_UNVERIFIED_SOURCE"), false);
    assert.ok(html.includes(locale === "en" ? "Test source could not be verified" : "测试源码未能通过读取校验"));
    assert.ok(locale === "en" ? html.includes("Retry") : /重\s*试/.test(html));
    const tracked = fixture();
    tracked.implementations[0].artifact_uri = null;
    const captured = [];
    const trackedHtml = render({ ...tracked, selection: props.selection }, { locale, captured });
    assert.equal(captured[0].enabled, false);
    assert.ok(trackedHtml.includes(locale === "en" ? "Existing repository test" : "仓库中已有的测试"));
  }
});

test("missing entities and unloaded relationship records remain explicit rather than pretending links exist", () => {
  const props = fixture();
  const missing = render({ ...props, selection: { kind: "risk", id: id(99) } });
  assert.ok(missing.includes("Refresh the run before trying again"));
  props.risks[0].requirement_keys.push("REQ-NOT-LOADED");
  const html = render({ ...props, selection: { kind: "risk", id: id(3) } });
  assert.ok(html.includes("REQ-NOT-LOADED"));
  assert.ok(html.includes("Not in the loaded records"));
});

test("test source API uses the recorded run and implementation identities and rejects non-200 error bodies", async () => {
  const urls = [];
  const api = load("lib/api.ts", { fetch: async (url) => { urls.push(url); return new Response("# accepted source\n"); } });
  assert.equal(await api.getImplementationContent(id(1), id(5)), "# accepted source\n");
  assert.deepEqual(urls, [`/api/v1/test-runs/${id(1)}/implementations/${id(5)}/content`]);
  const failed = load("lib/api.ts", { fetch: async () => new Response(JSON.stringify({ detail: "implementation artifact unavailable or checksum mismatch" }), { status: 409 }) });
  await assert.rejects(failed.getImplementationContent(id(1), id(5)), (error) => error.status === 409);
});
