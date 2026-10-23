const assert = require("node:assert/strict");
const test = require("node:test");
const { operationHarness, until, document, IDBFactory } = require("./operation-harness.cjs");
const pending = (key = "web:original", extra = {}) => ({ project_id: "project-a", operation_key: key, expected_version: 4, operation: "DISPATCH", task_id: "task-a", digest: "a".repeat(64), state: "UNKNOWN", ...extra });
const receipt = (key) => ({ status: "ACCEPTED", profile: "cloud-harness-task/v1alpha1", project_id: "project-a", operation_key: key, operation: "DISPATCH", task_id: "task-a", version: 5 });
const payload = { idempotency_key: "local-original", title: "Local request", objective: "Original objective", plan_markdown: "# Full original plan\n", intended_actor_ref: null };
function localDetail(request = payload) {
  return { task: { id: "local-task", project_id: "project-a", version: 1, title: request.title, objective: request.objective || "", plan_markdown: request.plan_markdown || "", intended_actor_ref: Object.hasOwn(request, "intended_actor_ref") ? request.intended_actor_ref : "sole-authorized-actor", binding_state: "UNBOUND", status: "DRAFT", reported_result: "NOT_RUN" }, cases: [], reports: [], case_history: [], report_history: [], sync_history: [], management_history: [], binding_history: [], creation_receipt: { status: "ACCEPTED", operation: "CREATE", project_id: "project-a", task_id: "local-task", version: 1, idempotency_key: request.idempotency_key } };
}

test("IndexedDB serializes competing reservations and survives closing all tab connections", async () => {
  const factory = new IDBFactory(), a = operationHarness({}, { factory }), b = operationHarness({}, { factory });
  const result = await Promise.all([a.journal.reserve(pending("web:first")), b.journal.reserve(pending("web:second"))]);
  assert.equal(result.filter((item) => item.created).length, 1); a.close(); b.close();
  const reopened = operationHarness({}, { factory });
  assert.equal((await reopened.journal.read("project-a")).length, 1); reopened.close();
});

test("Legacy migration retains all original keys, strips secrets and bodies, and blocks new POSTs", async () => {
  const factory = new IDBFactory(), first = pending("web:first"), second = pending("web:second");
  const a = operationHarness({}, { factory, session: new Map([["hypertest:cloud:pending:project-a", JSON.stringify({ ...first, secret: "private-secret", payload: { prd: "private-prd" } })]]) });
  const b = operationHarness({}, { factory, session: new Map([["hypertest:cloud:pending:project-a", JSON.stringify(second)]]) });
  await Promise.all([a.mount(), b.mount()]);
  const records = await a.journal.read("project-a");
  assert.equal(records.length, 2); assert.equal(/private-secret|private-prd|payload|secret/.test(JSON.stringify(records)), false);
  assert.equal(a.data.size + b.data.size, 0);
  assert.equal((await a.journal.reserve(pending("web:third"))).created, false);
  await a.journal.settle(first);
  assert.equal((await b.journal.reserve(pending("web:third"))).created, false, "every original key must settle"); a.close(); b.close();
});

test("Original-key CAS cannot erase a newer request or resurrect a settled old request", async () => {
  const harness = operationHarness(), original = pending(), newer = pending("web:new");
  await harness.journal.reserve(original); assert.equal(await harness.journal.settle(original), true);
  await harness.journal.reserve(newer);
  assert.equal(await harness.journal.settle(original), false); assert.equal(await harness.journal.markUnknown(original), false);
  assert.equal((await harness.journal.read("project-a"))[0].operation_key, newer.operation_key);
  await assert.rejects(harness.journal.settle({ ...newer, expected_version: 9 }), /KEY_CONFLICT/); harness.close();
});

test("Cloud and Local retain separate stores even with the same Project and key text", async () => {
  const factory = new IDBFactory(), cloud = operationHarness({}, { factory }), local = operationHarness({}, { factory, local: true });
  await cloud.journal.reserve(pending("shared-key"));
  await local.journal.reserve({ project_id: "project-a", operation_key: "shared-key", expected_version: 0, state: "UNKNOWN", payload: { ...payload, idempotency_key: "shared-key" } });
  await cloud.journal.settle(pending("shared-key"));
  const [kept] = await local.journal.read("project-a");
  assert.equal(kept.payload.plan_markdown, payload.plan_markdown); cloud.close(); local.close();
});

test("Two ready Cloud tabs send one POST and both display the same original key", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const overrides = { cloudRequest: async () => { posts++; throw new Error("reply lost"); } };
  const a = operationHarness(overrides, { factory, tab: "a" }), b = operationHarness(overrides, { factory, tab: "b" });
  await Promise.all([a.mount(), b.mount()]);
  await Promise.all([a.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 }), b.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 })]);
  await until(() => a.render().pending && b.render().pending);
  assert.equal(posts, 1); assert.equal(a.render().pending.operation_key, b.render().pending.operation_key); a.close(); b.close();
});

