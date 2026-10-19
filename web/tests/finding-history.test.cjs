const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const findingId = "00000000-0000-4000-8000-000000000001";

function render(query, locale = "en") {
  const queries = [];
  const hooks = { useQuery(options) { queries.push(options); return { refetch() {}, ...query }; } };
  const { FindingHistory } = load("app/runs/[runId]/finding-history.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@tanstack/react-query" ? hooks : name === "@/lib/api" ? { errorText: (error) => error.message } : require(name) });
  return { html: renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(FindingHistory, { findingId }))), queries };
}
const event = { id: "history-1", created_at: "2026-10-19T00:00:00Z", actor_type: "USER", action: "finding.resolved", before: { status: "CONFIRMED", resolution: null, row_version: 3 }, after: { status: "RESOLVED", resolution: "RISK_ACCEPTED", row_version: 4 }, reason: "Reviewed evidence <script>unsafe</script>\nWith owner", reason_truncated: false, actor_ref: "PRIVATE_USER", metadata: { provider: "PRIVATE_PROVIDER" } };

test("disposition history shows the recorded transitions, versions and reason in both languages without raw audit metadata", () => {
  for (const locale of ["en", "zh"]) {
    const { html, queries } = render({ data: { events: [event], truncated: false } }, locale);
    assert.equal(html.includes("Reviewed evidence &lt;script&gt;unsafe&lt;/script&gt;"), true);
    assert.equal(html.includes("<script>unsafe"), false);
    assert.equal(html.includes("PRIVATE_"), false);
    assert.equal(html.includes(locale === "en" ? "Confirmed" : "已确认"), true);
    assert.equal(html.includes(locale === "en" ? "Resolved" : "已解决"), true);
    assert.equal(html.includes(locale === "en" ? "Risk accepted" : "接受风险"), true);
    assert.equal(html.includes(locale === "en" ? "Version" : "版本"), true);
    assert.deepEqual(Array.from(queries[0].queryKey), ["finding-history", findingId]);
  }
});

test("failed history refresh retains loaded disposition history and makes bounded or missing history explicit", () => {
  for (const locale of ["en", "zh"]) {
    const { html } = render({ error: new Error("Read failed"), data: { events: [{ ...event, reason_truncated: true }], truncated: true } }, locale);
    assert.equal(html.includes("Reviewed evidence"), true);
    assert.equal(html.includes(locale === "en" ? "current disposition draft remain available" : "当前处置草稿仍会保留"), true);
    assert.equal(html.includes(locale === "en" ? "latest 50 recorded events" : "最近 50 条事件"), true);
    assert.equal(html.includes(locale === "en" ? "historical reason is abbreviated" : "历史原因已截短"), true);
    const empty = render({ data: { events: [], truncated: false } }, locale).html;
    assert.equal(empty.includes(locale === "en" ? "No disposition history" : "尚无已记录的处置历史"), true);
  }
});

test("finding history API is a bounded readonly request and error responses remain errors", async () => {
  const calls = [];
  const api = load("lib/api.ts", { fetch: async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify({ events: [], truncated: false })); } });
  await api.getFindingHistory(findingId);
  assert.equal(calls[0].url, `/api/v1/findings/${findingId}/history?limit=50`);
  assert.equal(calls[0].init.method, undefined);
  const failing = load("lib/api.ts", { fetch: async () => new Response(JSON.stringify({ detail: "finding not found" }), { status: 404 }) });
  await assert.rejects(failing.getFindingHistory(findingId), (error) => error.status === 404);
});
