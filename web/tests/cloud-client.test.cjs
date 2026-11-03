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
  assert.equal(credentialFreeUrl("ssh://alice@git.example.org/team/repo.git"), true);
  assert.equal(credentialFreeUrl("git@git.example.org:team/repo.git"), true);
  for (const url of ["https://token@git.example.org/team/repo", "https://user:secret@git.example.org/team/repo", "ssh://git:secret@git.example.org/team/repo", "ssh://git:@git.example.org/team/repo", "git@git.example.org:repo with spaces", "git.example.org:team/repo", "file:/tmp/repo", "file:///tmp/repo", "https://git.example.org/repo?token=secret"]) assert.equal(credentialFreeUrl(url), false);
  assert.equal(cloudSelector("SHA", "a".repeat(40)).value, "a".repeat(40));
  assert.throws(() => cloudSelector("SHA", "abcdef"));
  assert.throws(() => cloudSelector("BRANCH", "--upload-pack=command"));
  assert.throws(() => cloudSelector("MR", "3"));
  assert.throws(() => cloudSelector("MR", "0", "HEAD", "refs/heads/main"));
  assert.equal(cloudSelector("MR", "3", "HEAD", "refs/heads/main").base_ref, "refs/heads/main");
  for (const base of ["--exec=secret", "refs/heads/../main", "main.lock", "refs/heads/main:other", "main@{1}"]) assert.throws(() => cloudSelector("MR", "3", "HEAD", base));
});

const { operationHarness, until, document: completeDocument } = require("./operation-harness.cjs");

test("Delete remains pending until its original receipt reads back a tombstone", async () => {
  let tombstone = false, posts = 0, receipt;
  const harness = operationHarness({
    cloudRequest: async (_path, init) => {
      posts++;
      const payload = JSON.parse(init.body);
      receipt = { status: "ACCEPTED", profile: harness.client.CLOUD_PROFILE, project_id: payload.project_id,
        task_id: payload.task_id, operation_key: payload.operation_key, operation: payload.operation, version: payload.expected_version + 1 };
      return receipt;
    },
    cloudOperation: async () => receipt,
    cloudDocument: async (project, task, version) => {
      const document = completeDocument(project, task, version);
      if (tombstone) document.task.deleted_at = "2026-10-30T00:00:00Z";
      return document;
    },
  });
  await harness.mount("project-a");
  assert.equal(await harness.render().submit({ operation: "DELETE_TASK", task_id: "task-a", expected_version: 4 }), null);
  const pending = harness.render().pending;
  assert.equal(pending.state, "UNKNOWN");
  tombstone = true;
  assert.equal((await harness.render().reconcile()).operation_key, pending.operation_key);
  assert.equal((await harness.journal.read("project-a")).length, 0);
  assert.equal(posts, 1);
  harness.close();
});

for (const operation of ["DISPATCH", "START_TASK"]) test(`${operation} keeps its original key until the accepted attempt and digest read back`, async () => {
  let phase = "missing", posts = 0, receipt;
  const digest = "a".repeat(64);
  const harness = operationHarness({
    cloudRequest: async (_path, init) => {
      posts++;
      const payload = JSON.parse(init.body);
      receipt = { status: "ACCEPTED", profile: harness.client.CLOUD_PROFILE, project_id: payload.project_id,
        task_id: payload.task_id, operation_key: payload.operation_key, operation: payload.operation,
        version: payload.expected_version + 1, attempt_id: "attempt-a", input_digest: digest };
      return receipt;
    },
    cloudOperation: async () => receipt,
    cloudDocument: async (project, task, version) => {
      const document = completeDocument(project, task, version);
      document.task.latest_attempt_id = phase === "wrong-current" ? "attempt-b" : "attempt-a";
      if (phase !== "missing") document.attempts.push({ id: phase === "wrong-attempt" ? "attempt-b" : "attempt-a",
        input_digest: phase === "wrong-digest" ? "b".repeat(64) : digest });
      return document;
    },
  });
  await harness.mount("project-a");
  assert.equal(await harness.render().submit({ operation, task_id: "task-a", expected_version: 4 }), null);
  const key = harness.render().pending.operation_key;
  for (const state of ["wrong-attempt", "wrong-digest", "wrong-current"]) {
    phase = state;
    assert.equal(await harness.render().reconcile(), null);
    assert.equal(harness.render().pending.operation_key, key);
    assert.equal(harness.render().blocked, true);
  }
  phase = "ready";
  assert.equal((await harness.render().reconcile()).operation_key, key);
  assert.equal((await harness.journal.read("project-a")).length, 0);
  assert.equal(posts, 1);
  harness.close();
});

