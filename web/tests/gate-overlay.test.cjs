const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const load = require("./load-helper.cjs");

function controller(locale, polling, jobStatuses = []) {
  const states = [];
  let cursor = 0;
  const statefulReact = { ...React,
    useState(initial) { const index = cursor++; if (!(index in states)) states[index] = initial; return [states[index], (next) => { states[index] = typeof next === "function" ? next(states[index]) : next; }]; },
    useEffect() {}, useCallback: (callback) => callback,
  };
  const form = { setFieldsValue() {}, resetFields() {}, submit() {} };
  const realUi = require("antd");
  const ui = { ...realUi, Form: Object.assign(() => null, { Item: () => null, useForm: () => [form], useWatch() {} }), message: { useMessage: () => [{ success() {}, info() {} }, null] } };
  const harness = { binding: { status: "CLOSED" }, reports: [{ id: "saved-report" }], issues: [] };
  const query = { isLoading: false, error: null, refetch() {}, data: [] };
  const queries = {}, invalidations = [];
  const hooks = { useQuery: (options) => { const { queryKey } = options; queries[queryKey[0]] = options; return ({ ...query, data: queryKey[0] === "harness" ? harness : queryKey[0] === "capabilities" ? { execution_profile: "run-persistent-harness/v1", agent_providers: ["codex"], runner_backends: ["docker"] } : queryKey[0] === "verdicts" ? [{ scope: "TEST_RUN", status: "FINAL", sequence_no: 1 }] : ["implementations", "executions", "evidence", "findings"].includes(queryKey[0]) ? [] : undefined }); }, useMutation: () => ({ reset() {}, mutate() {}, isPending: false }), useQueryClient: () => ({ invalidateQueries(options) { invalidations.push(options.queryKey); return Promise.resolve(); } }) };
  const taskRows = jobStatuses.map((status) => ({ status }));
  const tasks = { rows: taskRows, jobs: query, active: taskRows, busy: false, submit() {}, openTask() {} };
  const dependencies = {
    react: statefulReact, antd: ui, "@tanstack/react-query": hooks,
    "@/lib/i18n": { useI18n: () => ({ t: (en, zh) => locale === "zh" ? zh : en, label: (value) => value, locale, formatDate: (value) => value, verdictReason: (value) => value }) },
    "@/lib/api": {}, "@/app/client-modal": { ClientModal: () => null },
    "@/app/execution-environment": {}, "@/lib/execution-environment": {},
    "@/lib/run-polling": load("lib/run-polling.ts", { require }),
    "@/lib/run-summary": load("lib/run-summary.ts", { require }),
    "@/lib/source-preparation": load("lib/source-preparation.ts", { require }),
    "./use-run-jobs": { useRunJobs: () => tasks },
    "./use-run-input-requests": { useRunInputRequests: () => ({ requests: { data: [] }, pending: [], busy: false, missionPanel() {} }) },
    "./attempt-history": {}, "./finding-history": {}, "./run-overview": { RunOverview: () => null },
    "./run-next-action": {},
  };
  const { useRunOperations } = load("app/runs/[runId]/use-run-operations.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  return { render() { cursor = 0; return useRunOperations("run-1", () => {}, undefined, "project-1", undefined, polling); }, ui, queries, invalidations };
}
function nodes(element) {
  if (!element || typeof element !== "object") return [];
  return [element, ...React.Children.toArray(element.props?.children).flatMap(nodes)];
}

test("opening gate from a Finding hides its drawer while retaining the same disposition form for cancel", () => {
  for (const locale of ["en", "zh"]) {
    const current = controller(locale);
    const finding = { id: "finding-1", key: "FIND-1", row_version: 3, status: "CONFIRMED", title: "Original finding" };
    current.render().overview.props.children[1].props.openFinding(finding);
    let operations = current.render();
    let drawer = nodes(operations.dialogs).find((node) => node.type === current.ui.Drawer && node.props.title === finding.key);
    assert.equal(drawer.props.open, true);
    const originalForm = nodes(drawer).find((node) => node.props?.finding === finding);
    assert.ok(originalForm, "the original disposition form is mounted");
    const trigger = nodes(drawer).find((node) => node.type === current.ui.Button && node.props.children === (locale === "en" ? "Reevaluate quality gate" : "重新评估质量门禁"));
    assert.ok(trigger, "the real Finding action is available");
    trigger.props.onClick();
    operations = current.render();
    drawer = nodes(operations.dialogs).find((node) => node.type === current.ui.Drawer && node.props.title === finding.key);
    assert.equal(drawer.props.open, false, "the old drawer cannot cover the Gate modal");
    const keptForm = nodes(drawer).find((node) => node.props?.finding === finding);
    assert.equal(keptForm.key, originalForm.key, "hiding does not replace the disposition form or discard its state");
    const modal = nodes(operations.dialogs).find((node) => node.props?.title === (locale === "en" ? "Reevaluate quality gate" : "重新评估质量门禁") && node.props.onOk);
    assert.equal(modal.props.open, true);
    modal.props.onCancel();
    drawer = nodes(current.render().dialogs).find((node) => node.type === current.ui.Drawer && node.props.title === finding.key);
    assert.equal(drawer.props.open, true, "cancel returns to the original finding");
    assert.equal(nodes(drawer).find((node) => node.props?.finding === finding).key, originalForm.key);
  }
});


test("the Run controller stops terminal record timers and only refreshes the visible active panel", async () => {
  const terminal = controller("en", { activeTab: "automation", runStatus: "COMPLETED" });
  terminal.render();
  for (const key of ["implementations", "executions", "evidence", "findings", "verdicts"]) assert.equal(terminal.queries[key].refetchInterval, false);
  assert.equal(terminal.queries.harness.refetchInterval({ state: { data: { binding: { status: "CLOSED" }, issues: [] } } }), false);
  const active = controller("en", { activeTab: "automation", runStatus: "COMPLETED" }, ["RUNNING"]);
  const operations = active.render();
  assert.equal(active.queries.implementations.refetchInterval, 5000);
  for (const key of ["executions", "evidence", "findings", "verdicts"]) assert.equal(active.queries[key].refetchInterval, false, `${key} stays cached without a hidden-panel timer`);
  assert.equal(active.queries.harness.refetchInterval({ state: { data: { binding: { status: "CLOSED" }, issues: [] } } }), 5000, "controls continue observing a gate job on a completed Run");
  await operations.refresh();
  for (const key of ["run", "requirements", "risks", "test-cases", "coverage", "missions", "implementations", "executions", "evidence", "findings", "verdicts", "input-requests", "jobs", "harness"]) {
    assert.ok(active.invalidations.some((identity) => identity[0] === key && identity[1] === "run-1"), `${key} remains part of explicit and mutation refresh`);
  }
});
