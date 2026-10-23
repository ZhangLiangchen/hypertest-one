const assert = require("node:assert/strict");
const test = require("node:test");
const { webcrypto } = require("node:crypto");
const { IDBFactory } = require("fake-indexeddb");
const load = require("./load-helper.cjs");
const { until } = require("./operation-harness.cjs");

function harness(overrides = {}, { factory = new IDBFactory(), unavailable = false, tab = "one" } = {}) {
  const client = load("lib/memory.ts", { crypto: webcrypto, TextEncoder, Uint8Array, URLSearchParams });
  const slots = [], effects = []; let cursor = 0, sequence = 0, selectedProject = "project-a";
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (value) => { slots[index] = value; }]; },
    useRef(initial) { const index = cursor++; if (!(index in slots)) slots[index] = { current: initial }; return slots[index]; },
    useEffect(effect, dependencies) { const index = cursor++, previous = slots[index]; if (!previous || dependencies.some((value, i) => value !== previous.dependencies[i])) { previous?.cleanup?.(); slots[index] = { dependencies }; effects.push(() => { slots[index].cleanup = effect(); }); } },
  };
  const journal = load("lib/memory-journal.ts", { indexedDB: unavailable ? undefined : factory });
  const module = load("lib/memory-operation.ts", { require: (name) => name === "react" ? react : name === "@/lib/uuid" ? { createUuid: () => `${tab}-${++sequence}` }
    : name === "@/lib/memory" ? { ...client, ...overrides } : name === "@/lib/memory-journal" ? journal : require(name) });
  const render = (projectId = selectedProject) => { selectedProject = projectId; cursor = 0; const value = module.useMemoryOperation(projectId); while (effects.length) effects.shift()(); return value; };
  const mount = async (projectId = selectedProject) => { render(projectId); await until(() => render(projectId).ready || render(projectId).issue === "MEMORY_STORAGE_UNAVAILABLE"); return render(projectId); };
  return { client, factory, render, mount, journal: module.memoryJournal, close: () => { for (const slot of slots) slot?.cleanup?.(); } };
}
function receipt(key, overrides = {}) { return { profile: "hypertest-project-memory/v1alpha1", project_id: "project-a", operation_key: key, operation: "PUBLISH", status: "ACCEPTED", entry_id: "entry-a", expected_version: 1, accepted_version: 2, ...overrides }; }
const intention = { operation: "PUBLISH", entry_id: "entry-a", expected_version: 1, title: "Reviewed lesson", content: "Selected private text", publication_note: "Removed sensitive values" };
const entry = (version = 2) => ({ id: "entry-a", project_id: "project-a", version, status: "PUBLISHED", title: "Reviewed lesson", content: "Selected private text" });

test("Memory persists metadata only, survives close/reopen and uses the original GET after lost response or NOT_FOUND", async () => {
  const factory = new IDBFactory(); let posts = 0, queried;
  const a = harness({ memoryRequest: async () => { posts++; throw new Error("lost response"); } }, { factory });
  await a.mount(); await a.render().submit(intention); const key = a.render().pending.operation_key; a.close();
  const b = harness({ memoryRequest: async () => { posts++; }, memoryOperation: async (_project, key) => { queried = key; throw new Error("NOT_FOUND"); } }, { factory });
  await b.mount(); assert.equal(b.render().pending.operation_key, key);
  const saved = JSON.stringify(await b.journal.read("project-a"));
  assert.equal(saved.includes("Selected private text"), false); assert.equal(saved.includes("Removed sensitive"), false);
  await b.render().submit({ ...intention, title: "Replacement" }); await b.render().reconcile();
  assert.equal(queried, key); assert.equal(posts, 1); assert.equal(b.render().blocked, true); b.close();
});

test("Memory tabs serialize reservations without occupying the Cloud or Local database", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const options = { memoryRequest: async () => { posts++; throw new Error("lost"); } };
  const a = harness(options, { factory, tab: "a" }), b = harness(options, { factory, tab: "b" }); await Promise.all([a.mount(), b.mount()]);
  await Promise.all([a.render().submit(intention), b.render().submit(intention)]); assert.equal(posts, 1);
  const journals = load("lib/operation-journal.ts", { indexedDB: factory });
  const cloud = journals.createOperationJournal("cloud", (value) => value), local = journals.createOperationJournal("local-create", (value) => value);
  const key = { project_id: "project-a", operation_key: "independent", state: "SENT" };
  assert.equal((await cloud.reserve(key)).created, true); assert.equal((await local.reserve(key)).created, true); a.close(); b.close();
});

