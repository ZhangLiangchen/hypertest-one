const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const plain = (value) => JSON.parse(JSON.stringify(value));
const projectId = "00000000-0000-4000-8000-000000000001";
const taskId = "00000000-0000-4000-8000-000000000002";

// Exercise the page's actual event handlers, form values and query-cache update.
// This is component regression evidence, not a browser or deployment acceptance.
function harness({ result = "FAIL", locale = "en", rejected = false } = {}) {
  const original = {
    task: { id: taskId, project_id: projectId, title: "Dedicated status fixture", objective: "Keep this objective", version: 7, archive_version: 3, status: "BLOCKED", reported_result: result },
    subtasks: [{ id: "child", title: "Not executed", status: "DRAFT", reported_result: "NOT_RUN", archive_version: 2 }],
    publications: [{ id: "summary", task_version: 6, root_archive_version: 3, subtask_versions: [{ subtask_id: "child", archive_version: 2 }], asset_revision_ids: ["report"], omitted_subtask_ids: [], incomplete_subtask_ids: ["child"], summary: "Scope: local only.\r\n限制：未覆盖外部系统；未完成性能测试。", status: "BLOCKED", reported_result: result }],
    management_history: [], submission_history: [{ submission_id: "upload", accepted_version: 3 }],
  };
  let data = structuredClone(original), cursor = 0, dirty = false;
  const states = [], effects = [], calls = [], cacheWrites = [], invalidations = [], queries = [];
  const form = { values: {}, resetFields() { this.values = {}; }, setFieldsValue(values) { Object.assign(this.values, values); } };
  const Form = Object.assign(() => null, { Item: "Form.Item", useForm: () => [form], useWatch: (field) => form.values[field] });
  const ui = { Form, Alert: "Alert", Button: "Button", Descriptions: "Descriptions", Empty: "Empty", Input: Object.assign(() => null, { TextArea: "TextArea" }), InputNumber: "InputNumber", Select: "Select", Space: "Space", Table: "Table", Tag: "Tag", Typography: { Paragraph: "Paragraph", Title: "Title", Text: "Text" } };
  const react = {
    useState(initial) { const i = cursor++; if (!(i in states)) states[i] = initial; return [states[i], (next) => { const value = typeof next === "function" ? next(states[i]) : next; if (!Object.is(value, states[i])) { states[i] = value; dirty = true; } }]; },
    useEffect(effect, deps) { const i = cursor++, previous = states[i]; if (!previous || deps.some((value, j) => value !== previous[j])) { states[i] = deps; effects.push(effect); } },
  };
  const jsx = (type, props) => ({ type, props });
  const operation = { blocked: false, busy: false, error: null, pending: null, ready: true, async manage(path, fields) {
    calls.push({ path, fields: plain(fields) });
    if (rejected) { this.error = new Error("ARCHIVE_TASK_VERSION_CONFLICT"); return null; }
    return { task: { ...data.task, status: fields.status, version: data.task.version + 1 }, subtasks: data.subtasks,
      receipt: { operation: "UPDATE_STATUS", operation_id: "status-operation", idempotency_key: "original-key", task_version: data.task.version + 1, from_status: data.task.status, to_status: fields.status, reason: fields.reason, actor_ref: "operator:test", created_at: "2026-11-03T00:00:00Z" } };
  } };
  const cache = {
    setQueryData(key, update) { data = update(data); cacheWrites.push(plain(data)); },
    invalidateQueries(value) { invalidations.push(value); return Promise.resolve(); },
  };
  const page = load("app/tasks/archive-task-detail.tsx", { document: { getElementById: () => ({ scrollIntoView() {}, focus() {} }) }, require: (name) => {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@/lib/i18n") return { useI18n: () => ({ locale, t: (en, zh) => locale === "en" ? en : zh, label: (value) => value, formatDate: (value) => value }) };
    if (name === "@/lib/api") return { errorText: (error) => error?.message || "" };
    if (name === "@/lib/archive") return {};
    if (name === "@/lib/archive-operation") return { useArchiveOperation: () => operation };
    if (name === "@tanstack/react-query") return { useQueryClient: () => cache, useQuery: (options) => {
      queries.push(options);
      return { data: options.queryKey[0] === "archive-task" ? data : options.queryKey[0] === "archive-publication-assets" ? [{ id: "report", title: "Original report", kind: "REPORT", revision: 1, space: null }] : { assets: [{ id: "report", title: "Original report", stable_key: "report", kind: "REPORT", revision: 1, reported_result: result, markdown: "Original report\nLimitations remain", origin: {} }] }, isLoading: false, isError: false, isFetching: false, isPending: false, refetch: async () => ({ data }) };
    } };
    if (name === "@/app/workspace-ui") return { WorkspaceHeading: "WorkspaceHeading", WorkspaceLoading: "WorkspaceLoading", ProjectNavigation: "ProjectNavigation" };
    if (name === "@/app/tasks/task-records") return { ReportedResultTag: "ReportedResultTag" };
    if (name === "@/app/archives/archive-shared") return { ArchiveOperationNotice: "ArchiveOperationNotice" };
    if (name === "@/app/archives/archive-prompt") return { ArchivePrompt: "ArchivePrompt" };
    if (name === "./task-quick-navigation") return { TaskQuickNavigation: "TaskQuickNavigation" };
    if (name === "next/link") return { default: "Link" };
    if (name === "@ant-design/icons") return { ReloadOutlined: "ReloadOutlined" };
    return require(name);
  } }).default;
  function nodes(value) {
    if (!value || typeof value !== "object") return [];
    if (Array.isArray(value)) return value.flatMap(nodes);
    return [value, ...nodes(value.props?.children), ...nodes(value.props?.actions)];
  }
  function render() {
    let tree, passes = 0;
    do { dirty = false; cursor = 0; tree = page({ taskId, projectId }); while (effects.length) effects.shift()(); assert.ok(++passes < 10, "page effects settle"); } while (dirty);
    return nodes(tree);
  }
  const text = (value) => value == null || typeof value === "boolean" ? "" : typeof value !== "object" ? String(value) : Array.isArray(value) ? value.map(text).join("") : text(value.props?.children);
  function click(label) { const button = render().find((node) => node.type === "Button" && text(node) === label); assert.ok(button, `button exists: ${label}`); button.props.onClick(); return render(); }
  return { form, original, operation, calls, cacheWrites, invalidations, queries, render, click, current: () => data, text,
    fields: () => render().filter((node) => node.type === "Form.Item").map((node) => node.props.name).filter(Boolean),
    async submit(values) { const node = render().find((node) => node.type === Form); assert.ok(node, "form is open"); await node.props.onFinish(values); return render(); },
  };
}

