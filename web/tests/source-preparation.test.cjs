const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const preparation = load("lib/source-preparation.ts", { require });
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const diagnostic = (extra = {}) => ({ schema_version: "hypertest.source-preparation-diagnostic/v1", stage: "fetch_commit", category: "authentication", summary: "untrusted-summary-secret", action: "untrusted-action-secret", retryable: true, exit_code: 128, timed_out: false, output_truncated: false, ...extra });
const failedJob = (extra = {}) => ({ id: id(1), key: "JOB-SOURCE-FAILED", project_id: id(2), test_run_id: id(3), job_type: "ADVANCE_RUN", status: "FAILED", error_code: "SOURCE_PREPARATION_FAILED", error_message: "raw-stderr-secret", created_at: "2026-10-19T00:00:00Z", result: { source_preparation_diagnostic: diagnostic() }, ...extra });

function tasks(job, { locale = "en", status = null, freshStatus = status } = {}) {
  const mutations = [], requests = [], clicked = [];
  const i18n = load("lib/i18n.tsx", { require });
  const harness = { binding: status ? { status } : null, reports: [], state: null, issues: [] };
  const hooks = {
    useQuery: ({ queryKey }) => ({ data: queryKey[0] === "jobs" ? [job] : queryKey[0] === "harness" ? harness : job }),
    useMutation: (options) => { mutations.push(options); return { reset() {}, mutate(value) { clicked.push(value); } }; },
    useQueryClient: () => ({ getQueryData() {}, setQueryData() {} }),
  };
  const api = { getRunHarness: async () => ({ ...harness, binding: freshStatus ? { status: freshStatus } : null }), retryJob: async (jobId, key) => { requests.push({ jobId, key }); return { ...job, id: id(9), retry_of_job_id: jobId, idempotency_key: key, status: "QUEUED" }; } };
  const followUp = load("app/runs/[runId]/run-next-action.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  const realUi = require("antd");
  const ui = { ...realUi, Drawer: ({ children }) => React.createElement("section", null, children), message: { useMessage: () => [{ success() {}, info() {} }, null] } };
  const dependencies = { react: { ...React, useState: () => React.useState(job.id) }, antd: ui,
    "@/lib/i18n": i18n, "@/lib/source-preparation": preparation, "@tanstack/react-query": hooks, "@/lib/api": api,
    "@/lib/uuid": { createUuid: () => "source-retry" }, "./run-next-action": followUp, "./job-activity": { JobActivityPanel: () => null } };
  const { useRunJobs } = load("app/runs/[runId]/use-run-jobs.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  let controller;
  function Render() { controller = useRunJobs(job.test_run_id, () => {}, () => {}); return React.createElement(React.Fragment, null, controller.taskTab.children, controller.monitor, controller.dialog); }
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(Render)));
  return { html, controller, mutations, requests, clicked, ui };
}

function nodes(element) {
  if (!element || typeof element !== "object") return [];
  return [element, ...React.Children.toArray(element.props?.children).flatMap(nodes)];
}

test("source failure details show bilingual stage, category and recovery without rendering raw error or backend prose", () => {
  for (const locale of ["en", "zh"]) {
    const { html } = tasks(failedJob(), { locale });
    for (const value of locale === "en" ? ["Source preparation failed", "Failed stage", "Fetch fixed commit", "Git authentication", "Git exit code", "128", "worker host&#x27;s Git credentials", "linked task"] : ["源码准备失败", "失败阶段", "获取固定提交", "Git 认证", "Git 退出码", "128", "Worker 宿主的 Git 认证配置", "关联新任务"]) assert.ok(html.includes(value), value);
    for (const secret of ["raw-stderr-secret", "untrusted-summary-secret", "untrusted-action-secret"]) assert.equal(html.includes(secret), false);
  }
});

test("source retry uses the original failed job and creates the existing retry relationship", async () => {
  const job = failedJob();
  const rendered = tasks(job);
  const button = nodes(rendered.controller.dialog).find((node) => node.type === rendered.ui.Button && node.props.children === "Retry as new task");
  assert.ok(button);
  button.props.onClick();
  assert.equal(rendered.clicked[0].id, job.id);
  const queued = await rendered.mutations[1].mutationFn(rendered.clicked[0]);
  assert.equal(queued.retry_of_job_id, job.id);
  assert.deepEqual(rendered.requests, [{ jobId: job.id, key: "web:source-retry" }]);
});

test("retry remains fenced by fresh session state and recovery is offered before retry", async () => {
  const job = failedJob();
  const recovery = tasks(job, { status: "RECOVERY_REQUIRED" });
  assert.ok(recovery.html.includes("Recover session first"));
  assert.equal(recovery.html.includes("Retry as new task"), false);
  const changed = tasks(job, { status: "ACTIVE", freshStatus: "RECOVERY_REQUIRED" });
  await assert.rejects(changed.mutations[1].mutationFn(job), /This session cannot retry tasks/);
  assert.equal(changed.requests.length, 0);
  for (const status of ["CLOSED", "FAILED", "CANCELLED"]) {
    const { html } = tasks(job, { status });
    assert.ok(html.includes("New round from this run"));
    assert.equal(html.includes("Retry as new task"), false);
  }
});

