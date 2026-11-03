const assert = require("node:assert/strict");
const test = require("node:test");
const { IDBFactory, until } = require("./operation-harness.cjs");
const load = require("./load-helper.cjs");
class ApiError extends Error { constructor(status, detail) { super(detail); this.status = status; this.detail = detail; } }
function harness({ factory = new IDBFactory(), send = async () => { throw new TypeError("Lost response"); }, recover = async () => { throw new ApiError(404, "NOT_FOUND"); }, validate = (_, value) => value, unavailable = false } = {}) {
  let cursor = 0, sequence = 0; const slots = [], effects = [], calls = [];
  const react = { useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], (v) => { slots[i] = typeof v === "function" ? v(slots[i]) : v; }]; }, useRef(initial) { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; }, useEffect(effect, deps) { const i = cursor++; if (!slots[i]) { slots[i] = {}; effects.push(() => { slots[i].cleanup = effect(); }); } } };
  const journal = load("lib/operation-journal.ts", { indexedDB: unavailable ? undefined : factory });
  const module = load("lib/archive-operation.ts", { URLSearchParams, require: (name) => name === "react" ? react : name === "@/lib/api" ? { ApiError } : name === "@/lib/operation-journal" ? journal : name === "@/lib/uuid" ? { createUuid: () => `request-${++sequence}` } : name === "@/lib/archive" ? {} : require(name) });
  const render = () => { cursor = 0; const value = module.useLocalWebOperation("archive", "project-a", "task-a", async (...args) => { calls.push(["POST", ...args]); return send(...args); }, async (...args) => { calls.push(["GET", ...args]); return recover(...args); }, validate); while (effects.length) effects.shift()(); return value; };
  const mount = async () => { render(); await until(() => render().ready || render().error); return render(); };
  return { render, mount, calls, factory, module, close() { for (const slot of slots) slot?.cleanup?.(); } };
}
test("archive lost response persists exact input and original-key-only recovery after reopening", async () => {
  const a = harness(); await a.mount();
  await a.render().submit("tasks", (key) => `operations/by-key?idempotency_key=${key}`, { project_id: "project-a", title: "Original FAIL", owner_uploader_actor_ref: null });
  assert.equal(a.render().pending.state, "UNKNOWN"); const original = a.render().pending; a.close();
  const b = harness({ factory: a.factory }); await b.mount(); assert.equal(b.render().pending.payload.title, "Original FAIL");
  await b.render().reconcile(); await b.render().submit("tasks", () => "other", { title: "Changed" });
  assert.equal(b.calls.length, 1); assert.deepEqual(b.calls[0], ["GET", original.recovery_path]); assert.ok(b.render().pending); b.close();
});
test("archive key conflict remains UNKNOWN; unavailable journal sends no POST", async () => {
  const h = harness({ send: async () => { throw new ApiError(409, "ARCHIVE_OPERATION_KEY_CONFLICT"); } }); await h.mount(); await h.render().submit("tasks", (key) => key, {});
  assert.equal(h.render().pending.state, "UNKNOWN"); assert.equal(h.calls.length, 1); h.close();
  const unavailable = harness({ unavailable: true }); await unavailable.mount(); await unavailable.render().submit("tasks", () => "key", {}); assert.equal(unavailable.calls.length, 0); unavailable.close();
});
test("status permission and version rejections settle the request without reporting success", async () => {
  for (const [status, detail] of [[401, "ARCHIVE_OPERATOR_REQUIRED"], [403, "ARCHIVE_OPERATOR_REQUIRED"], [409, "ARCHIVE_TASK_VERSION_CONFLICT"]]) {
    const h = harness({ send: async () => { throw new ApiError(status, detail); } });
    await h.mount();
    const result = await h.render().submit("tasks/task-a/status", (key) => `operations/by-key?idempotency_key=${key}`, { expected_task_version: 7, status: "COMPLETED", reason: "Recorded completion only" });
    assert.equal(result, null);
    assert.equal(h.render().error.detail, detail);
    assert.equal(h.render().pending, null);
    assert.equal(h.calls.length, 1);
    h.close();
  }
});
test("uncertain status save persists the reason and recovers by its original key without another update", async () => {
  const a = harness(); await a.mount();
  const fields = { expected_task_version: 7, status: "COMPLETED", reason: "Keep FAIL and unfinished children" };
  assert.equal(await a.render().submit("tasks/task-a/status", (key) => `operations/by-key?idempotency_key=${key}`, fields), null);
  const frozen = plain(a.render().pending); a.close();
  const accepted = { task: { status: "COMPLETED", reported_result: "FAIL", version: 8 } };
  const b = harness({ factory: a.factory, recover: async () => accepted }); await b.mount();
  assert.deepEqual(plain(b.render().pending), frozen);
  await b.render().submit("tasks/task-a/status", () => "new-key", { ...fields, status: "IN_PROGRESS" });
  assert.equal(b.calls.length, 0, "a new status update cannot bypass an unresolved request");
  assert.equal(await b.render().reconcile(), accepted);
  assert.deepEqual(b.calls, [["GET", frozen.recovery_path]]);
  assert.equal(b.render().pending, null);
  b.close();
});
function plain(value) { return JSON.parse(JSON.stringify(value)); }
test("status ACK verifies the independent action and immutable change-history fields", () => {
  const h = harness();
  for (const reason of [undefined, null, "Original reason\r\n未覆盖事项保持原样"]) {
    const payload = { project_id: "project-a", idempotency_key: "status-key", expected_task_version: 7, status: "COMPLETED", ...(reason !== undefined ? { reason } : {}) };
    const original = { project_id: "project-a", operation_key: "status-key", path: "tasks/task-a/status", payload };
    const result = {
      task: { id: "task-a", project_id: "project-a", version: 8, status: "COMPLETED", reported_result: "FAIL", archive_version: 3 }, subtasks: [],
      receipt: { project_id: "project-a", task_id: "task-a", task_version: 8, idempotency_key: "status-key", operation: "UPDATE_STATUS", actor_ref: "operator:test", created_at: "2026-11-03T00:00:00Z", from_status: "BLOCKED", to_status: "COMPLETED", reason: reason ?? null, request_payload: { operation: "UPDATE_STATUS", task_id: "task-a", request: payload } },
    };
    assert.equal(h.module.validateManagement(original, result).task.reported_result, "FAIL");
    for (const mutate of [
      (v) => { v.receipt.operation = "PUBLISH"; }, (v) => { v.task.status = "IN_PROGRESS"; },
      (v) => { v.receipt.to_status = "CANCELLED"; }, (v) => { v.receipt.from_status = "PASS"; },
      (v) => { v.receipt.reason = "Replaced reason"; }, (v) => { v.receipt.actor_ref = ""; },
      (v) => { delete v.receipt.created_at; }, (v) => { v.publication = { id: "unrequested-publication" }; },
      (v) => { v.receipt.request_payload.request.reason = "Changed frozen request"; },
    ]) {
      const changed = structuredClone(result); mutate(changed);
      assert.throws(() => h.module.validateManagement(original, changed), /RECEIPT_MISMATCH/);
    }
  }
});
test("publication ACK still verifies the explicitly published result, summary and version vector", () => {
  const h = harness();
  const payload = { project_id: "project-a", idempotency_key: "publish-key", expected_task_version: 7, status: "COMPLETED", reported_result: "FAIL", summary: "Scope unchanged\n未完成性能测试", root_archive_version: 3, subtask_versions: [{ subtask_id: "child", archive_version: 2 }], asset_revision_ids: ["report"] };
  const original = { project_id: "project-a", operation_key: "publish-key", path: "tasks/task-a/publications", payload };
  const result = { task: { id: "task-a", project_id: "project-a", version: 8, archive_version: 3, status: "COMPLETED", reported_result: "FAIL" }, subtasks: [], publication: { ...payload, task_version: 8 }, receipt: { project_id: "project-a", task_id: "task-a", task_version: 8, idempotency_key: "publish-key", operation: "PUBLISH", request_payload: { operation: "PUBLISH", task_id: "task-a", request: payload } } };
  assert.equal(h.module.validateManagement(original, result).publication.summary, payload.summary);
  for (const mutate of [(v) => { delete v.publication; }, (v) => { v.task.reported_result = "PASS"; }, (v) => { v.publication.summary = ""; }, (v) => { v.publication.asset_revision_ids = []; }, (v) => { v.publication.subtask_versions = []; }]) {
    const changed = structuredClone(result); mutate(changed); assert.throws(() => h.module.validateManagement(original, changed), /RECEIPT_MISMATCH/);
  }
});
test("archive ACK is not accepted when frozen receipt or version is inconsistent", () => {
  const h = harness(); const original = { project_id: "project-a", operation_key: "original", path: "tasks", payload: { project_id: "project-a", idempotency_key: "original", title: "Literal", objective: "Original", owner_uploader_actor_ref: null } };
  const result = { task: { id: "task-a", project_id: "project-a", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN", title: "Literal", objective: "Original", owner_uploader_actor_ref: null }, subtasks: [], receipt: { project_id: "project-a", task_id: "task-a", task_version: 1, idempotency_key: "original", operation: "CREATE", request_payload: { operation: "CREATE", task_id: null, request: original.payload } } };
  assert.equal(h.module.validateManagement(original, result).task.title, "Literal");
  for (const mutate of [(v) => { v.receipt.idempotency_key = "other"; }, (v) => { v.task.version = 2; }, (v) => { v.task.title = "Tampered"; }, (v) => { v.receipt.request_payload.request.owner_uploader_actor_ref = "other"; }]) {
    const changed = structuredClone(result); mutate(changed); assert.throws(() => h.module.validateManagement(original, changed), /RECEIPT_MISMATCH/);
  }
});
test("local task ACK checks the branch values from the original request", () => {
  const h = harness(); const payload = { project_id: "project-a", idempotency_key: "original", title: "Task", objective: "Objective", owner_uploader_actor_ref: null, sut_branch: "feature/a", framework_branch: "tests/a", expected_project_version: 7 };
  const original = { project_id: "project-a", operation_key: "original", path: "tasks", payload };
  const result = { task: { id: "task-a", project_id: "project-a", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN", title: "Task", objective: "Objective", owner_uploader_actor_ref: null, sut_branch: "feature/a", framework_branch: "tests/a" }, subtasks: [], receipt: { project_id: "project-a", task_id: "task-a", task_version: 1, idempotency_key: "original", operation: "CREATE", request_payload: { operation: "CREATE", task_id: null, request: payload } } };
  assert.equal(h.module.validateManagement(original, result).task.sut_branch, "feature/a");
  result.task.sut_branch = "other";
  assert.throws(() => h.module.validateManagement(original, result), /RECEIPT_MISMATCH/);
});
test("local task ACK checks an explicitly requested owner while allowing server assignment when omitted", () => {
  const h = harness();
  for (const owner of [undefined, null, "interactive:actor"]) {
    const payload = { project_id: "project-a", idempotency_key: "original", title: "Task", objective: "Objective", ...(owner === undefined ? {} : { owner_uploader_actor_ref: owner }) };
    const original = { project_id: "project-a", operation_key: "original", path: "tasks", payload };
    const assigned = owner === undefined ? "interactive:assigned" : owner;
    const result = { task: { id: "task-a", project_id: "project-a", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN", title: "Task", objective: "Objective", owner_uploader_actor_ref: assigned }, subtasks: [], receipt: { project_id: "project-a", task_id: "task-a", task_version: 1, idempotency_key: "original", operation: "CREATE", request_payload: { operation: "CREATE", task_id: null, request: structuredClone(payload) } } };
    assert.equal(h.module.validateManagement(original, result).task.owner_uploader_actor_ref, assigned);
    const alteredReceipt = structuredClone(result); alteredReceipt.receipt.request_payload.request.owner_uploader_actor_ref = "interactive:tampered";
    assert.throws(() => h.module.validateManagement(original, alteredReceipt), /RECEIPT_MISMATCH/);
    if (owner !== undefined) {
      result.task.owner_uploader_actor_ref = owner === null ? "interactive:other" : null;
      assert.throws(() => h.module.validateManagement(original, result), /RECEIPT_MISMATCH/);
    }
  }
});
test("CLI approval freezes project permissions and retains exact identity checks for earlier receipts", () => {
  const client = load("lib/cli-authorization.ts", { require: () => ({ ApiError }) });
  for (const legacy of [false, true]) {
    const actor = legacy ? "00000000-0000-4000-8000-000000000001" : "00000000-0000-4000-8000-000000000002";
    const original = { path: "requests/pairing/approve", operation_key: "original", payload: { ...(legacy ? { actor_identity_id: actor } : {}), project_ids: ["p1"], scopes: ["archive:read", "archive:write"], expires_in_days: 7, short_code: "123456" } };
    const value = { request_id: "pairing", status: "APPROVED", short_code: "123456", approval: { idempotency_key: "original", actor_identity_id: actor, actor_ref: `interactive:${actor}`, ...original.payload } };
    assert.equal(client.validateCliApproval(original, value).status, "APPROVED");
    for (const field of ["project_ids", "expires_in_days", "scopes", "idempotency_key", ...(legacy ? ["actor_identity_id"] : [])]) {
      const changed = structuredClone(value); changed.approval[field] = field === "project_ids" ? ["p1", "p2"] : "changed"; assert.throws(() => client.validateCliApproval(original, changed), /RECEIPT_MISMATCH/);
    }
    for (const field of ["request_id", "short_code", "status"]) {
      const changed = structuredClone(value); changed[field] = "changed"; assert.throws(() => client.validateCliApproval(original, changed), /RECEIPT_MISMATCH/);
    }
    for (const mutate of [(a) => { delete a.actor_identity_id; }, (a) => { a.actor_identity_id = "not-a-uuid"; }, (a) => { delete a.actor_ref; }, (a) => { a.actor_ref = "interactive:another-actor"; }]) {
      const changed = structuredClone(value); mutate(changed.approval); assert.throws(() => client.validateCliApproval(original, changed), /RECEIPT_MISMATCH/);
    }
  }
  assert.throws(() => client.validateCliRevocation({ path: "grants/g/revoke", operation_key: "original" }, { grant_id: "g", status: "REVOKED", idempotency_key: "other" }), /RECEIPT_MISMATCH/);
});
test("global CLI approval and revocation verify their original receipts", () => {
  const client = load("lib/cli-authorization.ts", { require: () => ({ ApiError }) });
  const actor = "00000000-0000-4000-8000-000000000001";
  const original = { path: "requests/pairing/approve", operation_key: "original", payload: { all_projects: true, project_ids: [], scopes: ["archive:read", "archive:write"], expires_in_days: null, short_code: "123456" } };
  const value = { request_id: "pairing", status: "APPROVED", short_code: "123456", approval: { idempotency_key: "original", actor_identity_id: actor, actor_ref: `interactive:${actor}`, ...original.payload } };
  assert.equal(client.validateCliApproval(original, value).status, "APPROVED");
  for (const [field, replacement] of [["all_projects", false], ["expires_in_days", 30], ["project_ids", ["p1"]]]) {
    const changed = structuredClone(value); changed.approval[field] = replacement;
    assert.throws(() => client.validateCliApproval(original, changed), /RECEIPT_MISMATCH/);
  }
  const revoke = { path: "requests/pairing/revoke", operation_key: "original" };
  const revoked = { request_id: "pairing", status: "REVOKED", idempotency_key: "original" };
  assert.equal(client.validateCliGlobalRevocation(revoke, revoked).status, "REVOKED");
  for (const field of ["request_id", "status", "idempotency_key"]) {
    assert.throws(() => client.validateCliGlobalRevocation(revoke, { ...revoked, [field]: "other" }), /RECEIPT_MISMATCH/);
  }
});
