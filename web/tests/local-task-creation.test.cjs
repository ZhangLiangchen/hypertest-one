const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const helpers = load("lib/local-task-binding.ts");
const installHelper = load("lib/local-mode-install.ts");
const bindingClient = load("lib/task-binding-client.ts", { require: (name) => name === "@/lib/local-mode-install" ? installHelper : require(name) });
const i18n = load("lib/i18n.tsx", { require });
const workspaceUi = load("app/workspace-ui.tsx", { require: (name) => name === "@/lib/i18n" ? i18n
  : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });

function detail() {
  return { task: { id: "task-1", project_id: "project-1", title: "Awaiting local Agent", objective: "Test an authorized target", plan_markdown: "# Initial plan", status: "DRAFT", reported_result: "NOT_RUN", version: 1, binding_state: "UNBOUND", binding_required: true, intended_actor_ref: null, provider: null, session_id: null, source: null, last_synced_at: null, last_managed_at: "2026-10-23T09:00:00Z", created_at: "2026-10-23T09:00:00Z" }, cases: [], reports: [], case_history: [], report_history: [], sync_history: [], binding_history: [], management_history: [], creation_receipt: { status: "ACCEPTED", operation: "CREATE", task_id: "task-1", project_id: "project-1", version: 1, idempotency_key: "create-original" } };
}

test("local creation accepts only management fields and explicitly leaves an unauthorized task unclaimed", () => {
  const body = helpers.localTaskCreatePayload({ title: "  Local task  ", objective: "literal\nobjective", plan_markdown: "# Original\n", provider: "invented", session_id: "other-session", task_id: "other-task", reported_result: "PASS", mode: "cloud" }, "original-key");
  assert.deepEqual(JSON.parse(JSON.stringify(body)), { idempotency_key: "original-key", title: "Local task", objective: "literal\nobjective", plan_markdown: "# Original\n", intended_actor_ref: null });
  assert.equal(helpers.localTaskCreatePayload({ title: "Task", intended_actor_ref: "agent-client:allowed" }, "key").intended_actor_ref, "agent-client:allowed");
});

test("creation ACK is accepted only for the frozen Project, key, task ID and version", () => {
  assert.equal(helpers.validateLocalTaskCreation(detail(), "project-1", "create-original").task.id, "task-1");
  for (const change of [{ idempotency_key: "another-key" }, { project_id: "another-project" }, { task_id: "another-task" }, { version: 2 }, { status: "UNKNOWN" }, { operation: "BIND" }]) {
    const value = detail();
    Object.assign(value.creation_receipt, change);
    assert.throws(() => helpers.validateLocalTaskCreation(value, "project-1", "create-original"), /RECEIPT_MISMATCH/);
  }
});

test("pending request restoration retains its original key and never trusts extra stored identity fields", () => {
  const raw = JSON.stringify({ project_id: "project-1", payload: { idempotency_key: "key-frozen", title: "Task", objective: "Exact objective", intended_actor_ref: null, provider: "fake", session_id: "fake" } });
  const restored = helpers.pendingLocalTaskCreation(raw, "project-1");
  assert.equal(restored.idempotency_key, "key-frozen");
  assert.equal(restored.provider, undefined);
  assert.equal(restored.session_id, undefined);
  assert.throws(() => helpers.pendingLocalTaskCreation(raw, "other-project"), /PENDING_REQUEST_INVALID/);
  for (const error of [new TypeError("Failed to fetch"), { status: 500 }, { status: 502 }, new Error("LOCAL_TASK_CREATION_RECEIPT_MISMATCH")]) assert.equal(helpers.localTaskCreateWasRejected(error), false);
  assert.equal(helpers.localTaskCreateWasRejected({ status: 409, detail: "TASK_OPERATION_KEY_CONFLICT" }), false);
  for (const status of [400, 403, 409, 422]) assert.equal(helpers.localTaskCreateWasRejected({ status }), true);
});

