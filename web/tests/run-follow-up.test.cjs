const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const job = (status, extra = {}) => ({ id: id(3), key: "JOB-ORIGINAL", job_type: "ADVANCE_RUN", project_id: id(2), test_run_id: id(1), status, created_at: "2026-10-19T00:00:00Z", ...extra });
const baseProps = { runId: id(1), projectId: id(2), binding: null, jobs: [], ready: true, startDisabled: false, starting: false, answer() {}, reviewSession() {}, reviewTask() {}, start() {} };

function followUp(locale, props) {
  const i18n = load("lib/i18n.tsx", { require });
  const components = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(components.RunNextAction, { ...baseProps, ...props })));
}

test("terminal session main actions create a reviewed new round and never offer start, answer or retry", () => {
  for (const locale of ["en", "zh"]) for (const status of ["CLOSED", "FAILED", "CANCELLED"]) {
    const html = followUp(locale, { binding: { status }, jobs: [job("FAILED")], questionId: "stale-question" });
    assert.equal(html.includes(`/projects/${id(2)}/tasks/new`), true);
    assert.equal(html.includes(locale === "en" ? "Create a test task" : "创建测试任务"), true);
    for (const forbidden of ["Run test cycle", "运行完整测试周期", "Answer question", "回答问题", "retry original", "重试原任务"]) assert.equal(html.includes(forbidden), false);
  }
});

test("recovery, answer, running task and durable retry guidance have distinct actions after a reload", () => {
  for (const locale of ["en", "zh"]) {
    assert.equal(followUp(locale, { binding: { status: "RECOVERY_REQUIRED" }, jobs: [job("FAILED")] }).includes(locale === "en" ? "Recover original session" : "恢复原会话"), true);
    assert.equal(followUp(locale, { binding: { status: "WAITING_INPUT" }, jobs: [job("WAITING_INPUT")], questionId: id(4) }).includes(locale === "en" ? "Answer question" : "回答问题"), true);
    assert.equal(followUp(locale, { binding: { status: "ACTIVE" }, jobs: [job("RUNNING")] }).includes(locale === "en" ? "View active task" : "查看进行中的任务"), true);
    const html = followUp(locale, { binding: { status: "ACTIVE" }, jobs: [job("FAILED")] });
    assert.equal(html.includes(locale === "en" ? "Review &amp; retry original task" : "检查并重试原任务"), true);
    assert.equal(html.includes(locale === "en" ? "Run test cycle" : "运行完整测试周期"), false);
  }
  assert.equal(followUp("en", { ready: false, binding: { status: "ACTIVE" }, jobs: [job("FAILED")] }).includes("Checking task state"), true);
});

test("retry guidance opens the exact latest failed task rather than creating a cycle", () => {
  let selected;
  let starts = 0;
  const { RunNextAction } = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? { useI18n: () => ({ t: (en) => en }) } : require(name) });
  const element = RunNextAction({ ...baseProps, binding: { status: "ACTIVE" }, jobs: [job("FAILED"), job("INTERRUPTED", { id: id(9), created_at: "2026-10-19T00:10:00Z" })], reviewTask: (value) => { selected = value; }, start: () => { starts++; } });
  element.props.onClick();
  assert.equal(selected, id(9));
  assert.equal(starts, 0);
});

test("overview exposes saved reports while retaining the canonical final verdict as the decision", () => {
  const i18n = load("lib/i18n.tsx", { require });
  const summary = load("lib/run-summary.ts", { require });
  const { RunOverview } = load("app/runs/[runId]/run-overview.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/run-summary" ? summary : name === "@/lib/source-preparation" ? load("lib/source-preparation.ts", { require }) : require(name) });
  const dataset = (data) => ({ data, isLoading: false, error: null, refetch() {} });
  for (const locale of ["en", "zh"]) {
    const element = React.createElement(RunOverview, {
      verdicts: dataset([{ id: id(5), status: "FINAL", scope: "TEST_RUN", decision: "RELEASE_BLOCKED", sequence_no: 1, reason: "Official tests failed", created_at: "2026-10-19T00:00:00Z" }]),
      executions: dataset([]), evidence: dataset([]), findings: dataset([]), jobs: dataset([job("SUCCEEDED")]), harness: { ...dataset([]), data: { binding: { status: "CLOSED" }, reports: [{ id: id(6) }], issues: [] } },
      navigate() {}, openVerdict() {}, openEvidence() {}, openExecution() {}, openFinding() {}, openTask() {},
    });
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, element));
    assert.equal(html.includes(locale === "en" ? "Read saved report (1)" : "阅读已保存报告（1）"), true);
    assert.equal(html.includes(locale === "en" ? "Release blocked" : "阻止发布"), true);
    assert.equal(html.includes(locale === "en" ? "remains the quality decision" : "质量结论仍以上方判定为准"), true);
  }
});

