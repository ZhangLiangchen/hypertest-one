const { IDBFactory } = require("fake-indexeddb");
const load = require("./load-helper.cjs");
const assert = require("node:assert/strict");

class TestChannel {
  static channels = new Set();
  constructor(name) { this.name = name; TestChannel.channels.add(this); }
  postMessage(data) {
    for (const channel of TestChannel.channels) if (channel !== this && channel.name === this.name) setImmediate(() => { if (TestChannel.channels.has(channel)) channel.onmessage?.({ data }); });
  }
  close() { TestChannel.channels.delete(this); }
}

async function until(condition) {
  for (let i = 0; i < 100; i++) { if (await condition()) return; await new Promise(setImmediate); }
  assert.fail("bounded async lifecycle did not settle");
}

function operationHarness(overrides = {}, options = {}) {
  const client = load("lib/cloud.ts", { TextEncoder, Uint8Array, DataView, Int32Array, URL });
  const binding = load("lib/local-task-binding.ts");
  const slots = [], effects = [], data = options.session || new Map();
  const factory = options.factory || new IDBFactory();
  let cursor = 0, sequence = 0, selectedProject = "project-a";
  const sessionStorage = options.storage || { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
  const react = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; if (!(index in slots)) slots[index] = { current: initial }; return slots[index]; },
    useEffect(effect, dependencies) {
      const index = cursor++, before = slots[index];
      if (!before || dependencies.some((value, i) => value !== before.dependencies[i])) {
        before?.cleanup?.(); slots[index] = { dependencies };
        effects.push(() => { slots[index].cleanup = effect(); });
      }
    },
  };
  const journals = load("lib/operation-journal.ts", { indexedDB: options.unavailable ? undefined : factory, BroadcastChannel: TestChannel });
  const module = load(options.local ? "lib/local-create-operation.ts" : "lib/cloud-operation.ts", { sessionStorage,
    require: (name) => name === "react" ? react : name === "@/lib/uuid" ? { createUuid: () => `operation-${options.tab || "one"}-${++sequence}` }
      : name === "@/lib/cloud" ? { ...client, ...overrides } : name === "@/lib/operation-journal" ? journals
        : name === "@/lib/local-task-binding" ? binding : name === "@/lib/api" ? overrides : require(name),
  });
  const render = (projectId = selectedProject) => {
    selectedProject = projectId; cursor = 0;
    const value = (options.local ? module.useLocalCreateOperation : module.useCloudOperation)(projectId);
    while (effects.length) effects.shift()();
    return value;
  };
  const mount = async (projectId = selectedProject) => { render(projectId); await until(() => render(projectId).ready || render(projectId).storageError || render(projectId).issue === "PRIVATE_JOURNAL_UNAVAILABLE"); return render(projectId); };
  const close = () => { for (const slot of slots) slot?.cleanup?.(); };
  return { render, mount, close, data, client, factory, journals, journal: options.local ? module.localCreateJournal : module.cloudJournal };
}

function document(projectId, taskId, version) {
  return { task: { project_id: projectId, id: taskId, version }, attempts: [], resolutions: [], assets: [], artifacts: [], runs: [], run_cases: [], delegations: [], questions: [], answers: [] };
}

module.exports = { operationHarness, until, document, IDBFactory };
