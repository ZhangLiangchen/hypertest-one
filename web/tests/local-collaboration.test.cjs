const assert = require("node:assert/strict");
const test = require("node:test");
const { operationHarness, until, IDBFactory } = require("./operation-harness.cjs");
const profile = "local-task-collaboration/v1alpha1";
const request = { profile, operation: "AUTHORIZE", expected_version: 4, idempotency_key: "original-key", actor_ref: "owner-a", provider: "codex", session_id: "real-root-b", assignment: "API failure review" };
const receipt = (payload = request) => ({ status: "ACCEPTED", profile, operation: payload.operation, idempotency_key: payload.idempotency_key, project_id: "project-a", task_id: "task-a", provider: null, session_id: null, actor_ref: "web-operator", participant_id: null, version: payload.expected_version + 1, request_digest: "a".repeat(64), primary_generation: payload.operation === "HANDOFF" ? 2 : 1, contribution_refs: [] });
function document(payload = request) {
  const ack = receipt(payload), primary = payload.operation === "HANDOFF" ? "participant-b" : "participant-a";
  return { profile, task: { id: "task-a", project_id: "project-a", version: ack.version, title: "Task", objective: "Objective", plan_markdown: "Plan", status: "IN_PROGRESS", reported_result: "FAIL", created_at: "time", provider: "codex", session_id: "initial-root", source: "sdk", collaboration_enabled: true, primary_participant_id: primary, primary_generation: ack.primary_generation }, collaboration: { enabled: true, primary_participant_id: primary, primary_generation: ack.primary_generation, participants: [{ id: "participant-b", actor_ref: "owner-a", provider: "codex", session_id: "real-root-b", assignment: request.assignment, role: payload.operation === "HANDOFF" ? "PRIMARY" : "CONTRIBUTOR", status: payload.operation === "HANDOFF" ? "ACTIVE" : "AUTHORIZED" }], contributions: [], publications: [] }, operation_history: [{ id: "operation-a", task_id: "task-a", project_id: "project-a", operation: payload.operation, idempotency_key: payload.idempotency_key, task_version: ack.version, input_digest: ack.request_digest, request_payload: { actor_ref: null, assignment: "", ...payload }, response: ack }] };
}

test("collaboration tabs reserve one exact request before a single POST", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const api = { changeTaskCollaboration: async () => { posts++; throw new Error("response lost"); } };
  const a = operationHarness(api, { collaboration: true, factory }), b = operationHarness(api, { collaboration: true, factory });
  await Promise.all([a.mount(), b.mount()]); await Promise.all([a.render().submit(request), b.render().submit({ ...request, idempotency_key: "competing" })]);
  await until(() => a.render().pending && b.render().pending);
  assert.equal(posts, 1); assert.equal(a.render().pending.idempotency_key, b.render().pending.idempotency_key);
  assert.equal((await a.journal.read("project-a"))[0].payload.assignment, request.assignment); a.close(); b.close();
});

test("collaboration task streams remain independent within a Project and from Local CREATE", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const api = { changeTaskCollaboration: async () => { posts++; throw new Error("lost"); } };
  const a = operationHarness(api, { collaboration: true, factory }), b = operationHarness(api, { collaboration: true, task: "task-b", factory }), local = operationHarness({}, { local: true, factory });
  await local.journal.reserve({ project_id: "project-a", operation_key: request.idempotency_key, expected_version: 0, state: "UNKNOWN", payload: { title: "Local", idempotency_key: request.idempotency_key } });
  await Promise.all([a.mount(), b.mount()]); await Promise.all([a.render().submit(request), b.render().submit(request)]);
  assert.equal(posts, 2); assert.equal((await a.journal.read("project-a")).length, 2); assert.equal((await local.journal.read("project-a")).length, 1); a.close(); b.close(); local.close();
});