test("local task APIs use operator web routes, explicit actor refs and read-only original-key reconciliation", async () => {
  const calls = [];
  const api = load("lib/api.ts", { fetch: async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify(detail())); } });
  await api.getLocalTaskActors("project id");
  await api.createLocalTask("project id", { idempotency_key: "key-original", title: "Task", objective: "Objective", intended_actor_ref: null });
  await api.getLocalTaskCreation("project id", "key original");
  await api.updateTaskBindingAuthorization("task id", { expected_version: 4, intended_actor_ref: "agent-client:allowed" });
  assert.deepEqual(calls.map(({ url }) => url), ["/api/v1/projects/project%20id/local-task-actors", "/api/v1/projects/project%20id/local-tasks", "/api/v1/projects/project%20id/local-tasks/by-key?idempotency_key=key%20original", "/api/v1/tasks/task%20id/binding-authorization"]);
  assert.equal(calls[2].options.method, undefined);
  assert.equal(calls[3].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[3].options.body), { expected_version: 4, intended_actor_ref: "agent-client:allowed" });
  for (const { options } of calls) {
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.headers["X-Hypertest-Operator-Key"], undefined);
  }
});

test("structured binding failures preserve their stable code and safe existing-task reference", async () => {
  const api = load("lib/api.ts", { fetch: async () => new Response(JSON.stringify({ detail: { code: "SESSION_ALREADY_HAS_TASK", existing_task_id: "existing-task" } }), { status: 409 }), require });
  await assert.rejects(api.createLocalTask("project", { title: "Task", idempotency_key: "key" }), (error) => {
    assert.equal(error.detail, "SESSION_ALREADY_HAS_TASK");
    assert.equal(error.existingTaskId, "existing-task");
    assert.ok(api.errorText(error, "zh").includes("已有任务"));
    return true;
  });
});

test("unbound task records show a stable ID without inventing a session or a successful sync", () => {
  const { SessionTaskRecords } = load("app/tasks/task-records.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(SessionTaskRecords, { detail: detail() })));
    assert.ok(html.includes("task-1"));
    assert.ok(html.includes(locale === "en" ? "Awaiting binding" : "待绑定"));
    assert.ok(html.includes(locale === "en" ? "Not bound yet" : "尚未绑定"));
    assert.ok(html.includes(locale === "en" ? "No Agent sync received" : "尚未收到 Agent 同步"));
    assert.ok(html.includes(locale === "en" ? "Not run" : "尚未运行"));
    assert.equal(html.includes("null · null"), false);
  }
});

test("binding guidance copies the chosen task and version while requiring a real native source", () => {
  const template = JSON.parse(helpers.taskBindingTemplate(detail().task));
  assert.equal(template.task_id, "task-1");
  assert.equal(template.project_id, "project-1");
  assert.equal(template.expected_version, 1);
  assert.equal(template.provider, "codex");
  assert.ok(template.session_id.includes("NATIVE_SESSION_START"));
  assert.equal(template.integration_token, undefined);
  const query = { isLoading: false, isError: false, data: { items: [], total: 0 } };
  const { LocalTaskBinding } = load("app/tasks/local-task-binding.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/local-task-binding" ? helpers : name === "./source-client-upgrade" ? { SourceClientUpgrade: () => null } : name === "@tanstack/react-query" ? { useQuery: () => query, useMutation: () => ({}), useQueryClient: () => ({}) } : name === "@/lib/api" ? {} : require(name) });
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(LocalTaskBinding, { task: detail().task })));
    assert.ok(html.includes("hypertest_bind_task"));
    assert.ok(html.includes("hypertest_get_task_binding"));
    assert.ok(html.includes("task-1"));
    assert.ok(html.includes(locale === "en" ? "it grants no access" : "不授予访问权限"));
    assert.ok(html.includes("local-v0.1.0"));
    assert.ok(html.includes(locale === "en" ? "start a new primary session" : "新建主会话"));
    assert.ok(html.includes("0.144.6"));
    assert.ok(html.includes(locale === "en" ? "do not currently support new Task ID binding" : "当前不支持新任务 ID 绑定"));
    assert.ok(html.includes(locale === "en" ? "Copy the request below" : "复制下方请求"));
    assert.equal(html.includes("hypertest_bind_execution"), false);
  }
});

test("task binding uses the same one-prompt updater and retains the current native caller limit", () => {
  const updater = { url: "https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/update-local.py", sha256: "a".repeat(64) };
  const prompt = bindingClient.taskBindingClientPrompt({ channel: "candidate", locale: "en", directory: "/private/owned install" }, updater);
  assert.ok(prompt.includes("--harness codex --channel candidate"));
  assert.ok(prompt.includes("--directory '/private/owned install'"));
  assert.ok(prompt.includes("0.144.6"));
  assert.ok(prompt.includes("UNKNOWN"));
  assert.equal(prompt.includes("pip install"), false);
});