function taskController(currentBinding, recordedJobs, createdJob, reports = []) {
  let controller;
  let posts = 0;
  const requests = [];
  const cache = new Map();
  const i18n = load("lib/i18n.tsx", { require });
  const followUp = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  const hooks = { useQuery: ({ queryKey }) => ({ data: queryKey[0] === "jobs" ? [] : queryKey[0] === "harness" ? { binding: { status: "ACTIVE" }, reports: [] } : undefined }), useMutation: () => ({ reset() {} }), useQueryClient: () => ({ getQueryData() {}, setQueryData(key, value) { cache.set(JSON.stringify(key), value); } }) };
  const api = { getJobs: async () => recordedJobs, getRunHarness: async () => ({ binding: currentBinding, reports }), createJob: async (runId, request) => { requests.push({ runId, request }); posts++; if (createdJob) return createdJob; throw new Error("unexpected new job"); } };
  const { useRunJobs } = load("app/runs/[runId]/use-run-jobs.tsx", { require: (name) => name === "@/lib/run-polling" ? load("lib/run-polling.ts", { require }) : name === "@/lib/i18n" ? i18n : name === "@/lib/source-preparation" ? load("lib/source-preparation.ts", { require }) : name === "@tanstack/react-query" ? hooks : name === "@/lib/api" ? api : name === "@/lib/uuid" ? { createUuid: () => "fixed" } : name === "./run-next-action" ? followUp : name === "./job-activity" ? { JobActivityPanel: () => null } : name === "antd" ? { ...require(name), message: { useMessage: () => [{ success() {} }, null] } } : require(name) });
  function Capture() { controller = useRunJobs(id(1), () => {}, () => {}); return null; }
  renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(Capture)));
  return { controller, posts: () => posts, cache, requests };
}

test("a stale cycle dialog cannot bypass the original task retry after session recovery", async () => {
  const { controller, posts } = taskController({ status: "ACTIVE" }, [job("FAILED")]);
  await assert.rejects(controller.submit("ADVANCE_RUN", {}), /Retry the recorded task explicitly/);
  assert.equal(posts(), 0);
});

test("fresh terminal binding blocks a new cycle even when the UI previously read ACTIVE", async () => {
  const { controller, posts } = taskController({ status: "CLOSED" }, []);
  await assert.rejects(controller.submit("ADVANCE_RUN", {}), /Ended sessions require a new testing round/);
  assert.equal(posts(), 0);
});

test("lost submission responses still recover the exact recorded job when its session has since closed", async () => {
  const saved = job("SUCCEEDED", { idempotency_key: "web:fixed" });
  const { controller, posts } = taskController({ status: "CLOSED" }, [saved]);
  const actual = await controller.submit("ADVANCE_RUN", {});
  assert.equal(actual.id, saved.id);
  assert.equal(posts(), 0);
});

test("finding changes are explained as preserving final decision and report history in both languages", () => {
  const i18n = load("lib/i18n.tsx", { require });
  const { VerdictHistoryNotice } = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(VerdictHistoryNotice, { runId: id(1), projectId: id(2) })));
    assert.equal(html.includes(locale === "en" ? "does not rewrite an earlier quality decision or report" : "不会改写先前的质量判定或报告"), true);
    assert.equal(html.includes(`/projects/${id(2)}/tasks/new`), true);
  }
});

