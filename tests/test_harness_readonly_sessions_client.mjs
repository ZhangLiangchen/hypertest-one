import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = "cloud-01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba";
const source = await readFile(new URL("../src/hypertest/cloud/harness_readonly_sessions.client.js", import.meta.url), "utf8");
const manifest = JSON.parse(await readFile(new URL("../src/hypertest/cloud/harness_readonly_sessions.package.json", import.meta.url), "utf8"));
let plugin;
vm.runInNewContext(source, {window: {__ModuleLoader__: {load(entry) {
  assert.equal(entry.id, manifest.name);
  plugin = entry.factory();
}}}});

function store(initial) {
  let value = initial;
  const listeners = new Set();
  return {
    getSnapshot: () => value,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    set(next) { value = next; for (const listener of [...listeners]) listener(); },
    listenerCount: () => listeners.size,
  };
}

function fixture(rows, initialBlocks = {}) {
  const list = store({byId: rows});
  const locale = store("zh");
  const stores = new Map(Object.entries(initialBlocks).map(([id, value]) => [id, store(value)]));
  const blocks = {
    storeFor(id) {
      if (!stores.has(id)) stores.set(id, store(undefined));
      return stores.get(id);
    },
    set(id, value) { blocks.storeFor(id).set(value); },
  };
  const disposers = [];
  const ctx = {
    sessions: {list}, conversation: {blocks},
    remote: new Proxy({}, {get() { throw new Error("Viewing must not call a remote writer"); }}),
    locale: {
      register(name, dictionaries) { ctx.dictionaries = dictionaries; return () => {}; },
      bind: () => key => ctx.dictionaries[locale.getSnapshot()][key],
      subscribe: locale.subscribe,
    },
    effect(fn) { disposers.push(fn()); },
  };
  plugin.apply(ctx);
  return {list, locale, blocks, stores, dispose() { for (const dispose of disposers.reverse()) dispose(); }};
}

test("native composer is read-only only for exact Cloud roots and native descendants", () => {
  const f = fixture({[root]: {id: root}, child: {parentId: root}, nested: {parentId: "child"},
    personal: {}, "cloud-my-notes": {}, "cloud-01a1a11d-9f58-7efd-b9b6-6ee53f9b46ba-copy": {}});
  for (const id of [root, "child", "nested"]) assert.match(f.blocks.storeFor(id).getSnapshot().reason, /只读/);
  for (const id of ["personal", "cloud-my-notes", root + "-copy"]) assert.equal(f.blocks.storeFor(id).getSnapshot(), undefined);
  f.dispose();
});

test("late native lineage blocks descendants and a refresh gap never enables them", () => {
  const f = fixture({child: {parentId: "parent"}, cycleA: {parentId: "cycleB"}, cycleB: {parentId: "cycleA"}});
  assert.equal(f.blocks.storeFor("child").getSnapshot(), undefined);
  f.list.set({byId: {child: {parentId: "parent"}, parent: {parentId: root}}});
  assert.match(f.blocks.storeFor("child").getSnapshot().reason, /只读/);
  f.list.set({byId: {}});
  assert.match(f.blocks.storeFor("child").getSnapshot().reason, /只读/);
  assert.equal(f.blocks.storeFor("cycleA").getSnapshot(), undefined);
  f.dispose();
});

test("native blockers retain their reason and clearing one cannot enable a Cloud composer", () => {
  const f = fixture({[root]: {}}, {[root]: {reason: "Select an available model"}});
  assert.equal(f.blocks.storeFor(root).getSnapshot().reason, "Select an available model");
  f.blocks.set(root, undefined);
  assert.match(f.blocks.storeFor(root).getSnapshot().reason, /只读/);
  f.blocks.set(root, {reason: "Another native restriction"});
  f.dispose();
  assert.equal(f.blocks.storeFor(root).getSnapshot().reason, "Another native restriction");
  assert.equal(f.list.listenerCount(), 0);
  assert.equal(f.blocks.storeFor(root).listenerCount(), 0);
});

test("locale changes update the native placeholder and disposal clears only owned blocks", () => {
  const f = fixture({[root]: {}, personal: {}}, {personal: {reason: "Native reason"}});
  f.locale.set("en");
  assert.equal(f.blocks.storeFor(root).getSnapshot().reason,
    "This Cloud session is read-only here. Send messages in HyperTest.");
  f.dispose();
  assert.equal(f.blocks.storeFor(root).getSnapshot(), undefined);
  assert.equal(f.blocks.storeFor("personal").getSnapshot().reason, "Native reason");
  assert.equal(f.locale.listenerCount(), 0);
});

test("the standalone release manifest exposes the native host and client halves", () => {
  assert.equal(manifest.exports["."], "./harness_readonly_sessions.mjs");
  assert.equal(manifest.exports["./client"], "./harness_readonly_sessions.client.js");
  assert.equal(manifest.dsh.client.platform, "web");
  assert.deepEqual(Array.from(plugin.inject), ["conversation", "sessions", "locale"]);
});