test("invalid fixed input and checkout integrity direct operators to a reviewed new round", async () => {
  for (const category of ["invalid_source", "checkout_integrity"]) for (const locale of ["en", "zh"]) {
    const job = failedJob({ result: { source_preparation_diagnostic: diagnostic({ category, retryable: false }) } });
    const rendered = tasks(job, { locale });
    assert.ok(rendered.html.includes(`/projects/${job.project_id}?fromRun=${job.test_run_id}`));
    assert.equal(rendered.html.includes(locale === "en" ? "Retry as new task" : "新建重试任务"), false);
    await assert.rejects(rendered.mutations[1].mutationFn(job), locale === "en" ? /operator review or corrected input/ : /创建新轮次修正输入/);
    assert.equal(rendered.requests.length, 0);
  }
});

test("historical failures and incompatible diagnostics show an honest bounded fallback", () => {
  for (const locale of ["en", "zh"]) for (const extra of [
    { error_code: "WORKSPACE_PREPARATION_FAILED", result: null },
    { error_code: "CONFLICTERROR", error_message: "cannot prepare pinned source using configured Git access; verify repository access, commit SHA and network availability", payload: { prepare_workspace: true }, result: null },
    { job_type: "PREPARE_WORKSPACE", error_code: "CONFLICT", result: null },
    { result: { source_preparation_diagnostic: diagnostic({ schema_version: "future-secret", category: "raw-category-secret" }) } },
    { result: { source_preparation_diagnostic: diagnostic({ exit_code: "exit-code-secret" }) } },
  ]) {
    const rendered = tasks(failedJob(extra), { locale });
    assert.ok(rendered.html.includes(locale === "en" ? "specific cause cannot be established" : "无法追认具体原因"));
    assert.ok(rendered.html.includes(locale === "en" ? "Retry as new task" : "新建重试任务"));
    for (const secret of ["raw-stderr-secret", "future-secret", "raw-category-secret", "exit-code-secret"]) assert.equal(rendered.html.includes(secret), false);
  }
});

test("only controlled primitive metadata is projected and output capture limits are explicit", () => {
  const job = failedJob({ result: { source_preparation_diagnostic: diagnostic({ output_truncated: true, stderr: "never-rendered-secret", command: "never-rendered-command" }) } });
  const projected = preparation.sourcePreparationDiagnostic(job);
  assert.deepEqual(Object.keys(projected).sort(), ["category", "exit_code", "output_truncated", "retryable", "stage", "timed_out"].sort());
  const { html } = tasks(job);
  assert.ok(html.includes("diagnostic capture limit"));
  for (const secret of ["never-rendered-secret", "never-rendered-command"]) assert.equal(html.includes(secret), false);
  for (const extra of [{ stage: "__proto__" }, { category: "toString" }, { timed_out: "false" }, { exit_code: Infinity }, { exit_code: 256 }, { exit_code: -256 }, { exit_code: 1.5 }, { retryable: "true" }]) assert.equal(preparation.sourcePreparationDiagnostic(failedJob({ result: { source_preparation_diagnostic: diagnostic(extra) } })), null);
  for (const exit_code of [-255, 0, 255]) assert.equal(preparation.sourcePreparationDiagnostic(failedJob({ result: { source_preparation_diagnostic: diagnostic({ exit_code }) } })).exit_code, exit_code);
});

test("all diagnostic categories and stages have actionable Chinese and English copy", () => {
  for (const category of ["authentication", "access_or_missing_repository", "network", "tls", "revision_not_found", "storage", "timeout", "git_unavailable", "invalid_source", "checkout_integrity", "unknown"]) for (const stage of ["validate_input", "create_workspace", "git_init", "configure_remote", "fetch_commit", "checkout_commit", "validate_checkout", "publish_workspace"]) {
    const job = failedJob({ result: { source_preparation_diagnostic: diagnostic({ category, stage }) } });
    for (const locale of ["en", "zh"]) {
      const copy = preparation.sourcePreparationCopy(job, locale);
      assert.ok(copy.diagnostic);
      assert.ok(copy.stage.length && copy.category.length && copy.summary.length && copy.action.length);
      assert.equal(JSON.stringify(copy).includes("untrusted-"), false);
    }
  }
  assert.equal(preparation.sourcePreparationCopy(failedJob({ job_type: "EXECUTE_TESTS", error_code: "EXECUTION_FAILED", result: null }), "en"), null);
});

test("the overview uses the same controlled summary and opens the exact failed task", () => {
  const i18n = load("lib/i18n.tsx", { require });
  const dependencies = { "@/lib/i18n": i18n, "@/lib/run-summary": load("lib/run-summary.ts", { require }), "@/lib/source-preparation": preparation };
  const { RunOverview } = load("app/runs/[runId]/run-overview.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const dataset = (data) => ({ data, isLoading: false, error: null, refetch() {} });
  const job = failedJob();
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(RunOverview, {
      verdicts: dataset([]), executions: dataset([]), evidence: dataset([]), findings: dataset([]), jobs: dataset([job]), navigate() {}, openTask() {},
    })));
    assert.ok(html.includes(locale === "en" ? "Fetch fixed commit" : "获取固定提交"));
    assert.equal(html.includes("raw-stderr-secret"), false);
  }
  let opened;
  const { RunOverview: DirectOverview } = load("app/runs/[runId]/run-overview.tsx", { require: (name) => name === "@/lib/i18n" ? { useI18n: () => ({ t: (en) => en, label: (value) => value, locale: "en", formatDate: (value) => value }) } : name in dependencies ? dependencies[name] : require(name) });
  const element = DirectOverview({ verdicts: dataset([]), executions: dataset([]), evidence: dataset([]), findings: dataset([]), jobs: dataset([job]), navigate() {}, openTask(value) { opened = value; } });
  const action = nodes(element).find((node) => node.props?.children === "Task details");
  action.props.onClick();
  assert.equal(opened, job.id);
});