test("top-level status action opens an independent form with current progress and no summary or result editor", () => {
  for (const locale of ["en", "zh"]) {
    const h = harness({ locale });
    const nodes = h.click(locale === "en" ? "Change status" : "修改状态");
    assert.equal(h.form.values.status, "BLOCKED");
    assert.deepEqual(h.fields().sort(), ["reason", "status"]);
    assert.ok(nodes.some((node) => node.type === "ReportedResultTag" && node.props.result === "FAIL"));
    const select = nodes.find((node) => node.type === "Select" && node.props.options?.some((option) => option.value === "COMPLETED"));
    assert.deepEqual(plain(select.props.options.map((option) => option.value)), ["DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"]);
    assert.equal(h.queries.filter((query) => query.queryKey[0] === "archive-publication-assets").at(-1).enabled, false);
  }
});

test("status save sends only status and reason and immediately retains results, scope, artifacts and child progress", async () => {
  for (const result of ["FAIL", "BLOCKED", "NOT_RUN"]) {
    const h = harness({ result }); h.click("Change status");
    const nodes = await h.submit({ status: "COMPLETED", reason: "Scope complete; excluded work remains.", reported_result: "PASS", summary: "must not publish", objective: "must not change" });
    assert.deepEqual(h.calls, [{ path: `tasks/${taskId}/status`, fields: { expected_task_version: 7, status: "COMPLETED", reason: "Scope complete; excluded work remains." } }]);
    assert.equal(h.current().task.status, "COMPLETED");
    assert.equal(h.current().task.reported_result, result);
    assert.equal(h.current().task.objective, h.original.task.objective);
    assert.equal(h.current().task.archive_version, 3);
    for (const field of ["publications", "submission_history", "subtasks"]) assert.deepEqual(plain(h.current()[field]), h.original[field]);
    assert.equal(h.current().management_history.length, 1);
    assert.equal(h.current().management_history[0].from_status, "BLOCKED");
    assert.equal(h.current().management_history[0].to_status, "COMPLETED");
    assert.equal(h.cacheWrites.length, 1, "accepted state is available before the refresh completes");
    assert.ok(nodes.some((node) => node.type === "Alert" && node.props.type === "success"));
    h.click("Change status"); assert.equal(h.form.values.status, "COMPLETED");
  }
});