test("a bound task does not claim an Agent sync before actual artifacts arrive", () => {
  const value = detail();
  Object.assign(value.task, { binding_state: "BOUND", provider: "codex", session_id: "native-root", bound_at: "2026-10-23T10:00:00Z", version: 2 });
  value.binding_history = [{ id: "bind-1", action: "BIND", actor_ref: "client:allowed", task_version: 2, task_snapshot: value.task, created_at: value.task.bound_at }];
  const { SessionTaskRecords } = load("app/tasks/task-records.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(SessionTaskRecords, { detail: value })));
  assert.ok(html.includes("Bound at"));
  assert.ok(html.includes("Binding history"));
  assert.ok(html.includes("no Agent work has been synced yet"));
  assert.ok(html.includes("No sync history is available"));
  assert.equal(html.includes("Synced from the source Agent session"), false);
});

function unifiedCreationHarness({ mode = "cloud", locale = "en", configured = true, operation: operationChanges = {}, queries = {} } = {}) {
  const antd = require("antd"), forms = [], submissions = [], localWrites = [], navigation = [];
  const config = { id: "config-1", revision: 1, configuration: { environment: { connection: "NONE" },
    sut: { url: "https://git.example.org/team/sut.git", default_selector: { kind: "BRANCH", value: "main", checkout_strategy: "HEAD" } },
    framework: { url: "https://git.example.org/team/framework.git", default_selector: { kind: "BRANCH", value: "main", checkout_strategy: "HEAD" } } } };
  const shared = { title: "Shared task title", objective: "Shared testing objective" };
  const Form = Object.assign((props) => {
    forms.push(props);
    return React.createElement(antd.Form, { ...props, initialValues: { ...props.initialValues, ...(props.initialValues?.mode ? { mode, ...shared } : {}) } });
  }, antd.Form, { useWatch: (name) => name === "mode" ? mode : shared[name] ?? null });
  const link = { default: ({ children, ...props }) => React.createElement("a", props, children) };
  const cloud = load("lib/cloud.ts", { URL, TextEncoder, Uint8Array, DataView, Int32Array });
  const operation = { ready: true, busy: false, pending: null, receipt: null, issue: null,
    submit: async (fields) => { submissions.push(fields); return { operation: "CREATE_TASK", task_id: "cloud-task-1" }; }, reconcile() {}, ...operationChanges };
  operation.blocked = !operation.ready || operation.busy || Boolean(operation.pending);
  let operationHookCalls = 0;
  const query = ({ queryKey }) => {
    const data = queryKey[0] === "cloud-web-setup" ? { configured }
      : queryKey[0] === "cloud-capabilities" ? configured ? { enabled: true, worker_enabled: false } : undefined
        : queryKey[0] === "cloud-config" ? configured ? { items: [config] } : undefined : { items: [], total: 0 };
    const result = { isSuccess: true, isLoading: false, isPending: false, isError: false, isFetching: false, data, ...queries[queryKey[0]] };
    return { ...result, refetch: async () => ({ data: result.data }) };
  };
  const cloudForm = load("app/projects/[projectId]/cloud/task-form.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "antd" ? { ...antd, Form } : name === "@/lib/cloud" ? cloud : name === "next/link" ? link : require(name) });
  const notices = load("app/projects/[projectId]/cloud/cloud-shared.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/cloud-recovery" ? load("lib/cloud-recovery.ts") : name === "next/link" ? link : require(name) });
  const { TaskCreateForm } = load("app/projects/[projectId]/tasks/new/task-create-form.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/app/workspace-ui" ? workspaceUi
    : name === "antd" ? { ...antd, Form } : name === "@/lib/local-task-binding" ? helpers : name === "@/lib/cloud" ? cloud
      : name === "@/lib/cloud-operation" ? { useCloudOperation: () => { operationHookCalls++; return operation; } }
        : name === "@/app/archives/archive-prompt" ? { ArchivePrompt: () => React.createElement("div", { "data-archive-prompt": true }) } : name === "@/lib/archive" ? {} : name === "@/lib/archive-operation" ? { useArchiveOperation: () => ({ ready: true, blocked: false, busy: false, pending: null, manage: async (path, payload) => { localWrites.push({path, payload}); return null; } }) } : name === "@/app/archives/archive-shared" ? { ArchiveOperationNotice: () => null }
        : name === "@/lib/local-create-operation" ? { useLocalCreateOperation: () => ({ ready: true, busy: false, success: false, pending: null, submit: async (payload) => { localWrites.push(payload); return null; }, resetError() {} }) }
        : name === "../../cloud/task-form" ? cloudForm : name === "../../cloud/cloud-shared" ? notices
          : name === "@/lib/uuid" ? { createUuid: () => "stable-key" }
            : name === "@tanstack/react-query" ? { useQuery: query, useMutation: () => ({ mutate: (payload) => localWrites.push(payload) }), useQueryClient: () => ({ invalidateQueries() {}, setQueryData() {} }) }
              : name === "@/lib/api" ? {} : name === "next/link" ? link : name === "next/navigation" ? { useRouter: () => ({ push: (href) => navigation.push(href) }), useSearchParams: () => new URLSearchParams() } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(TaskCreateForm, { projectId: "project-1" })));
  return { html, forms, shared, submissions, localWrites, navigation, operationHookCalls };
}