test("Memory storage unavailable or newly failing prohibits POST", async () => {
  let posts = 0; const unavailable = harness({ memoryRequest: async () => { posts++; } }, { unavailable: true });
  await unavailable.mount(); await unavailable.render().submit(intention); unavailable.close();
  const failing = harness({ memoryRequest: async () => { posts++; } }); await failing.mount(); failing.factory.open = () => { throw new Error("denied"); };
  await failing.render().submit(intention); assert.equal(posts, 0); assert.equal(failing.render().ready, false); failing.close();
});

test("ACK requires the original identity and complete fixed accepted revision before releasing Memory", async () => {
  let key, posts = 0, version, complete = false;
  const current = harness({ memoryRequest: async (_path, init) => { posts++; key = JSON.parse(init.body).operation_key; return receipt(key); },
    memoryEntry: async (_project, _entry, accepted) => { version = accepted; return complete ? entry() : entry(3); }, memoryOperation: async (_project, key) => receipt(key) });
  await current.mount(); await current.render().submit(intention); assert.equal(current.render().pending.operation_key, key); assert.equal(version, 2); assert.equal(current.render().receipt, null);
  complete = true; await current.render().reconcile(); assert.equal(current.render().pending, null); assert.equal(current.render().receipt.accepted_version, 2); assert.equal(posts, 1); current.close();
});

test("Project mapping ACK reads its immutable accepted configuration", async () => {
  let accepted;
  const current = harness({ memoryRequest: async (_path, init) => receipt(JSON.parse(init.body).operation_key, { operation: "CONFIGURE", expected_version: 0, accepted_version: 1, entry_id: undefined }),
    memoryConfiguration: async (project, version) => { accepted = version; return { project_id: project, enabled: true, version }; } });
  await current.mount(); await current.render().submit({ operation: "CONFIGURE", expected_version: 0, enabled: true });
  assert.equal(accepted, 1); assert.equal(current.render().pending, null); current.close();
});

test("A late Memory response cannot erase another tab's next original operation", async () => {
  const factory = new IDBFactory(); let finish, posts = 0;
  const a = harness({ memoryRequest: async () => { posts++; return new Promise((resolve) => { finish = resolve; }); }, memoryEntry: async () => entry() }, { factory, tab: "a" });
  await a.mount(); const sending = a.render().submit(intention); await until(() => posts === 1); const original = (await a.journal.read("project-a"))[0];
  const b = harness({ memoryOperation: async (_project, key) => receipt(key), memoryEntry: async () => entry(), memoryRequest: async () => { throw new Error("next lost"); } }, { factory, tab: "b" });
  await b.mount(); await b.render().reconcile(); await b.render().submit({ ...intention, expected_version: 2, operation: "REVISE" }); const next = b.render().pending.operation_key;
  finish(receipt(original.operation_key)); assert.equal(await sending, null); assert.equal((await a.journal.read("project-a"))[0].operation_key, next); a.close(); b.close();
});

test("Receipt matching rejects changed project, key, action, original version and accepted version", () => {
  const { memoryReceiptMatches } = harness().client;
  const original = { ...intention, project_id: "project-a", operation_key: "original" };
  assert.equal(memoryReceiptMatches(original, receipt("original")), true);
  for (const change of [{ status: "UNKNOWN" }, { operation_key: "replacement" }, { project_id: "project-b" }, { operation: "REVISE" }, { expected_version: 2 }, { accepted_version: 3 }, { entry_id: "entry-b" }]) assert.equal(memoryReceiptMatches(original, receipt("original", change)), false);
});

test("An accepted historical revision remains readable after supersession or expiry", async () => {
  const current = harness({ memoryRequest: async (_path, init) => receipt(JSON.parse(init.body).operation_key),
    memoryEntry: async () => ({ ...entry(), status: "SUPERSEDED", revision_status: "PUBLISHED", current_version: 4 }) });
  await current.mount(); await current.render().submit(intention); assert.equal(current.render().pending, null); assert.equal(current.render().receipt.accepted_version, 2); current.close();
});

test("Recovering a server-listed original operation persists only metadata and issues GET without POST", async () => {
  let posts = 0, queried;
  const current = harness({ memoryRequest: async () => { posts++; }, memoryOperation: async (_project, key) => { queried = key; return receipt(key); }, memoryEntry: async () => entry() });
  await current.mount();
  await current.render().recoverOriginal(receipt("original-server-key", { status: "UNKNOWN", accepted_version: null, request_digest: "a".repeat(64) }));
  assert.equal(queried, "original-server-key"); assert.equal(posts, 0); assert.equal(current.render().pending, null); current.close();
});
