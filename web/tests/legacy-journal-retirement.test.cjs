const assert = require("node:assert/strict");
const test = require("node:test");
const { IDBFactory } = require("fake-indexeddb");
const load = require("./load-helper.cjs");

function requestResult(request) {
  return new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); });
}

test("upgrading the journal removes retired session stores while preserving current requests", async () => {
  const indexedDB = new IDBFactory();
  const request = indexedDB.open("hypertest-operation-journals-v1", 3);
  request.onupgradeneeded = () => {
    for (const name of ["cloud", "local-create", "local-collaboration", "local-archive", "cli-authorization"]) {
      const store = request.result.createObjectStore(name, { keyPath: name === "local-collaboration" ? ["project_id", "task_id", "operation_key"] : ["project_id", "operation_key"] });
      store.createIndex("project", "project_id");
    }
  };
  const db = await requestResult(request);
  await new Promise((resolve, reject) => {
    const tx = db.transaction(["cloud", "local-create", "local-collaboration", "local-archive", "cli-authorization"], "readwrite");
    for (const store of ["cloud", "local-create", "local-collaboration", "local-archive", "cli-authorization"]) {
      tx.objectStore(store).put({ project_id: "p", task_id: "t", operation_key: store, state: "UNKNOWN" });
    }
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
  db.close();
  const journals = load("lib/operation-journal.ts", { indexedDB });
  for (const domain of ["cloud", "local-archive", "cli-authorization"]) {
    const rows = await journals.createOperationJournal(domain, (value) => value).read("p");
    assert.equal(rows.length, 1); assert.equal(rows[0].operation_key, domain);
  }
  const upgraded = await requestResult(indexedDB.open("hypertest-operation-journals-v1", 4));
  assert.deepEqual(Array.from(upgraded.objectStoreNames), ["cli-authorization", "cloud", "local-archive"]);
  upgraded.close();
});