test("a failed cycle before binding creation points to its recorded task while unrelated legacy failures keep the start action", () => {
  for (const locale of ["en", "zh"]) for (const status of ["FAILED", "INTERRUPTED", "CANCELLED"]) {
    const html = followUp(locale, { binding: null, jobs: [job(status)] });
    assert.equal(html.includes(locale === "en" ? "Review &amp; retry original task" : "检查并重试原任务"), true);
    assert.equal(html.includes(locale === "en" ? "Run test cycle" : "运行完整测试周期"), false);
  }
  const legacy = followUp("en", { binding: null, jobs: [job("FAILED", { job_type: "EXECUTE_TESTS" })] });
  assert.equal(legacy.includes("Run test cycle"), true);
});

test("fresh cycle submission preserves pre-binding retry lineage, uncertain response recovery and unrelated legacy operations", async () => {
  const failed = taskController(null, [job("FAILED")]);
  await assert.rejects(failed.controller.submit("ADVANCE_RUN", {}), /Retry the recorded task explicitly/);
  assert.equal(failed.posts(), 0);

  const recorded = job("FAILED", { idempotency_key: "web:fixed" });
  const uncertain = taskController(null, [recorded]);
  assert.equal((await uncertain.controller.submit("ADVANCE_RUN", {})).id, recorded.id);
  assert.equal(uncertain.posts(), 0);

  const queued = job("QUEUED", { id: id(8) });
  const legacy = taskController(null, [job("FAILED", { job_type: "EXECUTE_TESTS" })], queued);
  assert.equal((await legacy.controller.submit("ADVANCE_RUN", {})).id, queued.id);
  assert.equal(legacy.posts(), 1);
});


test("independent gate admission uses the fresh closed session, accepted report and absence of active work", async () => {
  const reports = [{ id: id(7) }];
  const queued = job("QUEUED", { job_type: "EVALUATE_GATE", id: id(8) });
  const allowed = taskController({ status: "CLOSED" }, [], queued, reports);
  assert.equal((await allowed.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Triage reviewed" })).id, queued.id);
  assert.equal(allowed.posts(), 1);
  assert.equal(JSON.stringify(allowed.requests[0].request.payload), JSON.stringify({ finalize: true, reason: "Triage reviewed" }));
  for (const status of ["RESERVED", "ACTIVE", "WAITING_INPUT", "RECOVERY_REQUIRED", "FAILED", "CANCELLED"]) {
    const denied = taskController({ status }, [], queued, reports);
    await assert.rejects(denied.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Review" }), /requires a closed session/);
    assert.equal(denied.posts(), 0);
  }
  const missingReport = taskController({ status: "CLOSED" }, [], queued);
  await assert.rejects(missingReport.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Review" }), /accepted report/);
  const active = taskController({ status: "CLOSED" }, [job("RUNNING")], queued, reports);
  await assert.rejects(active.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Review" }), /Wait for the active task/);
  assert.equal(active.posts(), 0);
});

test("gate submission preserves failed-task retry lineage and recovers an already-recorded request", async () => {
  const reports = [{ id: id(7) }];
  const failed = taskController({ status: "CLOSED" }, [job("FAILED", { job_type: "EVALUATE_GATE" })], undefined, reports);
  await assert.rejects(failed.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Review" }), /retry the recorded gate task/);
  assert.equal(failed.posts(), 0);
  const saved = job("SUCCEEDED", { job_type: "EVALUATE_GATE", idempotency_key: "web:fixed" });
  const uncertain = taskController({ status: "RECOVERY_REQUIRED" }, [saved]);
  assert.equal((await uncertain.controller.submit("EVALUATE_GATE", { finalize: true, reason: "Review" })).id, saved.id);
  assert.equal(uncertain.posts(), 0);
});

test("closed session main actions expose independent gate progress and exact failed-gate retry", () => {
  for (const locale of ["en", "zh"]) {
    assert.equal(followUp(locale, { binding: { status: "CLOSED" }, jobs: [job("RUNNING", { job_type: "EVALUATE_GATE" })] }).includes(locale === "en" ? "View reevaluation task" : "查看重评任务"), true);
    assert.equal(followUp(locale, { binding: { status: "CLOSED" }, jobs: [job("FAILED", { job_type: "EVALUATE_GATE" })] }).includes(locale === "en" ? "Review &amp; retry gate task" : "检查并重试门禁任务"), true);
  }
});
