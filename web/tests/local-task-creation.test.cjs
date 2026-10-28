const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const workspaceUi = load("app/workspace-ui.tsx", { require: (name) => name === "@/lib/i18n" ? i18n
  : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });

function unifiedCreationHarness({ mode = "cloud", locale = "en", configured = true, operation: operationChanges = {}, queries = {}, localResult = null, project = undefined, noDefaultSelectors = false } = {}) {
  const antd = require("antd"), forms = [], submissions = [], localWrites = [], navigation = [];
  const config = { id: "config-1", revision: 1, configuration: { environment: { connection: "NONE" },
    sut: { url: "https://git.example.org/team/sut.git", default_selector: { kind: "BRANCH", value: "main", checkout_strategy: "HEAD" } },
    framework: { url: "https://git.example.org/team/framework.git", default_selector: { kind: "BRANCH", value: "main", checkout_strategy: "HEAD" } } } };
  if (noDefaultSelectors) { delete config.configuration.sut.default_selector; delete config.configuration.framework.default_selector; }
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
  const { TaskCreateForm } = load("app/projects/[projectId]/tasks/new/task-create-form.tsx", { require: (name) => name === "@/lib/task-url" ? load("lib/task-url.ts") : name === "@/lib/i18n" ? i18n : name === "@/app/workspace-ui" ? workspaceUi
    : name === "antd" ? { ...antd, Form } : name === "@/lib/cloud" ? cloud
      : name === "@/lib/cloud-operation" ? { useCloudOperation: () => { operationHookCalls++; return operation; } }
        : name === "@/app/archives/archive-prompt" ? { ArchivePrompt: () => React.createElement("div", { "data-archive-prompt": true }) } : name === "@/lib/archive" ? {} : name === "@/lib/archive-operation" ? { useArchiveOperation: () => ({ ready: true, blocked: false, busy: false, pending: null, manage: async (path, payload) => { localWrites.push({path, payload}); return localResult; } }) } : name === "@/app/archives/archive-shared" ? { ArchiveOperationNotice: () => null }
        : name === "../../cloud/task-form" ? cloudForm : name === "../../cloud/cloud-shared" ? notices
          : name === "@/lib/uuid" ? { createUuid: () => "stable-key" }
            : name === "@tanstack/react-query" ? { useQuery: query, useMutation: () => ({ mutate: (payload) => localWrites.push(payload) }), useQueryClient: () => ({ invalidateQueries() {}, setQueryData() {} }) }
              : name === "@/lib/api" ? {} : name === "next/link" ? link : name === "next/navigation" ? { useRouter: () => ({ push: (href) => navigation.push(href) }), useSearchParams: () => new URLSearchParams() } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(TaskCreateForm, { projectId: "project-1", project })));
  return { html, forms, shared, submissions, localWrites, navigation, operationHookCalls };
}

test("unified creation shares title and objective without nesting the Cloud form", () => {
  for (const mode of ["cloud", "local"]) for (const locale of ["en", "zh"]) {
    const { html, operationHookCalls } = unifiedCreationHarness({ mode, locale });
    assert.equal(html.includes("data-archive-prompt"), mode === "local");
    assert.equal((html.match(/id="title"/g) || []).length, 1);
    assert.equal((html.match(/id="objective"/g) || []).length, 1);
    assert.equal(operationHookCalls, 1);
    assert.ok(html.includes(locale === "en" ? "Cloud testing" : "云端测试"));
    assert.ok(html.includes(locale === "en" ? "Local testing" : "本地测试"));
    assert.ok(html.indexOf("</form>") < html.indexOf('id="new-cloud-task-title"'), "the Cloud form is a sibling of the shared form");
    assert.equal((html.match(/<form\b/g) || []).length, 2);
    assert.ok(html.includes('href="/projects/project-1/cloud?tab=resources" target="_blank"'), "resource setup retains this page's draft");
    if (mode === "local") {
      assert.ok(html.includes(locale === "en" ? "Authorized uploader" : "获准上传的身份"));
      assert.ok(html.includes(locale === "en" ? "Local test setup" : "本地测试配置"));
      assert.ok(html.includes(locale === "en" ? "Create local test task" : "创建本地测试任务"));
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

test("cloud tasks without saved defaults require selecting each repository revision", () => {
  const harness = unifiedCreationHarness({ noDefaultSelectors: true });
  const cloudForm = harness.forms.find((form) => form.initialValues?.accounting_unit);
  assert.equal(cloudForm.initialValues.sut_ref, undefined);
  assert.equal(cloudForm.initialValues.framework_ref, undefined);
  assert.equal(cloudForm.initialValues.sut_kind, "BRANCH");
  assert.equal(cloudForm.initialValues.framework_kind, "BRANCH");
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

test("project and Cloud expose only current task creation routes", () => {
  const project = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/page.tsx"), "utf8");
  const cloud = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/cloud/page.tsx"), "utf8");
  const form = fs.readFileSync(path.join(__dirname, "../app/projects/[projectId]/tasks/new/task-create-form.tsx"), "utf8");
  assert.ok(project.includes("<ProjectArchiveTasks"));
  assert.equal(/ProjectSessionTasks|RunCreateDialog/.test(project), false);
  assert.equal(/Legacy local sessions|SESSION_TASK|CloudTaskForm/.test(cloud), false);
  assert.ok(cloud.includes('cloudDirectory(projectId, "CLOUD"'));
  assert.equal(/useLocalCreateOperation|createRun|bootstrap/.test(form), false);
  assert.ok(form.includes('value: "cloud"'));
  assert.ok(form.includes('value: "local"'));
});

test("an accepted local archive creation opens the shared task route without changing the destination", async () => {
  const { forms, navigation, localWrites } = unifiedCreationHarness({ mode: "local", localResult: { task: { id: "archive-task-1" } } });
  await forms[0].onFinish({ mode: "local", title: "Archive task", objective: "Store completed reports" });
  assert.deepEqual(navigation, ["/tasks/archive-task-1?mode=archive&projectId=project-1"]);
  assert.equal(localWrites.length, 1);
  assert.equal(localWrites[0].path, "tasks");
});

test("local task freezes the selected branches against the displayed project revision", async () => {
  const project = { id: "project-1", row_version: 7, repository_url: "https://git.example/sut", test_framework_repository_url: "https://git.example/framework" };
  const { html, forms, localWrites } = unifiedCreationHarness({ mode: "local", project });
  assert.ok(html.includes("SUT branch") && html.includes("Test framework branch"));
  await forms[0].onFinish({ mode: "local", title: "Test", objective: "Run framework", sut_branch: " feature/a ", framework_branch: " tests/a " });
  assert.equal(localWrites[0].payload.sut_branch, "feature/a");
  assert.equal(localWrites[0].payload.framework_branch, "tests/a");
  assert.equal(localWrites[0].payload.expected_project_version, 7);
});

test("legacy project missing repository addresses cannot create a local task from stale inputs", async () => {
  const { html, forms, localWrites } = unifiedCreationHarness({ mode: "local", project: { id: "project-1", row_version: 2, repository_url: "https://git.example/sut" } });
  assert.ok(html.includes("Project repository addresses are incomplete"));
  await forms[0].onFinish({ mode: "local", title: "Test", objective: "Test", sut_branch: "main", framework_branch: "main" });
  assert.equal(localWrites.length, 0);
});
