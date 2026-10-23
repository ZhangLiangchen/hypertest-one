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

test("Browser reconciliation only reads the original key and retains the pending stream", () => {
  const source = fs.readFileSync(path.join(__dirname, "../lib/cloud-operation.ts"), "utf8");
  const reconciliation = source.slice(source.indexOf("async function reconcile"));
  assert.ok(reconciliation.includes("cloudOperation(projectId, current.current.operation_key)"));
  assert.equal(reconciliation.includes('method: "POST"'), false);
  assert.ok(source.indexOf("save(original)") < source.indexOf('method: "POST"'));
  assert.ok(source.includes('state: "UNKNOWN"'));
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
