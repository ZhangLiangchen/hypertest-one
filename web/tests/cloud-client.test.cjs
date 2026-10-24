const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const load = require("./load-helper.cjs");

const helpers = () => load("lib/cloud.ts", { TextEncoder, Uint8Array, DataView, Int32Array, URL });

test("Cloud request identity is SHA-256, including unicode and long inputs", () => {
  const { cloudInputIdentity } = helpers();
  for (const input of [{}, { title: "版本与测试 🧪", prd: "原始文本\n" }, { value: "long".repeat(1000) }]) {
    assert.equal(cloudInputIdentity(input), createHash("sha256").update(JSON.stringify(input)).digest("hex"));
  }
});

test("Cloud journal restores only metadata, never a frozen body or secret", () => {
  const { parseCloudPending } = helpers();
  const original = { project_id: "project-1", operation_key: "web:original-key", expected_version: 3,
    operation: "STORE_CREDENTIAL", digest: "a".repeat(64), state: "UNKNOWN", secret: "synthetic-private-value", payload: { prd: "unselected artifact" } };
  const restored = parseCloudPending(JSON.stringify(original), "project-1");
  assert.equal(restored.operation_key, original.operation_key);
  assert.equal(JSON.stringify(restored).includes("synthetic-private-value"), false);
  assert.equal(JSON.stringify(restored).includes("unselected artifact"), false);
  assert.throws(() => parseCloudPending(JSON.stringify(original), "other-project"));
  assert.throws(() => parseCloudPending(JSON.stringify({ ...original, state: "ACK" }), "project-1"));
  assert.throws(() => parseCloudPending(JSON.stringify({ ...original, digest: "raw-value" }), "project-1"));
});

test("Cloud receipts must retain profile, owner target, original key, operation and accepted version", () => {
  const { cloudReceiptMatches, CLOUD_PROFILE } = helpers();
  const pending = { project_id: "p1", task_id: "t1", operation_key: "original", expected_version: 4, operation: "DISPATCH" };
  const receipt = { status: "ACCEPTED", profile: CLOUD_PROFILE, project_id: "p1", task_id: "t1", operation_key: "original", version: 5, operation: "DISPATCH" };
  assert.equal(cloudReceiptMatches(pending, receipt), true);
  for (const change of [{ status: "UNKNOWN" }, { profile: "codex-session-task-sync/v1alpha1" }, { project_id: "p2" },
    { task_id: "t2" }, { operation_key: "replacement" }, { version: 6 }, { operation: "CREATE_TASK" }]) {
    assert.equal(cloudReceiptMatches(pending, { ...receipt, ...change }), false);
  }
});

test("Denied readback after ACK remains pending instead of permitting a duplicate POST", () => {
  const { canReleaseCloudPending } = helpers();
  assert.equal(canReleaseCloudPending(409, false), true);
  for (const status of [401, 403, 404, 409, 422, 500, 502]) assert.equal(canReleaseCloudPending(status, true), false);
  assert.equal(canReleaseCloudPending(502, false), false);
  for (const status of [408, 425, 429, 499, 503]) assert.equal(canReleaseCloudPending(status, false), false);
});

test("Credential v1 ACK can complete original readback after another authorized rotation to v2", () => {
  const { cloudCredentialReceiptVisible } = helpers();
  const receipt = { operation: "STORE_CREDENTIAL", credential_id: "credential-1", credential_version_id: "version-1", version: 1 };
  const records = { credentials: [{ id: "credential-1", version: 2, status: "ACTIVE" }],
    versions: [{ id: "version-1", credential_id: "credential-1", version: 1 }, { id: "version-2", credential_id: "credential-1", version: 2 }] };
  assert.equal(cloudCredentialReceiptVisible(receipt, records), true);
  assert.equal(cloudCredentialReceiptVisible({ ...receipt, credential_version_id: "missing" }, records), false);
  assert.equal(cloudCredentialReceiptVisible({ ...receipt, credential_id: "other-parent" }, records), false);
  assert.equal(cloudCredentialReceiptVisible({ ...receipt, operation: "REVOKE_CREDENTIAL" }, records), false);
});

