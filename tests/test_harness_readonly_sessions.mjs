import assert from "node:assert/strict";
import test from "node:test";
import {cloudLineage, installReadOnlySessions, methodFingerprints} from "../src/hypertest/cloud/harness_readonly_sessions.mjs";

const ROOT = "cloud-11111111-1111-4111-8111-111111111111";
const address = id => ({kind: "session", sessionId: id});
const event = (seq, type, data = {}) => ({seq, time: 100 + seq, type, data});

function fixture() {
  const rows = new Map([
    [ROOT, {header: {id: ROOT, createdAt: 1, cwd: "/synthetic/cloud"}, revision: "1",
      events: [event(0, "turn/start"), event(1, "step/start")]}],
    ["child", {header: {id: "child", createdAt: 2, cwd: "/synthetic/cloud", origin: "subagent", parentSession: ROOT},
      revision: "1", events: []}],
    ["grandchild", {header: {id: "grandchild", createdAt: 3, cwd: "/synthetic/other", origin: "subagent", parentSession: "child"},
      revision: "1", events: []}],
    ["personal", {header: {id: "personal", createdAt: 4, cwd: "/synthetic/personal"}, revision: "1", events: []}],
  ]);
  const calls = {open: [], closed: 0, originalFollow: 0, originalObserve: 0, resolve: [], writes: [], broadcasts: [], errors: []};
  const ctx = {
    sessions: {get() {}},
    sessionPersistence: {
      async stat(id, {signal} = {}) { signal?.throwIfAborted(); return rows.get(id); },
      async open(id, access, {signal}) {
        assert.equal(access, "read");
        signal.throwIfAborted(); calls.open.push(id);
        const row = structuredClone(rows.get(id));
        return {header: row.header, inheritedEventCount: 0,
          async read() { return {events: row.events}; }, async close() { calls.closed++; }};
      },
    },
    sessionProjections: {
      restore(checkpoint, events, baseSeq, header) {
        const open = events.some(value => value.type === "turn/start") && !events.some(value => value.type === "turn/end");
        return {snapshot: {asOfSeq: events.length - 1, values: {turnBoundary: {open}, subagent:
          header.origin === "subagent" ? {seq: 0, mode: "continuable"} : null}}, checkpoint: {}};
      },
    },
    sessionQuery: {
      async observeSession(id) {
        calls.originalObserve++;
        const row = rows.get(id);
        return {source: "prepared", header: row.header, events: [...row.events, event(row.events.length, "turn/end")],
          cursor: row.events.length, [Symbol.dispose]() {}};
      },
    },
    logger: {error(message) { calls.errors.push(message); }},
  };
  const history = {
    async sourceFor(target, signal) {
      const id = target.kind === "session" ? target.sessionId : target.childSessionId;
      const source = await ctx.sessionQuery.observeSession(id, {signal});
      if (target.kind === "subagent" && source.header.parentSession !== target.parentSessionId) {
        source[Symbol.dispose](); throw new Error("subagent/unauthorized");
      }
      return source;
    },
    async page(request, signal) {
      const source = await this.sourceFor(request.address, signal);
      try {
        assert(request.throughSeq <= source.cursor);
        return {records: source.events.slice(0, request.throughSeq + 1).map(value => ({type: "event", event: value})), hasMore: false};
      } finally { source[Symbol.dispose](); }
    },
  };
  ctx.sessionController = {
    history,
    agents: {async resolve(id) { calls.resolve.push(id); return {agent: {id}}; }},
    controlState: {broadcast(value) { calls.broadcasts.push(value); }},
    async *follow(request) { calls.originalFollow++; yield {type: "personal", request}; },
    async page(request, signal) { return this.history.page(request, signal); },
    async projections(request) { return {kind: "personal", sessionId: request.sessionId}; },
  };
  for (const key of ["create", "prompt", "rename", "selectModel", "updateQueue", "cancel", "fork"]) {
    ctx.sessionController[key] = async request => { calls.writes.push([key, request.sessionId]); return {accepted: true}; };
  }
  const install = () => installReadOnlySessions(ctx, {pollIntervalMs: 250}, methodFingerprints(ctx));
  return {ctx, rows, calls, install};
}

test("Cloud membership follows immutable native parent links and rejects broken or cyclic ancestry", async () => {
  const {ctx, rows} = fixture();
  for (const id of [ROOT, "child", "grandchild"]) assert.equal((await cloudLineage(ctx, id)).managed, true);
  for (const id of ["personal", "cloud-not-a-uuid", "brand-new"]) assert.equal((await cloudLineage(ctx, id)).managed, false);
  rows.get("child").header.parentSession = "missing";
  await assert.rejects(cloudLineage(ctx, "child"), error => error.details.reason === "SESSION_PARENT_UNAVAILABLE");
  rows.get("child").header.parentSession = "grandchild";
  await assert.rejects(cloudLineage(ctx, "child"), error => error.details.reason === "SESSION_PARENT_IDENTITY_INVALID");
});

test("an open native turn is observed without synthetic closers, promotion, or log writes", async t => {
  const {ctx, calls, rows, install} = fixture();
  const before = JSON.stringify([...rows]);
  const adapter = install(); t.after(() => adapter.dispose());
  assert.equal(adapter.supported, true);
  const signal = new AbortController().signal;
  const stream = ctx.sessionController.follow({address: address(ROOT), assistantStream: true}, signal);
  const first = (await stream.next()).value;
  assert.equal(first.type, "snapshot");
  assert.equal(first.cursor, 1);
  assert.deepEqual(first.records.map(item => item.event.type), ["turn/start", "step/start"]);
  assert.equal(first.projections.values.turnBoundary.open, true);
  assert.deepEqual(first.assistantStream, {revision: 0});
  assert.equal(calls.originalFollow, 0);
  assert.equal(calls.originalObserve, 0);
  assert.deepEqual(calls.resolve, []);
  assert.deepEqual(calls.writes, []);
  assert.equal(calls.closed, calls.open.length);
  assert.equal(JSON.stringify([...rows]), before);
  await stream.return();
});