test("Start preparation reconciles its original resolution without submitting another start", async () => {
  let phase = "missing", posts = 0, receipt;
  const harness = operationHarness({
    cloudRequest: async (_path, init) => {
      posts++;
      const payload = JSON.parse(init.body);
      receipt = { status: "ACCEPTED", profile: harness.client.CLOUD_PROFILE, project_id: payload.project_id,
        task_id: payload.task_id, operation_key: payload.operation_key, operation: payload.operation,
        version: payload.expected_version + 1, resolution_id: "resolution-a", start_requested: true };
      return receipt;
    },
    cloudOperation: async () => receipt,
    cloudDocument: async (project, task, version) => {
      const document = completeDocument(project, task, version);
      document.task.status = "DRAFT";
      if (phase !== "missing") document.resolutions.push({ id: "resolution-a", status: "PENDING",
        operation_key: phase === "wrong-key" ? "other" : receipt.operation_key,
        source_draft_version: phase === "wrong-version" ? version - 1 : version });
      return document;
    },
  });
  await harness.mount("project-a");
  assert.equal(await harness.render().submit({ operation: "START_TASK", task_id: "task-a", expected_version: 4 }), null);
  const key = harness.render().pending.operation_key;
  for (const state of ["wrong-key", "wrong-version"]) {
    phase = state;
    assert.equal(await harness.render().reconcile(), null);
    assert.equal(harness.render().pending.operation_key, key);
  }
  phase = "ready";
  assert.equal((await harness.render().reconcile()).operation_key, key);
  assert.equal((await harness.journal.read("project-a")).length, 0);
  assert.equal(posts, 1);
  harness.close();
});

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
    latest_attempt_id: attempt?.id ?? null, status, reported_result: options.result || "NOT_RUN", inputs: {}, deleted_at: options.deletedAt },
    attempts: attempt ? [attempt] : [], resolutions: [], questions: [], answers: [], assets: [{ markdown: "Original FAIL" }], runs: [], run_cases: [], artifacts: [], delegations: [] };
  const live = { ...document.task, version: options.liveVersion || document.task.version, current_attempt: attempt, resolutions: options.resolutions || [], management: options.management, observed_at: "2026-10-23T00:00:00Z" };
  const values = { "cloud-web-setup": { configured: true }, "cloud-capabilities": { enabled: true, worker_enabled: true },
    project: { id: projectId, row_version: 1, repository_url: "https://git.invalid/sut", test_framework_repository_url: "https://git.invalid/framework" },
    "cloud-task": document, "cloud-task-live": options.missingLive ? undefined : options.foreignLive ? { ...live, project_id: "other-project" } : live };
  const ui = Object.fromEntries(["Alert", "Button", "Checkbox", "Descriptions", "Space", "Spin", "Steps", "Table", "Tabs", "Tag"].map((name) => [name, name]));
  Object.assign(ui, { Form: { Item: "Form.Item" }, Input: { TextArea: "Input.TextArea" }, Typography: { Title: "Title", Text: "Text", Paragraph: "Paragraph" } });
  let writes = 0; const queries = {}; const effects = []; const reads = []; const stateUpdates = [];
  let hookIndex = 0; const hookValues = [];
  const jsx = (type, props) => typeof type === "function" ? type(props) : ({ type, props });
  const original = JSON.stringify(document);
  const page = load("app/cloud-tasks/[taskId]/page.tsx", { require: (name) => {
    if (name === "react") return { useState(initial) {
      const index = hookIndex++;
      if (!(index in hookValues)) hookValues[index] = initial;
      return [hookValues[index], (value) => { hookValues[index] = value; stateUpdates.push(value); }];
    }, useEffect(effect) { effects.push(effect); } };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@ant-design/icons") return { ArrowLeftOutlined: "ArrowLeftOutlined", ReloadOutlined: "ReloadOutlined" };
    if (name === "next/link") return "Link";
    if (name === "next/navigation") return { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams({ projectId }) };
    if (name === "@tanstack/react-query") return { useQuery: (queryOptions) => { queries[queryOptions.queryKey[0]] = queryOptions; return { data: values[queryOptions.queryKey[0]], dataUpdatedAt: 1, refetch() { reads.push(queryOptions.queryKey[0]); }, isError: options.liveError === true && queryOptions.queryKey[0] === "cloud-task-live" }; } };
    if (name === "@/lib/api") return { getProject() {} };
    if (name === "@/lib/cloud") return { ...helpers(), ...(options.cloudDocument ? { cloudDocument: options.cloudDocument } : {}) };
    if (name === "@/lib/run-polling") return load("lib/run-polling.ts", { require });
    if (name === "@/lib/cloud-operation") return { useCloudOperation: () => ({ blocked: false, submit(fields) { writes++; if (options.submit) return options.submit(fields); throw new Error("render must not write"); } }) };
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en, label: (value) => value }) };
    if (name === "@/app/tasks/task-records") return { ReportedResultTag: "ReportedResultTag" };
    if (name === "@/app/workspace-ui") return {
      WorkspaceHeading: ({ title, description, metadata, actions }) => jsx("header", { children: [jsx("h1", { children: title }), description, metadata, actions] }),
      WorkspaceLoading: "WorkspaceLoading",
    };
    if (name === "@/app/projects/[projectId]/cloud/cloud-shared") return { CloudCapabilitiesNotice: "CloudCapabilitiesNotice", CloudOperationNotice: "CloudOperationNotice", CloudAttemptRecovery: "CloudAttemptRecovery" };
    if (name === "@/app/projects/[projectId]/cloud/task-form") return { CloudTaskForm: "CloudTaskForm" };
    if (name === "./records") return { CloudTaskRecords: "CloudTaskRecords" };
    if (name === "./live-questions-panel") return { LiveQuestionsPanel: "LiveQuestionsPanel" };
    if (name === "./delete-task") return { CloudTaskDelete: "CloudTaskDelete" };
    if (name === "./retry-dialog") return { RetryDialog: "RetryDialog" };
    return require(name);
  } });
  const render = () => { hookIndex = 0; return page.default(); };
  const tree = render();
  const nodes = (value) => !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children), ...nodes(value.props?.items), ...nodes(value.children)];
  const rendered = nodes(tree);
  assert.equal(JSON.stringify(document), original, "a progress projection cannot rewrite accepted history");
  assert.equal(writes, 0);
  return { queries, effects, reads, stateUpdates, document, live, rendered, rerender: () => nodes(render()), recovery: rendered.find((node) => node.type === "CloudAttemptRecovery")?.props, steps: rendered.find((node) => node.type === "Steps").props,
    result: rendered.find((node) => node.type === "ReportedResultTag").props.result,
    unknown: rendered.some((node) => String(node.props?.children).includes("Phase completion is unknown")) };
}