test("Operational lease expiry changes the live display without rewriting accepted history", () => {
  const { cloudOperationalView } = helpers();
  const document = { task: { id: "task-1", project_id: "project-1", version: 7, latest_attempt_id: "attempt-1", status: "RUNNING" },
    attempts: [{ id: "attempt-1", status: "RUNNING" }], resolutions: [{ id: "resolution-1", status: "PENDING" }], assets: [{ markdown: "Original FAIL" }] };
  const original = JSON.stringify(document);
  const live = { ...document.task, status: "RECOVERY_REQUIRED", current_attempt: { id: "attempt-1", status: "RECOVERY_REQUIRED", reason: "lease expired" },
    resolutions: [{ id: "resolution-1", status: "RESOLVING" }], observed_at: "2026-10-22T10:00:00Z" };
  const view = cloudOperationalView(document, live);
  assert.equal(view.valid, true);
  assert.equal(view.status, "RECOVERY_REQUIRED");
  assert.equal(view.attempt.reason, "lease expired");
  assert.equal(view.resolutions[0].status, "RESOLVING");
  assert.equal(JSON.stringify(document), original);
  for (const change of [{ project_id: "other-project" }, { id: "other-task" }, { current_attempt: { id: "other-attempt" } }, { version: 6 }]) assert.equal(cloudOperationalView(document, { ...live, ...change }).valid, false);
  const newer = cloudOperationalView(document, { ...live, version: 8 });
  assert.equal(newer.valid, false);
  assert.equal(newer.newerVersion, true);
});

test("Repository selectors reject embedded credentials and freeze complete SHA or explicit MR base", () => {
  const { credentialFreeUrl, cloudSelector } = helpers();
  assert.equal(credentialFreeUrl("https://git.example.org/team/repo.git"), true);
  assert.equal(credentialFreeUrl("ssh://git@git.example.org/team/repo.git"), true);
  for (const url of ["https://token@git.example.org/team/repo", "https://user:secret@git.example.org/team/repo", "file:///tmp/repo", "https://git.example.org/repo?token=secret"]) assert.equal(credentialFreeUrl(url), false);
  assert.equal(cloudSelector("SHA", "a".repeat(40)).value, "a".repeat(40));
  assert.throws(() => cloudSelector("SHA", "abcdef"));
  assert.throws(() => cloudSelector("BRANCH", "--upload-pack=command"));
  assert.throws(() => cloudSelector("MR", "3"));
  assert.throws(() => cloudSelector("MR", "0", "HEAD", "refs/heads/main"));
  assert.equal(cloudSelector("MR", "3", "HEAD", "refs/heads/main").base_ref, "refs/heads/main");
  for (const base of ["--exec=secret", "refs/heads/../main", "main.lock", "refs/heads/main:other", "main@{1}"]) assert.throws(() => cloudSelector("MR", "3", "HEAD", base));
});

const { operationHarness, until, document: completeDocument } = require("./operation-harness.cjs");

test("An old Project response settles only its own key and cannot clear the next Project's pending write", async () => {
  let finish, posts = 0;
  const pendingResponse = new Promise((resolve) => { finish = resolve; });
  const harness = operationHarness({ cloudRequest: async () => { posts++; return pendingResponse; }, cloudDocument: async (project, task, version) => completeDocument(project, task, version) });
  await harness.mount("project-a");
  const submitted = harness.render().submit({ operation: "CREATE_TASK", expected_version: 0 });
  await until(() => posts === 1);
  const [original] = await harness.journal.read("project-a");
  const second = { project_id: "project-b", operation_key: "web:kept-original", expected_version: 2, task_id: "task-b", operation: "DISPATCH", state: "UNKNOWN", digest: "b".repeat(64) };
  await harness.journal.importLegacy(second);
  await harness.mount("project-b");
  finish({ status: "ACCEPTED", profile: harness.client.CLOUD_PROFILE, project_id: "project-a", task_id: "task-a", operation_key: original.operation_key, operation: "CREATE_TASK", version: 1 });
  assert.equal(await submitted, null, "must not navigate back to the previous Project");
  const next = harness.render("project-b");
  assert.equal(next.pending.operation_key, second.operation_key);
  assert.equal((await harness.journal.read("project-a")).length, 0);
  assert.equal((await harness.journal.read("project-b"))[0].operation_key, second.operation_key);
  assert.equal(await next.submit({ operation: "CREATE_TASK", expected_version: 0 }), null);
  assert.equal(posts, 1); harness.close();
});