test("tabs share one observer and receive externally appended durable events and projections", async t => {
  const {ctx, calls, rows, install} = fixture();
  const adapter = install(); t.after(() => adapter.dispose());
  const a = ctx.sessionController.follow({address: address(ROOT)}, new AbortController().signal);
  const b = ctx.sessionController.follow({address: address(ROOT)}, new AbortController().signal);
  await Promise.all([a.next(), b.next()]);
  assert.deepEqual(calls.open, [ROOT]);
  const nextA = a.next(), nextB = b.next();
  rows.get(ROOT).events.push(event(2, "step/end")); rows.get(ROOT).revision = "2";
  const frames = await Promise.all([nextA, nextB]);
  assert.deepEqual(frames.map(frame => frame.value.event.seq), [2, 2]);
  assert.deepEqual(calls.open, [ROOT, ROOT]);
  assert(calls.broadcasts.some(frame => frame.seq === 2 && frame.key === "turnBoundary"));
  await a.return(); await b.return();
  assert.equal(calls.closed, 2);
});

test("Cloud root and descendants reject every explicit mutation and resolver while personal sessions remain writable", async t => {
  const {ctx, calls, install} = fixture();
  const adapter = install(); t.after(() => adapter.dispose());
  for (const id of [ROOT, "child", "grandchild"]) {
    for (const key of ["create", "prompt", "rename", "selectModel", "updateQueue", "cancel", "fork"]) {
      await assert.rejects(ctx.sessionController[key]({sessionId: id}), error => error.code === "session/read-only");
    }
    assert.equal((await ctx.sessionController.agents.resolve(id)).error.code, "session/read-only");
  }
  assert.deepEqual(calls.resolve, []); assert.deepEqual(calls.writes, []);
  assert.deepEqual(await ctx.sessionController.rename({sessionId: "personal"}), {accepted: true});
  const personal = ctx.sessionController.follow({address: address("personal")}, new AbortController().signal);
  assert.equal((await personal.next()).value.type, "personal"); await personal.return();
  assert.equal(calls.originalFollow, 1);
});

test("unsupported method fingerprints retain Cloud refusal instead of restoring native writable follow", async t => {
  const {ctx, calls} = fixture();
  const adapter = installReadOnlySessions(ctx, {pollIntervalMs: 250}); t.after(() => adapter.dispose());
  assert.equal(adapter.supported, false);
  const stream = ctx.sessionController.follow({address: address(ROOT)}, new AbortController().signal);
  await assert.rejects(stream.next(), error => error.details.reason === "NATIVE_VIEW_UNSUPPORTED");
  await assert.rejects(ctx.sessionController.projections({sessionId: ROOT}, new AbortController().signal));
  await assert.rejects(ctx.sessionController.rename({sessionId: "child"}));
  assert.equal(calls.originalFollow, 0); assert.equal(calls.originalObserve, 0);
  assert.deepEqual(calls.open, []); assert.equal(calls.errors.length, 1);
  assert.deepEqual(await ctx.sessionController.rename({sessionId: "personal"}), {accepted: true});
});

test("a foreign rewrite or parent identity change terminates observation without resuming", async t => {
  for (const mutation of [
    row => { row.events[0] = event(0, "different"); row.revision = "2"; },
    row => { row.header.cwd = "/changed-identity"; row.revision = "2"; },
  ]) {
    const {ctx, calls, rows, install} = fixture();
    const adapter = install(); t.after(() => adapter.dispose());
    const stream = ctx.sessionController.follow({address: address(ROOT)}, new AbortController().signal);
    await stream.next(); const pending = stream.next(); mutation(rows.get(ROOT));
    await assert.rejects(pending, error => error.code === "session/read-only");
    assert.equal(calls.originalFollow, 0); assert.deepEqual(calls.resolve, []);
    assert.equal(calls.closed, calls.open.length);
  }
});

test("read failures and cancellation close the native read handle and do not fall back to the native query", async t => {
  const {ctx, calls, install} = fixture();
  let entered;
  const reading = new Promise(resolve => { entered = resolve; });
  ctx.sessionPersistence.open = async (_id, access, {signal}) => {
    assert.equal(access, "read");
    return {header: {id: ROOT, createdAt: 1, cwd: "/synthetic/cloud"}, inheritedEventCount: 0,
      read() { entered(); return new Promise((resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason), {once: true})); },
      async close() { calls.closed++; }};
  };
  const adapter = install(); t.after(() => adapter.dispose());
  const abort = new AbortController();
  const operation = ctx.sessionController.projections({sessionId: ROOT}, abort.signal);
  await reading; abort.abort(new Error("test aborted"));
  await assert.rejects(operation, /test aborted/);
  assert.equal(calls.closed, 1); assert.equal(calls.originalObserve, 0);
});

test("native parent-address validation still rejects a child addressed through another parent", async t => {
  const {ctx, calls, install} = fixture();
  const adapter = install(); t.after(() => adapter.dispose());
  const stream = ctx.sessionController.follow({address: {kind: "subagent", childSessionId: "child", parentSessionId: "personal"}}, new AbortController().signal);
  await assert.rejects(stream.next(), /subagent\/unauthorized/);
  assert.deepEqual(calls.resolve, []); assert.equal(calls.originalFollow, 0);
});
