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
test("archive ACK is not accepted when frozen receipt or version is inconsistent", () => {
  const h = harness(); const original = { project_id: "project-a", operation_key: "original", path: "tasks", payload: { project_id: "project-a", idempotency_key: "original", title: "Literal", objective: "Original", owner_uploader_actor_ref: null } };
  const result = { task: { id: "task-a", project_id: "project-a", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN", title: "Literal", objective: "Original", owner_uploader_actor_ref: null }, subtasks: [], receipt: { project_id: "project-a", task_id: "task-a", task_version: 1, idempotency_key: "original", operation: "CREATE", request_payload: { operation: "CREATE", task_id: null, request: original.payload } } };
  assert.equal(h.module.validateManagement(original, result).task.title, "Literal");
  for (const mutate of [(v) => { v.receipt.idempotency_key = "other"; }, (v) => { v.task.version = 2; }, (v) => { v.task.title = "Tampered"; }, (v) => { v.receipt.request_payload.request.owner_uploader_actor_ref = "other"; }]) {
    const changed = structuredClone(result); mutate(changed); assert.throws(() => h.module.validateManagement(original, changed), /RECEIPT_MISMATCH/);
  }
});
test("CLI approval receipt cannot widen projects or replace identity; revocation needs its original key", () => {
  const client = load("lib/cli-authorization.ts", { require: () => ({ ApiError }) });
  const original = { path: "requests/pairing/approve", operation_key: "original", payload: { actor_identity_id: "actor", project_ids: ["p1"], scopes: ["archive:read", "archive:write"], expires_in_days: 7, short_code: "123456" } };
  const value = { request_id: "pairing", status: "APPROVED", short_code: "123456", approval: { idempotency_key: "original", ...original.payload } };
  assert.equal(client.validateCliApproval(original, value).status, "APPROVED");
  for (const field of ["actor_identity_id", "project_ids", "expires_in_days", "scopes", "idempotency_key"]) {
    const changed = structuredClone(value); changed.approval[field] = field === "project_ids" ? ["p1", "p2"] : "changed"; assert.throws(() => client.validateCliApproval(original, changed), /RECEIPT_MISMATCH/);
  }
  assert.throws(() => client.validateCliRevocation({ path: "grants/g/revoke", operation_key: "original" }, { grant_id: "g", status: "REVOKED", idempotency_key: "other" }), /RECEIPT_MISMATCH/);
});