test("unified creation shares title and objective without nesting the Cloud form", () => {
  for (const mode of ["cloud", "local"]) for (const locale of ["en", "zh"]) {
    const { html, operationHookCalls } = unifiedCreationHarness({ mode, locale });
    assert.equal(html.includes("data-archive-prompt"), mode === "local");
    assert.equal((html.match(/id="title"/g) || []).length, 1);
    assert.equal((html.match(/id="objective"/g) || []).length, 1);
    assert.equal(operationHookCalls, 1);
    assert.ok(html.includes(locale === "en" ? "Cloud execution" : "云端执行"));
    assert.ok(html.includes(locale === "en" ? "Local archive" : "本地归档"));
    assert.ok(html.indexOf("</form>") < html.indexOf('id="new-cloud-task-title"'), "the Cloud form is a sibling of the shared form");
    assert.equal((html.match(/<form\b/g) || []).length, 2);
    assert.ok(html.includes('href="/projects/project-1/cloud?tab=resources" target="_blank"'), "resource setup retains this page's draft");
    if (mode === "local") {
      assert.ok(html.includes(locale === "en" ? "Authorized uploader" : "获准上传的身份"));
      assert.ok(html.includes(locale === "en" ? "Archive destination" : "归档目标"));
      assert.ok(html.includes('href="/cli-authorizations?projectId=project-1#cli-install" target="_blank"'), "installation guidance keeps the task draft open");
      assert.ok(html.includes(locale === "en" ? "CLI installation prompt &amp; authorization" : "CLI 安装 Prompt 与授权"));
      assert.ok(html.includes('hidden=""'), "the Cloud draft stays mounted but hidden in Local mode");
    } else {
      assert.ok(html.includes(locale === "en" ? "Create draft and review versions" : "创建草稿并核对版本"));
      assert.equal(html.includes(locale === "en" ? "Authorized uploader" : "获准上传的身份"), false);
    }
  }
});

test("the shared task form has a separate padded workspace surface", () => {
  const { html, forms } = unifiedCreationHarness();
  assert.match(html, /<section class="workspace-panel" aria-labelledby="task-details-title"><form\b/);
  assert.equal(forms[0].className?.includes("workspace-panel") ?? false, false, "Ant Form's reset must not own the content surface padding");
  assert.ok(html.indexOf("</form></section>") < html.indexOf('id="new-cloud-task-title"'));
});

test("initial Cloud reads show loading without falsely reporting missing resources", () => {
  const pending = { data: undefined, isSuccess: false, isPending: true, isLoading: true, isFetching: true };
  const states = [
    { "cloud-web-setup": pending, "cloud-capabilities": pending, "cloud-config": pending },
    { "cloud-capabilities": pending, "cloud-config": pending },
    { "cloud-config": pending },
  ];
  for (const locale of ["en", "zh"]) for (const queries of states) {
    const { html, forms, localWrites, submissions } = unifiedCreationHarness({ locale, queries });
    assert.ok(html.includes(locale === "en" ? "Loading Cloud configuration" : "正在读取云端配置"));
    assert.equal(html.includes(locale === "en" ? "Save project resources first" : "请先保存项目资源"), false);
    assert.equal(html.includes('id="new-cloud-task-title"'), false);
    assert.equal(forms.length, 1, "the Cloud form waits for its initial inputs");
    assert.equal(localWrites.length + submissions.length, 0);
  }
});

