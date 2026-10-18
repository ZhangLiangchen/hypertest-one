const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

 test("recovery requests carry only the expected binding epoch and version, never host paths or session credentials", async () => {
  const calls = [];
  const api = load("lib/api.ts", { fetch: async (url, init) => { calls.push({ url, init }); return new Response("{}"); } });
  await api.recoverRunBinding({ id: id(1), binding_epoch: 2, row_version: 7, workspace_id: "PRIVATE_PATH", provider_session_id: "PRIVATE_NATIVE" });
  assert.equal(calls[0].url, `/api/v1/bindings/${id(1)}/recover`);
  assert.deepEqual(JSON.parse(calls[0].init.body), { expected_epoch: 2, expected_row_version: 7 });
});

test("report reads propagate failed integrity checks rather than treating the error body as report text", async () => {
  const api = load("lib/api.ts", { fetch: async () => new Response(JSON.stringify({ detail: "report artifact unavailable or checksum mismatch" }), { status: 409 }) });
  await assert.rejects(api.getRunReportContent(id(2)), (error) => error.status === 409);
});

test("the real bilingual session panel keeps native fields private and offers recovery only for the recorded recovery state", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const i18n = load("lib/i18n.tsx", { require });
  for (const status of ["ACTIVE", "WAITING_INPUT", "RECOVERY_REQUIRED", "CLOSED"]) {
    const fixture = { binding: { id: id(1), primary_agent_session_id: id(2), binding_epoch: 3, status, updated_at: "2026-10-19T00:00:00Z", provider_session_id: "PRIVATE_NATIVE", workspace_id: "PRIVATE_PATH" }, state: { max_steps: 12, timeout_seconds: 300, harness_budget_seconds: 3600 }, reports: [{ id: id(3), created_at: "2026-10-19T00:00:00Z" }], issues: [] };
    const hooks = { useQuery: (options) => options.queryKey[0] === "harness" ? { data: fixture, refetch() {} } : {}, useMutation: () => ({}), useQueryClient: () => ({}) };
    const { RunHarness } = load("app/runs/[runId]/run-harness.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@tanstack/react-query" ? hooks : name === "@/lib/api" ? {} : require(name) });
    for (const locale of ["en", "zh"]) {
      const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(RunHarness, { runId: id(4), refreshRun: async () => {}, selectTab() {} })));
      assert.equal(html.includes("PRIVATE_"), false);
      assert.equal(html.includes(locale === "en" ? "Read report" : "阅读报告"), true);
      assert.equal(html.includes(locale === "en" ? "Verify &amp; recover session" : "核验并恢复会话"), status === "RECOVERY_REQUIRED");
      assert.equal(html.includes("RELEASE_READY"), false);
      assert.equal(html.includes(locale === "en" ? "3600s of active agent time" : "活跃时间上限 3600 秒"), true);
    }
  }
});