test("rejected status save retains the draft and original task without a success notice or cache write", async () => {
  const h = harness({ rejected: true }); h.click("Change status");
  h.form.setFieldsValue({ status: "COMPLETED", reason: "Keep this reason after conflict" });
  const nodes = await h.submit(h.form.values);
  assert.equal(h.current().task.status, "BLOCKED");
  assert.equal(h.form.values.status, "COMPLETED");
  assert.equal(h.form.values.reason, "Keep this reason after conflict");
  assert.equal(h.cacheWrites.length, 0);
  assert.equal(nodes.some((node) => node.type === "Alert" && node.props.type === "success"), false);
  assert.ok(nodes.some((node) => node.type === "ArchiveOperationNotice" && node.props.operation.error.message === "ARCHIVE_TASK_VERSION_CONFLICT"));
});

test("an unresolved status request visibly disables saving until original-key reconciliation", () => {
  const h = harness(); h.click("Change status");
  h.form.setFieldsValue({ status: "COMPLETED", reason: "Keep this draft while reconciling" });
  h.operation.pending = { operation_key: "original-status-key", state: "UNKNOWN" };
  h.operation.blocked = true;
  const nodes = h.render();
  const submit = nodes.find((node) => node.type === "Button" && node.props.htmlType === "submit");
  assert.ok(submit, "status form still shows its save action");
  assert.equal(submit.props.disabled, true, "an explicit Button prop must not override the disabled form");
  assert.equal(h.form.values.reason, "Keep this draft while reconciling");
  assert.equal(h.calls.length, 0);
  assert.equal(nodes.some((node) => node.type === "Alert" && node.props.type === "success"), false);
});

test("publish summary remains a separate form using the publication endpoint and explicit result", async () => {
  const h = harness({ rejected: true }); h.click("Publish summary");
  assert.ok(h.fields().includes("summary")); assert.ok(h.fields().includes("reported_result"));
  assert.equal(h.form.values.summary, h.original.publications[0].summary);
  assert.equal(h.form.values.reported_result, "FAIL");
  await h.submit({ ...h.form.values, status: "IN_PROGRESS", reported_result: "FAIL" });
  assert.equal(h.calls[0].path, `tasks/${taskId}/publications`);
  assert.equal(h.calls[0].fields.summary, h.original.publications[0].summary);
  assert.equal(h.calls[0].fields.reported_result, "FAIL");
  assert.deepEqual(h.calls[0].fields.subtask_versions, [{ subtask_id: "child", archive_version: 2 }]);
  assert.deepEqual(h.calls[0].fields.asset_revision_ids, ["report"]);
});