const retryManagement = { can_retry: true, retry_blocking_reasons: [], can_delete: true, delete_blocking_reasons: [], native_scope_unobserved: true };
const newAttemptButton = (rendered) => rendered.find((node) => node.type === "Button" && node.props.children === "Start new attempt");

test("Completed reported FAIL, failed and cancelled attempts can dispatch an explicitly confirmed new attempt", async () => {
  for (const status of ["COMPLETED", "FAILED", "CANCELLED"]) {
    const submitted = [];
    const page = taskPage(status, { result: "FAIL", management: retryManagement, submit: async (fields) => { submitted.push(fields); return null; } });
    const button = newAttemptButton(page.rendered);
    assert.equal(button.props.disabled, false);
    button.props.onClick();
    assert.equal(submitted.length, 0, "opening the review dialog never dispatches");
    const dialog = page.rerender().find((node) => node.type === "RetryDialog");
    assert.equal(dialog.props.invalid, false);
    const freshInputs = { objective: "New scope", test_scope: "Read-only", basic_flow: "New steps", authorization: { targets: ["https://git.invalid/sut"], permitted_actions: ["git:read"], side_effect_limits: "No writes" } };
    dialog.props.onSubmit(freshInputs);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(submitted.length, 1);
    assert.equal(submitted[0].operation, "DISPATCH");
    assert.equal(submitted[0].retry_of_attempt_id, "attempt-1");
    assert.equal(submitted[0].expected_version, 1);
    assert.equal(submitted[0].retry_scope_confirmed, true);
    assert.equal(submitted[0].retry_authorization_confirmed, true);
    assert.equal(submitted[0].retry_inputs, freshInputs);
    assert.equal(page.document.task.reported_result, "FAIL");
  }
});