test("Closing and reopening after lost response permits original-key GET only, including NOT_FOUND", async () => {
  const factory = new IDBFactory(); let posts = 0, queried;
  const a = operationHarness({ cloudRequest: async () => { posts++; throw new Error("reply lost"); } }, { factory });
  await a.mount(); await a.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  const key = a.render().pending.operation_key; a.close();
  const b = operationHarness({ cloudRequest: async () => { posts++; }, cloudOperation: async (_project, original) => { queried = original; throw new Error("NOT_FOUND"); } }, { factory, tab: "reopened" });
  await b.mount(); assert.equal(b.render().pending.operation_key, key);
  await b.render().submit({ operation: "DISPATCH", expected_version: 4 }); await b.render().reconcile();
  assert.equal(queried, key); assert.equal(posts, 1); assert.equal((await b.journal.read("project-a"))[0].state, "UNKNOWN"); b.close();
});

test("Unavailable or newly failing persistent storage prohibits POST", async () => {
  let posts = 0;
  const unavailable = operationHarness({ cloudRequest: async () => { posts++; } }, { unavailable: true });
  await unavailable.mount(); assert.equal(unavailable.render().ready, false);
  await unavailable.render().submit({ operation: "CREATE_TASK", expected_version: 0 }); unavailable.close();
  const failing = operationHarness({ cloudRequest: async () => { posts++; } });
  await failing.mount(); failing.factory.open = () => { throw new Error("storage denied"); };
  await failing.render().submit({ operation: "CREATE_TASK", expected_version: 0 });
  assert.equal(failing.render().ready, false); assert.equal(posts, 0); failing.close();
});

test("ACK waits for the complete exact accepted version and never retries the POST", async () => {
  let key, readVersion, complete = false, posts = 0;
  const harness = operationHarness({ cloudRequest: async (_path, init) => { posts++; key = JSON.parse(init.body).operation_key; return receipt(key); },
    cloudDocument: async (project, task, version) => { readVersion = version; return complete ? document(project, task, version) : document(project, task, version + 1); }, cloudOperation: async (_project, original) => receipt(original) });
  await harness.mount(); await harness.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  assert.equal(harness.render().pending.operation_key, key); assert.equal(harness.render().receipt, null); assert.equal(readVersion, 5);
  complete = true; await harness.render().reconcile();
  assert.equal(harness.render().pending, null); assert.equal(harness.render().receipt.version, 5); assert.equal(posts, 1); harness.close();
});

test("A partial task readback cannot settle a matching ACK", async () => {
  const harness = operationHarness({ cloudRequest: async (_path, init) => receipt(JSON.parse(init.body).operation_key), cloudDocument: async () => ({ task: { id: "task-a", project_id: "project-a", version: 5 }, assets: [] }) });
  await harness.mount(); await harness.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  assert.equal(harness.render().pending.state, "UNKNOWN"); assert.equal(harness.render().receipt, null); harness.close();
});

test("A late Cloud response cannot clear another tab's newer operation", async () => {
  const factory = new IDBFactory(); let finish, posts = 0;
  const response = new Promise((resolve) => { finish = resolve; });
  const a = operationHarness({ cloudRequest: async () => { posts++; return response; }, cloudDocument: async (project, task, version) => document(project, task, version) }, { factory, tab: "a" });
  await a.mount(); const sending = a.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  await until(() => posts === 1); const [original] = await a.journal.read("project-a");
  const b = operationHarness({ cloudOperation: async (_project, key) => receipt(key), cloudDocument: async (project, task, version) => document(project, task, version), cloudRequest: async () => { posts++; throw new Error("new unknown request"); } }, { factory, tab: "b" });
  await b.mount(); await b.render().reconcile(); await b.render().submit({ operation: "CANCEL_TASK", task_id: "task-a", expected_version: 5 });
  const newer = b.render().pending.operation_key; finish(receipt(original.operation_key));
  assert.equal(await sending, null); assert.equal((await a.journal.read("project-a"))[0].operation_key, newer); assert.equal(posts, 2); a.close(); b.close();
});

test("Local closes and reopens with its exact complete request and only original-key GET", async () => {
  const factory = new IDBFactory(); let posts = 0, queried;
  const a = operationHarness({ createLocalTask: async () => { posts++; throw new Error("reply lost"); } }, { local: true, factory });
  await a.mount(); await a.render().submit(payload); a.close();
  const b = operationHarness({ createLocalTask: async () => { posts++; }, getLocalTaskCreation: async (_project, key) => { queried = key; throw { status: 404 }; } }, { local: true, factory });
  await b.mount(); assert.deepEqual(JSON.parse(JSON.stringify(b.render().pending)), payload);
  await b.render().submit({ ...payload, idempotency_key: "new-key" }); await b.render().reconcile();
  assert.equal(queried, payload.idempotency_key); assert.equal(posts, 1); assert.equal(b.render().blocked, true); b.close();
});