test("a failed initial Cloud read shows its error without a missing-resources or loading state", () => {
  const idle = { data: undefined, isSuccess: false, isPending: true, isLoading: false, isFetching: false };
  const failed = { data: undefined, isSuccess: false, isPending: false, isLoading: false, isFetching: false, isError: true };
  const states = [
    { "cloud-web-setup": failed, "cloud-capabilities": idle, "cloud-config": idle },
    { "cloud-capabilities": failed, "cloud-config": idle },
    { "cloud-config": failed },
  ];
  for (const locale of ["en", "zh"]) for (const queries of states) {
    const { html, forms } = unifiedCreationHarness({ locale, queries });
    assert.ok(html.includes(locale === "en" ? "Cloud configuration could not be refreshed" : "无法刷新云端配置"));
    assert.equal(html.includes(locale === "en" ? "Save project resources first" : "请先保存项目资源"), false);
    assert.equal(html.includes(locale === "en" ? "Loading Cloud configuration" : "正在读取云端配置"), false);
    assert.equal(forms.length, 1);
    assert.equal(forms[0].disabled, false, "Cloud read failures must leave Local setup available");
  }
});

test("only a successful empty resource read prompts project resource setup", () => {
  for (const locale of ["en", "zh"]) {
    const { html, forms } = unifiedCreationHarness({ locale, queries: { "cloud-config": { data: { items: [] } } } });
    assert.ok(html.includes(locale === "en" ? "Save project resources first" : "请先保存项目资源"));
    assert.equal(html.includes(locale === "en" ? "Loading Cloud configuration" : "正在读取云端配置"), false);
    assert.equal(html.includes(locale === "en" ? "Cloud configuration could not be refreshed" : "无法刷新云端配置"), false);
    assert.equal(forms.length, 1);
  }
});

test("cached Cloud configuration remains visible after refresh failure and cannot create a draft", async () => {
  for (const key of ["cloud-web-setup", "cloud-capabilities", "cloud-config"]) {
    const { html, forms, submissions } = unifiedCreationHarness({ queries: { [key]: { isSuccess: false, isError: true } } });
    assert.ok(html.includes("Cloud configuration could not be refreshed"));
    assert.ok(html.includes('id="new-cloud-task-title"'), "loaded Cloud fields stay rendered during a failed refresh");
    assert.ok(html.includes("https://git.example.org/team/sut.git"));
    assert.equal(html.includes("Save project resources first"), false);
    assert.equal(html.includes("Loading Cloud configuration"), false);
    const cloudForm = forms.find((form) => form.initialValues?.accounting_unit);
    assert.ok(cloudForm);
    await cloudForm.onFinish({ ...cloudForm.initialValues, prd: "# Requirements", basic_flow: "Read inputs", test_scope: "Approved fixture only", entrypoints: "python -m pytest tests" });
    await new Promise(setImmediate);
    assert.equal(submissions.length, 0, "a stale read must not authorize a new write");
  }
});

test("the embedded Cloud form creates only a draft using shared fields and request credits", async () => {
  const harness = unifiedCreationHarness();
  const cloudForm = harness.forms.find((form) => form.initialValues?.accounting_unit);
  assert.equal(cloudForm.initialValues.accounting_unit, "REQUEST_CREDITS");
  await cloudForm.onFinish({ ...cloudForm.initialValues, title: "Ignored duplicate title", objective: "Ignored duplicate objective", prd: "# Requirements", basic_flow: "Read inputs", test_scope: "Approved fixture only", entrypoints: "python -m pytest tests" });
  await new Promise(setImmediate); // AntD's onFinish wrapper intentionally returns void.
  assert.equal(harness.submissions.length, 1);
  assert.equal(harness.submissions[0].operation, "CREATE_TASK");
  assert.equal(harness.submissions[0].expected_version, 0);
  assert.equal(harness.submissions[0].title, harness.shared.title);
  assert.equal(harness.submissions[0].inputs.objective, harness.shared.objective);
  assert.equal(harness.submissions[0].inputs.budgets.accounting_unit, "REQUEST_CREDITS");
  assert.equal(harness.localWrites.length, 0);
  assert.deepEqual(harness.navigation, ["/cloud-tasks/cloud-task-1?projectId=project-1"]);
});

