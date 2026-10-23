/** Independent durable Memory operation journal. Task journals are never opened.
 * IndexedDB readwrite transactions arbitrate writers across tabs; notifications
 * only refresh the view and never grant permission to submit a request.
 */
export type JournalIdentity = { project_id: string; operation_key: string; state: "SENT" | "UNKNOWN" };
type Domain = "memory";
const databaseName = "hypertest-memory-operations-v1";
const channelName = "hypertest-memory-operations-changed-v1";
const listeners = new Set<(domain: Domain, projectId: string) => void>();

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") { reject(new Error("PRIVATE_JOURNAL_UNAVAILABLE")); return; }
    const request = indexedDB.open(databaseName, 1);
    request.onupgradeneeded = () => {
      for (const name of ["memory"]) {
        const store = request.result.createObjectStore(name, { keyPath: ["project_id", "operation_key"] });
        store.createIndex("project", "project_id");
      }
    };
    request.onerror = () => reject(request.error || new Error("PRIVATE_JOURNAL_UNAVAILABLE"));
    request.onblocked = () => reject(new Error("PRIVATE_JOURNAL_UNAVAILABLE"));
    request.onsuccess = () => resolve(request.result);
  });
}

function notify(domain: Domain, projectId: string) {
  for (const listener of listeners) listener(domain, projectId);
  // BroadcastChannel is optional. Transactions still prevent duplicate writers.
  try {
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(channelName);
      channel.postMessage({ domain, projectId }); channel.close();
    }
  } catch { /* A failed notification never changes journal ownership. */ }
}

function identity(value: JournalIdentity): string {
  const { state: _state, ...frozen } = value;
  return JSON.stringify(frozen);
}

export function createMemoryJournal<T extends JournalIdentity>(domain: Domain, validate: (value: unknown, projectId: string) => T) {
  async function transaction<R>(mode: IDBTransactionMode, work: (store: IDBObjectStore, done: (value: R) => void, fail: (error: unknown) => void) => void): Promise<R> {
    const db = await openDatabase();
    return new Promise<R>((resolve, reject) => {
      let result: R, failure: unknown;
      let tx: IDBTransaction;
      try { tx = db.transaction(domain, mode, mode === "readwrite" ? { durability: "strict" } : undefined); } catch (error) { db.close(); reject(error); return; }
      tx.oncomplete = () => { db.close(); resolve(result); };
      tx.onabort = tx.onerror = () => { db.close(); reject(failure || tx.error || new Error("PRIVATE_JOURNAL_UNAVAILABLE")); };
      const fail = (error: unknown) => { failure = error; tx.abort(); };
      try { work(tx.objectStore(domain), (value) => { result = value; }, fail); } catch (error) { fail(error); }
    });
  }

  const read = (projectId: string) => transaction<T[]>("readonly", (store, done, fail) => {
    const request = store.index("project").getAll(projectId);
    request.onsuccess = () => { try { done(request.result.map((value) => validate(value, projectId))); } catch (error) { fail(error); } };
  });

  async function reserve(input: T): Promise<{ created: boolean; records: T[] }> {
    const value = validate(input, input.project_id);
    const result = await transaction<{ created: boolean; records: T[] }>("readwrite", (store, done, fail) => {
      const request = store.index("project").getAll(value.project_id);
      request.onsuccess = () => {
        try {
          const records = request.result.map((row) => validate(row, value.project_id));
          if (records.length) { done({ created: false, records }); return; }
          store.add(value); done({ created: true, records: [value] });
        } catch (error) { fail(error); }
      };
    });
    if (result.created) notify(domain, value.project_id);
    return result;
  }

  // Migrations append every original key. Conflicting old tabs must not replace
  // each other's requests, nor replace the current durable stream.
  async function importLegacy(input: T): Promise<void> {
    const value = validate(input, input.project_id);
    await transaction<void>("readwrite", (store, done, fail) => {
      const request = store.get([value.project_id, value.operation_key]);
      request.onsuccess = () => {
        try {
          if (request.result) {
            const previous = validate(request.result, value.project_id);
            if (identity(previous) !== identity(value)) throw new Error("JOURNAL_KEY_CONFLICT");
          } else store.add(value);
          done();
        } catch (error) { fail(error); }
      };
    });
    notify(domain, value.project_id);
  }

  async function change(input: T, remove: boolean): Promise<boolean> {
    const original = validate(input, input.project_id);
    const changed = await transaction<boolean>("readwrite", (store, done, fail) => {
      const request = store.get([original.project_id, original.operation_key]);
      request.onsuccess = () => {
        try {
          if (!request.result) { done(false); return; }
          const previous = validate(request.result, original.project_id);
          if (identity(previous) !== identity(original)) throw new Error("JOURNAL_KEY_CONFLICT");
          if (remove) store.delete([original.project_id, original.operation_key]);
          else store.put({ ...previous, state: "UNKNOWN" });
          done(true);
        } catch (error) { fail(error); }
      };
    });
    if (changed) notify(domain, original.project_id);
    return changed;
  }

  function subscribe(projectId: string, callback: () => void): () => void {
    const listener = (changedDomain: Domain, changedProject: string) => { if (changedDomain === domain && changedProject === projectId) callback(); };
    listeners.add(listener);
    let channel: BroadcastChannel | undefined;
    try {
      if (typeof BroadcastChannel !== "undefined") {
        channel = new BroadcastChannel(channelName);
        channel.onmessage = (event) => { if (event.data?.domain === domain && event.data?.projectId === projectId) callback(); };
      }
    } catch { /* Focus refresh and transactional reserve remain available. */ }
    if (typeof window !== "undefined") { window.addEventListener("focus", callback); window.addEventListener("pageshow", callback); }
    return () => {
      listeners.delete(listener); channel?.close();
      if (typeof window !== "undefined") { window.removeEventListener("focus", callback); window.removeEventListener("pageshow", callback); }
    };
  }

  return { read, reserve, importLegacy, markUnknown: (original: T) => change(original, false), settle: (original: T) => change(original, true), subscribe };
}