test("Local ACK requires fixed v1 readback of the complete original task", async () => {
  let correct = false, readVersion, posts = 0;
  const harness = operationHarness({ createLocalTask: async () => { posts++; return localDetail(); }, getLocalTaskCreation: async () => localDetail(),
    getSessionTask: async (_id, version) => { readVersion = version; const value = localDetail(); if (!correct) value.task.plan_markdown = "wrong plan"; return value; } }, { local: true });
  await harness.mount(); assert.equal(await harness.render().submit(payload), null);
  assert.equal(harness.render().pending.idempotency_key, payload.idempotency_key); assert.equal(readVersion, 1);
  correct = true; const result = await harness.render().reconcile();
  assert.equal(result.task.plan_markdown, payload.plan_markdown); assert.equal(harness.render().pending, null); assert.equal(posts, 1); harness.close();
});

test("Denied Local readback after ACK preserves UNKNOWN instead of treating it as POST rejection", async () => {
  const harness = operationHarness({ createLocalTask: async () => localDetail(), getSessionTask: async () => { throw { status: 403 }; } }, { local: true });
  await harness.mount(); await harness.render().submit(payload);
  assert.equal(harness.render().pending.idempotency_key, payload.idempotency_key); assert.equal((await harness.journal.read("project-a"))[0].state, "UNKNOWN"); harness.close();
});

test("Local tabs serialize CREATE and migrate omitted intended actor without inventing a value", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const a = operationHarness({ createLocalTask: async () => { posts++; throw new Error("lost"); } }, { local: true, factory });
  const b = operationHarness({ createLocalTask: async () => { posts++; throw new Error("lost"); } }, { local: true, factory });
  await Promise.all([a.mount(), b.mount()]); await Promise.all([a.render().submit(payload), b.render().submit({ ...payload, idempotency_key: "second-local" })]);
  assert.equal(posts, 1); a.close(); b.close();
  const omitted = { idempotency_key: "omitted-actor", title: "Original task" };
  const c = operationHarness({}, { local: true, factory, session: new Map([["hypertest:local-task-create:project-a", JSON.stringify({ project_id: "project-a", payload: omitted })]]) });
  await c.mount(); const records = await c.journal.read("project-a");
  assert.equal(records.length, 2); assert.equal(Object.hasOwn(records.find((row) => row.operation_key === omitted.idempotency_key).payload, "intended_actor_ref"), false);
  assert.equal(c.data.size, 0); c.close();
});

test("Local refuses an ACK with the same Project/key but different frozen CREATE input", async () => {
  const harness = operationHarness({ createLocalTask: async () => localDetail({ ...payload, title: "Other request" }), getSessionTask: async () => localDetail() }, { local: true });
  await harness.mount(); await harness.render().submit(payload);
  assert.equal(harness.render().pending.idempotency_key, payload.idempotency_key); assert.equal(harness.render().success, false); harness.close();
});

test("Legacy storage denial preserves read-only recovery of durable Cloud and Local keys", async () => {
  const denied = { getItem() { throw new Error("session storage denied"); } };
  for (const local of [false, true]) {
    let posts = 0, queried;
    const overrides = local ? { createLocalTask: async () => { posts++; }, getLocalTaskCreation: async (_project, key) => { queried = key; return localDetail(); }, getSessionTask: async () => localDetail() }
      : { cloudRequest: async () => { posts++; }, cloudOperation: async (_project, key) => { queried = key; return receipt(key); }, cloudDocument: async (project, task, version) => document(project, task, version) };
    const harness = operationHarness(overrides, { local, storage: denied });
    const original = local ? { project_id: "project-a", operation_key: payload.idempotency_key, expected_version: 0, state: "UNKNOWN", payload } : pending();
    await harness.journal.reserve(original); await harness.mount();
    assert.equal(harness.render().ready, false); assert.ok(harness.render().pending);
    await harness.render().submit(local ? payload : { operation: "CREATE_TASK", expected_version: 0 });
    const accepted = await harness.render().reconcile();
    assert.ok(accepted); assert.equal(queried, original.operation_key); assert.equal(posts, 0); harness.close();
  }
});

test("Cloud original-key conflict remains UNKNOWN and cannot permit another POST", async () => {
  let posts = 0;
  const harness = operationHarness({ cloudRequest: async () => { posts++; throw new harness.client.CloudApiError(409, "safe original-key conflict", "OPERATION_KEY_CONFLICT"); }, cloudOperation: async () => { throw new Error("read-only unresolved"); } });
  await harness.mount(); await harness.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  const original = harness.render().pending.operation_key;
  assert.equal(harness.render().pending.state, "UNKNOWN");
  await harness.render().reconcile(); await harness.render().submit({ operation: "DISPATCH", task_id: "task-a", expected_version: 4 });
  assert.equal(harness.render().pending.operation_key, original); assert.equal(posts, 1); harness.close();
});