test("Timeout and NOT_FOUND reconciliation preserve the original key and never repeat a POST", async () => {
  let posts = 0, queried;
  const harness = operationHarness({ cloudRequest: async () => { posts++; throw new harness.client.CloudApiError(408, "timeout"); }, cloudOperation: async (_project, key) => { queried = key; throw new harness.client.CloudApiError(404, "not found"); } });
  await harness.mount("project-a");
  await harness.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  const pending = harness.render();
  assert.equal(pending.pending.state, "UNKNOWN");
  const original = pending.pending.operation_key;
  await pending.reconcile();
  const retained = harness.render();
  assert.equal(queried, original);
  assert.equal(retained.pending.operation_key, original);
  assert.equal(retained.blocked, true);
  assert.equal(posts, 1); harness.close();
});

test("A definitive version rejection keeps the submitted key visible without automatically retrying", async () => {
  let posts = 0;
  const harness = operationHarness({ cloudRequest: async () => { posts++; throw new harness.client.CloudApiError(409, "Refresh the accepted version", "VERSION_CONFLICT"); } });
  await harness.mount("project-a");
  await harness.render().submit({ operation: "RESOLVE_INPUTS", task_id: "task-a", expected_version: 4 });
  const rejected = harness.render();
  assert.equal(rejected.issue, "VERSION_CONFLICT");
  assert.equal(rejected.rejectedOperation.operation_key, "web:operation-one-1");
  assert.equal(rejected.rejectedOperation.expected_version, 4);
  assert.equal(rejected.pending, null);
  assert.equal(posts, 1); harness.close();
});

test("Cancellation uses only the fixed operator fence reason for tasks and attempts", () => {
  const { cloudCancellation } = helpers();
  assert.deepEqual(JSON.parse(JSON.stringify(cloudCancellation())), { operation: "CANCEL_TASK", reason: "OPERATOR_REQUESTED_CANCELLATION" });
  assert.deepEqual(JSON.parse(JSON.stringify(cloudCancellation("attempt-1"))), { operation: "CANCEL_ATTEMPT", attempt_id: "attempt-1", reason: "OPERATOR_REQUESTED_CANCELLATION" });
});

test("Completed task progress never supplies the test-result success tone", () => {
  const { cloudProgressTone } = helpers();
  assert.equal(cloudProgressTone("COMPLETED"), undefined);
  assert.equal(cloudProgressTone("RUNNING"), "blue");
  assert.equal(cloudProgressTone("RECOVERY_REQUIRED"), "gold");
});

function taskPage(status, options = {}) {
  const projectId = "00000000-0000-4000-8000-000000000001", taskId = "00000000-0000-4000-8000-000000000002";
  const attempt = status === "DRAFT" ? null : { id: "attempt-1", attempt_no: 1, status, checkpoint: {}, reason: "MODEL_KEY_UNAVAILABLE" };
  const document = { task: { id: taskId, project_id: projectId, version: 1, config_id: "config-1", title: "Task",
    latest_attempt_id: attempt?.id ?? null, status, reported_result: options.result || "NOT_RUN", inputs: {} },
    attempts: attempt ? [attempt] : [], resolutions: [], questions: [], answers: [], assets: [{ markdown: "Original FAIL" }], runs: [], run_cases: [], artifacts: [], delegations: [] };
  const live = { ...document.task, current_attempt: attempt, resolutions: [], observed_at: "2026-10-23T00:00:00Z" };
  const values = { "cloud-web-setup": { configured: true }, "cloud-capabilities": { enabled: true, worker_enabled: true },
    "cloud-config": { items: [{ id: "config-1", configuration: { environment: { connection: "NONE" }, sut: { url: "https://git.invalid/sut" }, framework: { url: "https://git.invalid/framework" } } }] },
    "cloud-task": document, "cloud-task-live": options.missingLive ? undefined : options.foreignLive ? { ...live, project_id: "other-project" } : live };
  const ui = Object.fromEntries(["Alert", "Button", "Checkbox", "Descriptions", "Space", "Spin", "Steps", "Table", "Tabs", "Tag"].map((name) => [name, name]));
  Object.assign(ui, { Form: { Item: "Form.Item" }, Input: { TextArea: "Input.TextArea" }, Typography: { Title: "Title", Text: "Text", Paragraph: "Paragraph" } });
  let writes = 0;
  const jsx = (type, props) => typeof type === "function" ? type(props) : ({ type, props });
  const original = JSON.stringify(document);
  const page = load("app/cloud-tasks/[taskId]/page.tsx", { require: (name) => {
    if (name === "react") return { useState: (initial) => [initial, () => {}], useEffect() {} };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@ant-design/icons") return { ArrowLeftOutlined: "ArrowLeftOutlined", ReloadOutlined: "ReloadOutlined" };
    if (name === "next/link") return "Link";
    if (name === "next/navigation") return { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams({ projectId }) };
    if (name === "@tanstack/react-query") return { useQuery: ({ queryKey }) => ({ data: values[queryKey[0]], refetch() {}, isError: false }) };
    if (name === "@/lib/cloud") return helpers();
    if (name === "@/lib/cloud-operation") return { useCloudOperation: () => ({ blocked: false, submit() { writes++; throw new Error("render must not write"); } }) };
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en, label: (value) => value }) };
    if (name === "@/app/tasks/task-records") return { ReportedResultTag: "ReportedResultTag" };
    if (name === "@/app/workspace-ui") return {
      WorkspaceHeading: ({ title, description, metadata, actions }) => jsx("header", { children: [jsx("h1", { children: title }), description, metadata, actions] }),
      WorkspaceLoading: "WorkspaceLoading",
    };
    if (name === "@/app/projects/[projectId]/cloud/cloud-shared") return { CloudCapabilitiesNotice: "CloudCapabilitiesNotice", CloudOperationNotice: "CloudOperationNotice" };
    if (name === "./records") return { CloudTaskRecords: "CloudTaskRecords" };
    return require(name);
  } });
  const tree = page.default();
  const nodes = (value) => !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
  const rendered = nodes(tree);
  assert.equal(JSON.stringify(document), original, "a progress projection cannot rewrite accepted history");
  assert.equal(writes, 0);
  return { steps: rendered.find((node) => node.type === "Steps").props,
    result: rendered.find((node) => node.type === "ReportedResultTag").props.result,
    unknown: rendered.some((node) => node.type === "Paragraph" && String(node.props.children).includes("Phase completion is unknown")) };
}