test("Retry controls require current server admission and refuse a forced stale dialog submit", () => {
  for (const options of [{}, { management: { ...retryManagement, can_retry: false, retry_blocking_reasons: ["PENDING_ORIGINAL_OPERATIONS"] } },
    { management: retryManagement, liveError: true }, { management: retryManagement, liveVersion: 2 },
    { management: retryManagement, deletedAt: "2026-11-03T00:00:00Z" }]) {
    const page = taskPage("COMPLETED", options);
    const button = newAttemptButton(page.rendered);
    if (button) { assert.equal(button.props.disabled, true); button.props.onClick(); }
    assert.equal(page.rerender().some((node) => node.type === "RetryDialog"), false);
  }
  for (const status of ["DRAFT", "RUNNING", "RECOVERY_REQUIRED", "WAITING_INPUT"]) {
    assert.equal(newAttemptButton(taskPage(status, { management: retryManagement }).rendered), undefined);
  }
  const submitted = [];
  const page = taskPage("COMPLETED", { management: { ...retryManagement }, submit: async (fields) => submitted.push(fields) });
  newAttemptButton(page.rendered).props.onClick();
  page.live.management.can_retry = false;
  page.live.management.retry_blocking_reasons = ["PENDING_ORIGINAL_OPERATIONS"];
  const dialog = page.rerender().find((node) => node.type === "RetryDialog");
  assert.equal(dialog.props.invalid, true);
  dialog.props.onSubmit({});
  assert.equal(submitted.length, 0);
});

test("Removed task pages preserve manual reconciliation while refusing new task work", async () => {
  const submitted = [];
  const page = taskPage("RECOVERY_REQUIRED", { deletedAt: "2026-11-03T00:00:00Z", submit: async (fields) => { submitted.push(fields); return null; } });
  assert.equal(page.recovery.blocked, false);
  assert.ok(page.rendered.some((node) => node.type === "Alert" && node.props.message === "Removed from the task list"));
  for (const operation of ["DISPATCH", "CANCEL_ATTEMPT", "ANSWER_INPUT", "DELETE_TASK"]) {
    await page.recovery.onSubmit({ operation, attempt_id: "attempt-1" });
  }
  assert.equal(submitted.length, 0);
  await page.recovery.onSubmit({ operation: "RECONCILE_ATTEMPT", attempt_id: "attempt-1", status: "CANCELLED" });
  assert.equal(submitted.length, 1);
  assert.equal(submitted[0].expected_version, 1);
  assert.equal(submitted[0].operation, "RECONCILE_ATTEMPT");
  assert.equal(taskPage("RECOVERY_REQUIRED", { deletedAt: "2026-11-03T00:00:00Z", liveError: true }).recovery.blocked, true);
});

test("Missing live identity and early terminal states show no inferred completed Harness phase", () => {
  for (const [status, options] of [["DRAFT", { missingLive: true }], ["COMPLETED", { foreignLive: true }], ["FAILED", {}], ["CANCELLED", {}], ["RECOVERY_REQUIRED", {}]]) {
    const page = taskPage(status, options);
    assert.equal(page.steps.current, -1);
    assert.equal(page.unknown, true);
    assert.equal(page.result, "NOT_RUN");
  }
});