test("lost reply survives reopen; original-key NOT_FOUND never permits another POST", async () => {
  const factory = new IDBFactory(); let posts = 0, queried;
  const a = operationHarness({ changeTaskCollaboration: async () => { posts++; throw Error("lost"); } }, { collaboration: true, factory });
  await a.mount(); await a.render().submit(request); a.close();
  const b = operationHarness({ changeTaskCollaboration: async () => { posts++; }, getTaskCollaborationReceipt: async (task, key) => { queried = [task, key]; throw { status: 404, detail: "RECEIPT_NOT_FOUND" }; } }, { collaboration: true, factory });
  await b.mount(); await b.render().reconcile(); await b.render().submit({ ...request, idempotency_key: "replacement" });
  assert.deepEqual(queried, ["task-a", "original-key"]); assert.equal(posts, 1); assert.equal(b.render().pending.assignment, request.assignment); assert.equal(b.render().blocked, true); b.close();
});

test("ACK requires full frozen input and exact accepted version readback", async () => {
  let correct = false, readVersion, posts = 0;
  const api = { changeTaskCollaboration: async () => { posts++; return receipt(); }, getTaskCollaborationReceipt: async () => receipt(), getTaskCollaboration: async (_task, version) => { readVersion = version; const doc = document(); if (!correct) doc.task.version++; return doc; } };
  const a = operationHarness(api, { collaboration: true }); await a.mount();
  assert.equal(await a.render().submit(request), null); assert.equal(readVersion, 5); assert.equal(a.render().pending.idempotency_key, "original-key");
  correct = true; assert.equal((await a.render().reconcile()).task.reported_result, "FAIL"); assert.equal(a.render().pending, null); assert.equal(posts, 1); a.close();
});

test("partial history, altered source and denied readback retain UNKNOWN", async () => {
  for (const mutate of [(doc) => { delete doc.operation_history; }, (doc) => { doc.operation_history[0].request_payload.session_id = "wrong-root"; }, (doc) => { doc.collaboration.participants[0].session_id = "wrong-root"; }]) {
    const a = operationHarness({ changeTaskCollaboration: async () => receipt(), getTaskCollaboration: async () => { const doc = document(); mutate(doc); return doc; } }, { collaboration: true });
    await a.mount(); await a.render().submit(request); assert.equal((await a.journal.read("project-a"))[0].state, "UNKNOWN"); a.close();
  }
  const denied = operationHarness({ changeTaskCollaboration: async () => receipt(), getTaskCollaboration: async () => { throw { status: 403 }; } }, { collaboration: true });
  await denied.mount(); await denied.render().submit(request); assert.equal(denied.render().pending.idempotency_key, "original-key"); denied.close();
});

test("version rejection permits a reviewed new intent; key conflict remains uncertain", async () => {
  for (const detail of ["TASK_VERSION_CONFLICT", "TASK_OPERATION_KEY_CONFLICT"]) {
    const a = operationHarness({ changeTaskCollaboration: async () => { throw { status: 409, detail }; } }, { collaboration: true });
    await a.mount(); await a.render().submit(request); assert.equal(a.render().pending !== null, detail.includes("KEY_CONFLICT")); a.close();
  }
});

test("storage denial prevents POST and accepted handoff checks role and generation", async () => {
  let posts = 0;
  const unavailable = operationHarness({ changeTaskCollaboration: async () => { posts++; } }, { collaboration: true, unavailable: true });
  await unavailable.mount(); await unavailable.render().submit(request); assert.equal(posts, 0); unavailable.close();
  const handoff = { profile, operation: "HANDOFF", expected_version: 4, idempotency_key: "handoff-original", participant_id: "participant-b", expected_primary_generation: 1, handoff: { materials: ["accepted report"], unresolved_items: ["old journal not observed"], private_journals_observed: false } };
  const a = operationHarness({ changeTaskCollaboration: async () => receipt(handoff), getTaskCollaboration: async () => document(handoff) }, { collaboration: true });
  await a.mount(); const result = await a.render().submit(handoff); assert.equal(result.task.primary_participant_id, "participant-b"); assert.equal(result.task.primary_generation, 2); a.close();
});
