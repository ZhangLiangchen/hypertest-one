const assert = require("node:assert/strict");
const test = require("node:test");
const { operationHarness, until, document, IDBFactory } = require("./operation-harness.cjs");
const pending = (key = "web:original", extra = {}) => ({ project_id: "project-a", operation_key: key, expected_version: 4, operation: "DISPATCH", task_id: "task-a", digest: "a".repeat(64), state: "UNKNOWN", ...extra });
const receipt = (key) => ({ status: "ACCEPTED", profile: "cloud-harness-task/v1alpha1", project_id: "project-a", operation_key: key, operation: "DISPATCH", task_id: "task-a", version: 5 });
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

test("Legacy session storage denial preserves Cloud original-key recovery", async () => {
  const denied = { getItem() { throw new Error("session storage denied"); } }; let posts = 0, queried;
  const harness = operationHarness({ cloudRequest: async () => { posts++; }, cloudOperation: async (_project, key) => { queried = key; return receipt(key); }, cloudDocument: async (project, task, version) => document(project, task, version) }, { storage: denied });
  const original = pending(); await harness.journal.reserve(original); await harness.mount();
  assert.equal(harness.render().ready, false); assert.ok(harness.render().pending);
  await harness.render().submit({ operation: "CREATE_TASK", expected_version: 0 });
  assert.ok(await harness.render().reconcile()); assert.equal(queried, original.operation_key); assert.equal(posts, 0); harness.close();
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
