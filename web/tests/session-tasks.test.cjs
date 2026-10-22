const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const { SessionTaskRecords } = load("app/tasks/task-records.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });

function fixture() {
  const at = "2026-10-21T04:00:00+00:00";
  const task = { id: "task-1", project_id: "project-1", provider: "codex", session_id: "session-long-reference", title: "Provider integration", objective: "Real SUT objective", status: "IN_PROGRESS", plan_markdown: "# Plan\nPreserve the raw source", reported_result: "PASS", version: 2, source: "AGENT_REPORTED", created_at: at, last_synced_at: at };
  const item = { id: "case-1", task_id: task.id, key: "UC-TX-18-01", title: "Preserved case", steps: ["Call project test", "Inspect result"], expected: "The expected response", actual: "Observed response", reported_result: "PASS", revision: 2, task_version: 2, source: "AGENT_REPORTED", created_at: at };
  const report = { id: "report-1", task_id: task.id, key: "original", title: "Original report", markdown: "# Original\n<script>UNTRUSTED()</script>\nResult: PASS", source_ref: "repo/report.md", reported_result: "PASS", revision: 2, task_version: 2, source: "AGENT_REPORTED", created_at: at };
  return { task, cases: [item], reports: [report], case_history: [{ ...item, id: "case-old", revision: 1, reported_result: "FAIL", actual: "Historical failure" }, item], report_history: [{ ...report, id: "report-old", revision: 1, reported_result: "FAIL", markdown: "# Historical failure\nDo not overwrite" }, report], sync_history: [{ id: "sync-1", task_version: 2, actor_ref: "codex:client", created_at: at, task_snapshot: task }] };
}

function render(detail, locale) {
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(SessionTaskRecords, { detail })));
}

test("session task separates progress and reported result and preserves previous failures in both languages", () => {
  for (const locale of ["en", "zh"]) {
    const html = render(fixture(), locale);
    for (const text of ["session-long-reference", "AGENT_REPORTED", "Historical failure", "Do not overwrite", "The expected response", "Call project test", "Observed response", "codex:client"]) assert.ok(html.includes(text), text);
    assert.ok(html.includes(locale === "en" ? "In progress" : "进行中"));
    assert.ok(html.includes(locale === "en" ? "Codex reported result" : "Codex 报告结果"));
    assert.ok(html.includes(locale === "en" ? "Pass" : "通过"));
    assert.ok(html.includes(locale === "en" ? "Fail" : "未通过"));
    assert.equal(html.includes(locale === "en" ? ">Unknown<" : ">未知<"), false);
    for (const claim of ["RELEASE_READY", "VERIFIED", "Gate", "Runner"]) assert.equal(html.includes(claim), false);
  }
});

test("untrusted original Markdown remains literal readable text, including report history", () => {
  const html = render(fixture(), "en");
  assert.ok(html.includes("&lt;script&gt;UNTRUSTED()&lt;/script&gt;"));
  assert.equal(html.includes("<script>UNTRUSTED"), false);
  assert.ok(html.includes("Original Markdown report"));
  assert.ok(html.includes("Copy original report"));
  assert.ok(html.includes("repo/report.md"));
  assert.ok(html.includes("Report revision history"));
});

test("empty synchronized task does not invent results, cases or reports", () => {
  const detail = fixture();
  detail.cases = detail.case_history = detail.reports = detail.report_history = detail.sync_history = [];
  detail.task.plan_markdown = "";
  detail.task.reported_result = "NOT_RUN";
  const html = render(detail, "en");
  assert.ok(html.includes("Not run"));
  assert.ok(html.includes("No cases have been synced"));
  assert.ok(html.includes("No reports have been synced"));
  assert.ok(html.includes("No test plan has been synced"));
  assert.equal(html.includes("Historical failure"), false);
});

test("task management reads only task APIs without credentials or execution mutations", async () => {
  const calls = [];
  const api = load("lib/api.ts", { fetch: async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ items: [] })); } });
  await api.getProjectTasks("project value", 20, 20);
  await api.getSessionTask("task value");
  await api.getSessionTask("task value", 1);
  await api.getSessionReport("task value", "report value");
  assert.deepEqual(calls.map((call) => call.url), ["/api/v1/tasks?project_id=project%20value&limit=20&offset=20", "/api/v1/tasks/task%20value", "/api/v1/tasks/task%20value?version=1", "/api/v1/tasks/task%20value/reports/report%20value"]);
  for (const { options } of calls) {
    assert.equal(options.method, undefined);
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers["X-Hypertest-Operator-Key"], undefined);
  }
  for (const file of ["app/tasks/[taskId]/page.tsx", "app/tasks/task-records.tsx", "app/projects/[projectId]/session-tasks.tsx"]) {
    const source = fs.readFileSync(path.join(__dirname, "..", file), "utf8");
    assert.equal(/useRunOperations|createRun|requestExecution|bootstrap|evaluateGate|dangerouslySetInnerHTML|useMutation/.test(source), false, file);
  }
});

test("project task reads show loading, empty and refresh errors without discarding loaded records", () => {
  for (const locale of ["en", "zh"]) {
    for (const state of ["loading", "empty", "error", "stale"]) {
      const query = { isLoading: state === "loading", isFetching: false, isError: state === "error" || state === "stale", error: new Error("Read failed"), refetch() {}, data: state === "stale" ? { items: [fixture().task], total: 1 } : state === "empty" ? { items: [], total: 0 } : undefined };
      const component = load("app/projects/[projectId]/session-tasks.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "./local-mode-guide" ? { LocalModeGuide: () => null } : name === "@tanstack/react-query" ? { useQuery: () => query } : name === "@/lib/api" ? { errorText: (error) => error.message } : name === "@/app/tasks/task-records" ? load("app/tasks/task-records.tsx", { require: (n) => n === "@/lib/i18n" ? i18n : require(n) }) : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });
      const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.ProjectSessionTasks, { projectId: "project-1" })));
      if (state === "empty") assert.ok(html.includes(locale === "en" ? "No Codex tasks" : "尚未同步 Codex 测试任务"));
      if (query.isError) assert.ok(html.includes(locale === "en" ? "Task sync records could not be refreshed" : "无法刷新任务同步记录"));
      if (state === "stale") assert.ok(html.includes("Provider integration"));
      else assert.equal(html.includes("Provider integration"), false);
    }
  }
});