test("Missing live identity and early terminal states show no inferred completed Harness phase", () => {
  for (const [status, options] of [["DRAFT", { missingLive: true }], ["COMPLETED", { foreignLive: true }], ["FAILED", {}], ["CANCELLED", {}], ["RECOVERY_REQUIRED", {}]]) {
    const page = taskPage(status, options);
    assert.equal(page.steps.current, -1);
    assert.equal(page.unknown, true);
    assert.equal(page.result, "NOT_RUN");
  }
});

test("In-flight work stays on Harness work instead of marking it finished without a delivered result", () => {
  for (const status of ["QUEUED", "PREPARING", "RUNNING", "WAITING_INPUT"]) {
    const page = taskPage(status);
    assert.equal(page.steps.items[page.steps.current].title, "Harness work");
    assert.equal(page.unknown, false);
    assert.equal(page.result, "NOT_RUN");
  }
  assert.ok(taskPage("DRAFT").steps.current < taskPage("RUNNING").steps.current);
});

test("A delivered task can reach execution/report while retaining its original reported FAIL", () => {
  const page = taskPage("COMPLETED", { result: "FAIL" });
  assert.equal(page.steps.items[page.steps.current].title, "Execution and report");
  assert.equal(page.result, "FAIL");
  assert.equal(page.unknown, false);
});

test("Browser reconciliation only reads the original key and retains the pending stream", () => {
  const source = fs.readFileSync(path.join(__dirname, "../lib/cloud-operation.ts"), "utf8");
  const reconciliation = source.slice(source.indexOf("async function reconcile"));
  assert.ok(reconciliation.includes("cloudOperation(projectId, original.operation_key)"));
  assert.equal(reconciliation.includes('method: "POST"'), false);
  assert.ok(source.indexOf("await cloudJournal.reserve(candidate)") < source.indexOf('method: "POST"'));
  assert.ok(source.includes("await cloudJournal.markUnknown(original)"));
  assert.ok(source.includes("const { secret: _secret, ...safeIdentity }"));
  assert.equal(source.includes("setInterval"), false);
});

test("Cloud browser client never sets operator credentials or calls legacy execution APIs", async () => {
  const calls = [];
  const api = load("lib/cloud.ts", { fetch: async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ items: [] })); }, URL, TextEncoder });
  await api.cloudDirectory("project value", "CLOUD", 20);
  await api.cloudOperation("project value", "original:key");
  assert.equal(calls[0].url, "/api/cloud/projects/project%20value/task-directory?offset=20&limit=20&product_mode=CLOUD");
  assert.equal(calls[1].url, "/api/cloud/projects/project%20value/operations/original%3Akey");
  for (const call of calls) {
    assert.equal(call.options.headers["X-Hypertest-Operator-Key"], undefined);
    assert.equal(call.options.headers.Authorization, undefined);
    assert.equal(call.options.cache, "no-store");
  }
});
