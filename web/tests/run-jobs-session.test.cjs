const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function renderTasks(status, locale = "en", freshStatus = status, operation = "ADVANCE_RUN", reports = [], retryResult) {
  const mutations = [];
  const job = { id: id(1), key: "JOB-HISTORY", project_id: id(2), job_type: operation, status: "FAILED", created_at: "2026-10-19T00:00:00Z" };
  const harness = { binding: status ? { status } : null, state: null, reports, issues: [] };
  const api = { getRunHarness: async () => ({ ...harness, binding: freshStatus ? { status: freshStatus } : null }), retryJob: async (jobId, key) => { if (retryResult) return { ...job, id: id(9), idempotency_key: key, retry_of_job_id: jobId, status: "QUEUED" }; throw new Error("retry POST must not be reached"); } };
  const hooks = { useQuery: ({ queryKey }) => ({ data: queryKey[0] === "jobs" ? [job] : queryKey[0] === "harness" ? harness : undefined }), useMutation: (options) => { mutations.push(options); return { reset() {} }; }, useQueryClient: () => ({ getQueryData() {}, setQueryData() {} }) };
  const i18n = load("lib/i18n.tsx", { require });
  const followUp = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  const { useRunJobs } = load("app/runs/[runId]/use-run-jobs.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@tanstack/react-query" ? hooks : name === "@/lib/api" ? api : name === "@/lib/uuid" ? { createUuid: () => "fixed" } : name === "./job-activity" ? { JobActivityPanel: () => null } : name === "./run-next-action" ? followUp : require(name) });
  function Tasks() { return useRunJobs(id(3), () => {}, () => {}).taskTab.children; }
  return { html: renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(Tasks))), mutations, job };
}

test("historical failed tasks in ended sessions direct both languages to a new run", () => {
  for (const status of ["CLOSED", "FAILED", "CANCELLED"]) for (const locale of ["en", "zh"]) {
    const { html } = renderTasks(status, locale);
    assert.equal(html.includes(locale === "en" ? "Retry as new task" : "新建重试任务"), false);
    assert.equal(html.includes(locale === "en" ? "New round from this run" : "基于本次运行创建新轮次"), true);
    assert.equal(html.includes(`/projects/${id(2)}?fromRun=${id(3)}`), true);
  }
});

test("retry is offered only after binding recovery or for legacy unbound runs", () => {
  assert.equal(renderTasks("RECOVERY_REQUIRED").html.includes("Recover session first"), true);
  assert.equal(renderTasks("RECOVERY_REQUIRED").html.includes("Retry as new task"), false);
  for (const status of ["ACTIVE", null]) assert.equal(renderTasks(status).html.includes("Retry as new task"), true);
});

test("retry rechecks fresh binding state before sending any mutation", async () => {
  const { mutations, job } = renderTasks("ACTIVE", "en", "CLOSED");
  await assert.rejects(mutations[1].mutationFn(job), /This session cannot retry tasks/);
});


test("only independent gate retries remain available in a closed session with an accepted report", () => {
  for (const locale of ["en", "zh"]) {
    const closed = renderTasks("CLOSED", locale, "CLOSED", "EVALUATE_GATE", [{ id: id(8) }]).html;
    assert.equal(closed.includes(locale === "en" ? "Retry as new task" : "新建重试任务"), true);
    assert.equal(closed.includes(locale === "en" ? "New round from this run" : "基于本次运行创建新轮次"), false);
    for (const status of ["ACTIVE", "RECOVERY_REQUIRED", "WAITING_INPUT", "FAILED", "CANCELLED"]) {
      assert.equal(renderTasks(status, locale, status, "EVALUATE_GATE", [{ id: id(8) }]).html.includes(locale === "en" ? "Retry as new task" : "新建重试任务"), false);
    }
    assert.equal(renderTasks("CLOSED", locale, "CLOSED", "EVALUATE_GATE").html.includes(locale === "en" ? "Retry as new task" : "新建重试任务"), false);
  }
});

test("a closed gate retry rechecks admission and preserves the exact prior job relationship", async () => {
  const allowed = renderTasks("CLOSED", "en", "CLOSED", "EVALUATE_GATE", [{ id: id(8) }], true);
  const queued = await allowed.mutations[1].mutationFn(allowed.job);
  assert.equal(queued.retry_of_job_id, allowed.job.id);
  assert.equal(queued.idempotency_key, "web:fixed");
  const changed = renderTasks("CLOSED", "en", "ACTIVE", "EVALUATE_GATE", [{ id: id(8) }], true);
  await assert.rejects(changed.mutations[1].mutationFn(changed.job), /This session cannot retry tasks/);
});