test("an unresolved Cloud creation keeps its original key visible and prevents a Local create", () => {
  const harness = unifiedCreationHarness({ mode: "local", operation: { pending: { operation_key: "web:original-unknown", operation: "CREATE_TASK" } } });
  assert.equal(harness.forms[0].disabled, true);
  assert.ok(harness.html.includes("web:original-unknown"));
  assert.ok(harness.html.includes("Query original key"));
  harness.forms[0].onFinish({ mode: "local", ...harness.shared });
  assert.equal(harness.localWrites.length, 0);
  assert.equal(harness.submissions.length, 0);
  assert.equal(unifiedCreationHarness({ mode: "local", configured: false }).forms[0].disabled, false, "Cloud setup does not gate Local creation");
});

test("the task directory reopens both task kinds and marks only unbound Local rows as waiting", () => {
  const cloud = load("lib/cloud.ts", { URL, TextEncoder, Uint8Array, DataView, Int32Array });
  const records = load("app/tasks/task-records.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
  const rows = [{ task_id: "cloud-task-1", task_kind: "CLOUD_TASK", product_mode: "CLOUD", title: "Cloud draft", status: "DRAFT", reported_result: "NOT_RUN", version: 1 },
    { task_id: "local-task-1", task_kind: "SESSION_TASK", product_mode: "LOCAL", title: "Local draft", status: "DRAFT", reported_result: "NOT_RUN", version: 1, provider: null, last_synced_at: null }];
  const page = load("app/projects/[projectId]/cloud/page.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/app/workspace-ui" ? workspaceUi : name === "@/lib/cloud" ? cloud
    : name === "@/lib/api" ? {} : name === "@/lib/cloud-operation" ? { useCloudOperation: () => ({ blocked: false }) }
      : name === "@/app/tasks/task-records" ? records : name === "./cloud-shared" ? { CloudCapabilitiesNotice: () => null, CloudOperationNotice: () => null }
        : name === "./resources" ? { CloudResources: () => null } : name === "./task-form" ? { CloudTaskForm: () => null }
          : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) }
            : name === "next/navigation" ? { useParams: () => ({ projectId: "project-1" }), useRouter: () => ({}), useSearchParams: () => new URLSearchParams() }
              : name === "@tanstack/react-query" ? { useQuery: ({ queryKey }) => ({ isSuccess: true, data: queryKey[0] === "project" ? { name: "Project" } : queryKey[0] === "cloud-web-setup" ? { configured: true } : queryKey[0] === "cloud-capabilities" ? { enabled: true } : queryKey[0] === "cloud-directory" ? { items: rows, total: rows.length } : { items: [] } }) } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(page.default)));
  assert.ok(html.includes('href="/cloud-tasks/cloud-task-1?projectId=project-1"'));
  assert.ok(html.includes('href="/tasks/local-task-1"'));
  assert.equal((html.match(/Awaiting local binding/g) || []).length, 1);
  assert.ok(html.includes("Not synced yet"));
  assert.equal(html.includes("null · null"), false);
});

test("unified task creation preserves Local setup and keeps binding mutations out of read-only record components", () => {
  const project = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/page.tsx"), "utf8");
  const navigation = fs.readFileSync(path.join(__dirname, "../app/workspace-ui.tsx"), "utf8");
  const list = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/session-tasks.tsx"), "utf8");
  const form = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/tasks/new/task-create-form.tsx"), "utf8");
  assert.ok(project.includes('/tasks/new'));
  assert.ok(project.includes('"Create test task", "创建测试任务"'));
  assert.ok(project.includes('<ProjectNavigation'));
  assert.ok(navigation.includes('/cloud?tab=tasks'));
  assert.equal(list.includes("<LocalModeGuide"), false);
  assert.ok(fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/archive-tasks.tsx"), "utf8").includes("<LocalModeGuide"));
  assert.ok(list.includes("SessionTaskActions"));
  assert.ok(form.includes('value: "cloud"'));
  assert.ok(form.includes('value: "local"'));
  assert.ok(form.includes("useLocalCreateOperation"));
  assert.ok(fs.readFileSync(path.join(__dirname, "../lib/local-create-operation.ts"), "utf8").includes("getLocalTaskCreation"));
  assert.equal(form.includes("createRun"), false);
  assert.equal(form.includes("bootstrap"), false);
});