test("Workflow links navigate to their matching task sections without submitting work", () => {
  const page = taskPage("DRAFT");
  const links = page.steps.items.map((item) => item.title.props.children);
  assert.equal(links.length, 5);
  const destinations = [["overview", "cloud-task-inputs"], ["overview", "cloud-task-resolution"],
    ["attempts", "cloud-attempt-history-heading"], ["artifacts", "cloud-assets-title"], ["artifacts", "cloud-runs-title"]];
  destinations.forEach(([tab, id], index) => {
    const link = links[index]; let prevented = false;
    assert.equal(link.props.href, `#${id}`);
    link.props.onClick({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    const [selectedTab, target] = page.stateUpdates.splice(0);
    assert.equal(selectedTab, tab);
    assert.equal(target.tab, tab);
    assert.equal(target.id, id);
  });
});

test("In-flight work stays on Harness work instead of marking it finished without a delivered result", () => {
  for (const status of ["QUEUED", "PREPARING", "RUNNING", "WAITING_INPUT"]) {
    const page = taskPage(status);
    assert.equal(page.steps.items[page.steps.current].title.props.children.props.children, "Harness work");
    assert.equal(page.unknown, false);
    assert.equal(page.result, "NOT_RUN");
  }
  assert.ok(taskPage("DRAFT").steps.current < taskPage("RUNNING").steps.current);
});

test("A delivered task can reach execution/report while retaining its original reported FAIL", () => {
  const page = taskPage("COMPLETED", { result: "FAIL" });
  assert.equal(page.steps.items[page.steps.current].title.props.children.props.children, "Execution and report");
  assert.equal(page.result, "FAIL");
  assert.equal(page.unknown, false);
  assert.equal(page.steps.items.filter((item) => item.title.props["aria-current"] === "step").length, 1);
  assert.equal(page.steps.items[page.steps.current].title.props["aria-current"], "step");
  assert.equal(taskPage("COMPLETED", { result: "PASS" }).result, "PASS");
});

test("Workflow colors reflect recorded facts without inferring phase completion", () => {
  const tones = (page) => Array.from(page.steps.items, (item) => item.icon.props.className);
  const running = tones(taskPage("RUNNING"));
  assert.match(running[2], /cloud-flow-active/);
  assert.match(running[3], /cloud-flow-unknown/);
  assert.match(running[4], /cloud-flow-unknown/);
  assert.match(tones(taskPage("WAITING_INPUT"))[2], /cloud-flow-waiting/);
  assert.match(tones(taskPage("COMPLETED", { result: "FAIL" }))[4], /cloud-flow-failed/);
  assert.match(tones(taskPage("COMPLETED", { result: "PASS" }))[4], /cloud-flow-complete/);
  assert.match(tones(taskPage("COMPLETED", { result: "PASS" }))[3], /cloud-flow-complete/);
  assert.match(tones(taskPage("COMPLETED", { result: "PASS", liveError: true }))[3], /cloud-flow-unknown/);
  assert.match(tones(taskPage("FAILED"))[2], /cloud-flow-unknown/);
  assert.match(tones(taskPage("DRAFT", { resolutions: [{ status: "FAILED", source_draft_version: 1 }] }))[1], /cloud-flow-failed/);
  assert.match(tones(taskPage("DRAFT", { resolutions: [{ status: "FAILED", source_draft_version: 0 }] }))[1], /cloud-flow-unknown/);
  assert.match(tones(taskPage("RUNNING", { liveError: true }))[2], /cloud-flow-unknown/);
});

test("A failed live refresh does not present an old phase as current", () => {
  const page = taskPage("RUNNING", { liveError: true });
  assert.equal(page.steps.current, -1);
  assert.equal(page.steps.items.filter((item) => item.title.props["aria-current"] === "step").length, 0);
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


test("Cloud detail only schedules summary polls and reads a complete newer version once observed", async () => {
  const calls = [];
  const page = taskPage("RUNNING", { liveVersion: 2, cloudDocument: async (projectId, taskId, version) => {
    calls.push({ projectId, taskId, version });
    return { task: { ...page.live }, assets: [{ markdown: "Original FAIL" }] };
  } });
  assert.equal(page.queries["cloud-task"].refetchInterval, undefined, "complete records have no periodic timer");
  assert.equal(page.queries["cloud-task-live"].refetchInterval({ state: { data: page.live } }), 3000);
  assert.equal(page.reads.length, 0);
  page.effects.forEach((effect) => effect());
  assert.deepEqual(page.reads, ["cloud-task"], "observing a greater accepted version requests a full readback");
  const accepted = await page.queries["cloud-task"].queryFn();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].version, 2);
  assert.equal(accepted.task.version, 2);
  assert.equal(page.document.task.version, 1, "the previous verified document stays unchanged until the complete read succeeds");
});

test("same-version lease observations and foreign Projects cannot trigger complete Cloud reads", () => {
  for (const options of [{}, { foreignLive: true }]) {
    const page = taskPage("RUNNING", options);
    page.effects.forEach((effect) => effect());
    assert.deepEqual(page.reads, []);
  }
});


test("retired CONFIGURE reconciles the original accepted revision without issuing a new write", async () => {
  const pending = { project_id: "project-a", operation_key: "web:retired-config", operation: "CONFIGURE", expected_version: 2, digest: "a".repeat(64), state: "UNKNOWN" };
  let recorded = false, posts = 0;
  const session = new Map([["hypertest:cloud:pending:project-a", JSON.stringify(pending)]]);
  const harness = operationHarness({
    cloudRequest: async () => { posts++; throw Error("must not write"); },
    cloudOperation: async (project, key) => ({ status: "ACCEPTED", profile: "cloud-harness-task/v1alpha1", project_id: project, operation_key: key, operation: "CONFIGURE", version: 3, config_id: "original-revision" }),
    legacyCloudConfigurationReadback: async () => ({ items: recorded ? [{ id: "original-revision", revision: 3 }] : [] }),
  }, { session });
  await harness.mount("project-a");
  assert.equal(await harness.render().reconcile(), null);
  assert.equal(harness.render().pending.operation_key, pending.operation_key);
  recorded = true;
  assert.equal((await harness.render().reconcile()).operation_key, pending.operation_key);
  assert.equal(harness.render().pending, null);
  assert.equal(posts, 0);
  harness.close();
});
