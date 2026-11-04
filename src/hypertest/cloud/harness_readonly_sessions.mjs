/** Native Web viewing of Cloud sessions never acquires a Harness writer. */
import {createHash} from "node:crypto";

export const name = "hypertest-cloud-readonly-view";
export const inject = ["sessionController", "sessionPersistence", "sessionQuery", "sessionProjections", "sessions"];
const CLOUD_ROOT = /^cloud-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// Audited from the installed App's app.asar, not the independently released SDK.
// Typert resolves the live Service method on each invocation. No asar is patched.
const METHODS = {
  resolve: "e35c27a59494c10763dac8d3ed0e4dc0d101c14341a4877530a375bf7b385679",
  broadcast: "a54f5c7d19fc0c23d405f26b99d6d89af1a010a895d5d4635d1f58b85c48dd26",
  page: "ff53b87b493f733fa0e8cbe9693f3a770612c543401a723b64d7c7cba0578253",
  sourceFor: "7b238698f23c0f502f8b9db594ca7a103d8728507a2d28f12fd8089a3a2c92da",
  follow: "1aad9384a6f809fb39723c16fdf281cfac5990f5e8d92f847699c7c867f086b4",
  projections: "91dad80f6ed1006218c7ff2ad78127ea0eed6a4487a91220f6a1ca4293015045",
  observeSession: "4edcde028e9033c470c1c19517c19685fe9c4330634d481445ea89a58c0987dd",
  restore: "1eb3f77cd74ec76311375055479e5a6888f341ddbe5119ea9bcd8e0edf698382",
};

function failure(reason = "CLOUD_SESSION_READ_ONLY") {
  // The official protocol explicitly identifies RemoteError structurally across
  // bundles; this keeps a file plugin independent of private npm resolution.
  return Object.assign(new Error("This Cloud session is read-only here. Send messages in HyperTest."), {
    name: "RemoteError", isDSHRemoteError: true, code: "session/read-only", details: {reason},
  });
}

// Cordis wraps Service methods in invocation-scoped shadow functions. Inspect
// and replace the underlying method, while preserving each caller's `this`.
// This is the same shared symbol used by the official Typert gateway.
function originalOf(value) { return value?.[Symbol.for("cordis.original")] ?? value; }

export function methodFingerprints(ctx) {
  const controller = originalOf(ctx.sessionController);
  const methods = {
    resolve: controller.agents?.resolve, broadcast: controller.controlState?.broadcast,
    page: controller.history?.page, sourceFor: controller.history?.sourceFor,
    follow: controller.follow, projections: controller.projections,
    observeSession: originalOf(ctx.sessionQuery).observeSession, restore: originalOf(ctx.sessionProjections).restore,
  };
  return Object.fromEntries(Object.entries(methods).map(([key, method]) => [key,
    typeof method === "function" ? digest(Function.prototype.toString.call(method).replace(/\s+/g, "")) : null,
  ]));
}

function digest(value) { return createHash("sha256").update(value).digest("hex"); }
function identity(header) {
  return JSON.stringify([header.id, header.createdAt, header.cwd, header.parentSession,
    header.origin, header.isSeeded, header.delegationDepth ?? 0]);
}

/** Follow immutable native parentSession links; child names are not authority. */
export async function cloudLineage(ctx, sessionId, signal) {
  const seen = new Set();
  const chain = [];
  let id = sessionId;
  while (typeof id === "string" && id) {
    signal?.throwIfAborted();
    if (seen.has(id) || seen.size >= 64) throw failure("SESSION_PARENT_IDENTITY_INVALID");
    seen.add(id);
    const stored = await ctx.sessionPersistence.stat(id, {signal});
    signal?.throwIfAborted();
    const header = stored?.header ?? ctx.sessions.get(id)?.header;
    if (header && header.id !== id) throw failure("SESSION_IDENTITY_CHANGED");
    chain.push(header ? identity(header) : id);
    if (CLOUD_ROOT.test(id)) return {managed: true, identity: JSON.stringify(chain)};
    if (!header) {
      // A missing fresh ordinary ID may be created normally. A broken parent
      // chain must never fall back to activating an unidentified child.
      if (id !== sessionId) throw failure("SESSION_PARENT_UNAVAILABLE");
      return {managed: false};
    }
    id = header.parentSession;
  }
  return {managed: false};
}

function raceAbort(promise, signal) {
  if (!signal) return promise;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, {once: true});
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

/** An observation is a borrowed immutable cut, never a published native Session. */
function observation(snapshot, projectionMode) {
  return {
    source: "prepared", header: snapshot.header, inheritedEventCount: snapshot.inheritedEventCount,
    events: snapshot.events, cursor: snapshot.cursor, revision: snapshot.revision,
    ...(projectionMode === "none" ? {} : {projections: snapshot.projections}),
    retain: () => observation(snapshot, projectionMode), [Symbol.dispose]() {},
  };
}

async function readDurable(ctx, sessionId, signal, previous) {
  signal.throwIfAborted();
  const before = await ctx.sessionPersistence.stat(sessionId, {signal});
  if (!before || before.header.id !== sessionId) throw failure("SESSION_SOURCE_UNAVAILABLE");
  if (previous && identity(before.header) !== identity(previous.header)) throw failure("SESSION_IDENTITY_CHANGED");
  if (previous?.revision === before.revision) return previous;
  // Unlike sessionQuery's cold read, this path does not append synthetic
  // interruptedTurnClosers to a turn that another process is still executing.
  const handle = await ctx.sessionPersistence.open(sessionId, "read", {signal});
  let read;
  try {
    signal.throwIfAborted();
    read = await handle.read(0, undefined, {signal});
    signal.throwIfAborted();
    if (handle.header.id !== sessionId || identity(handle.header) !== identity(before.header)) {
      throw failure("SESSION_IDENTITY_CHANGED");
    }
  } finally {
    await handle.close();
  }
  const events = read.events;
  for (let index = 0; index < events.length; index++) {
    if (events[index].seq !== index) throw failure("SESSION_LOG_NOT_CONTIGUOUS");
  }
  if (previous && (events.length < previous.events.length ||
      digest(JSON.stringify(events.slice(0, previous.events.length))) !== previous.digest)) {
    throw failure("SESSION_LOG_PREFIX_CHANGED");
  }
  const projected = ctx.sessionProjections.restore(previous?.checkpoint ?? {}, events, 0,
    handle.header, handle.inheritedEventCount);
  return {
    header: handle.header, inheritedEventCount: handle.inheritedEventCount,
    events, cursor: events.length - 1, revision: before.revision,
    projections: projected.snapshot, checkpoint: projected.checkpoint,
    digest: digest(JSON.stringify(events)),
  };
}

/** One polling read per observed Session, shared by all native browser tabs. */
class Observer {
  constructor(host, sessionId, lineage) {
    this.host = host;
    this.sessionId = sessionId;
    this.lineage = lineage;
    this.controller = new AbortController();
    this.waiters = new Set();
    this.refs = 0;
  }
  refresh() {
    if (this.pending) return this.pending;
    this.pending = (async () => {
      const signal = this.controller.signal;
      const lineage = await cloudLineage(this.host.ctx, this.sessionId, signal);
      if (!lineage.managed || lineage.identity !== this.lineage.identity) throw failure("SESSION_IDENTITY_CHANGED");
      const next = await readDurable(this.host.ctx, this.sessionId, signal, this.current);
      if (next === this.current) return;
      this.current = next;
      for (const [key, value] of Object.entries(next.projections.values)) {
        // This is the read-only client control channel. Do not emit session/event:
        // native persistence listeners would interpret that as a local mutation.
        this.host.broadcast({type: "projection", sessionId: this.sessionId,
          key, value, seq: next.projections.asOfSeq});
      }
      this.notify();
    })().catch(error => {
      this.error = error;
      clearInterval(this.timer);
      this.notify();
      throw error;
    }).finally(() => { this.pending = undefined; });
    return this.pending;
  }
  notify() { for (const wake of this.waiters) wake(); }
  async acquire(signal) {
    this.refs++;
    try {
      if (!this.current) await raceAbort(this.refresh(), signal);
      if (this.error) throw this.error;
      this.timer ??= setInterval(() => this.refresh().catch(() => {}), this.host.interval);
      this.timer.unref?.();
      return this;
    } catch (error) { this.release(); throw error; }
  }
  async after(cursor, signal) {
    for (;;) {
      signal.throwIfAborted();
      this.controller.signal.throwIfAborted();
      if (this.error) throw this.error;
      if (this.current.cursor > cursor) return this.current;
      let wake;
      const waiting = new Promise(resolve => { wake = resolve; });
      this.waiters.add(wake);
      try { await raceAbort(waiting, signal); }
      finally { this.waiters.delete(wake); }
    }
  }
  release() {
    this.refs--;
    if (this.refs > 0) return;
    this.host.observers.delete(this.sessionId);
    clearInterval(this.timer);
    this.controller.abort();
    this.notify();
  }
  async dispose() {
    clearInterval(this.timer);
    this.controller.abort();
    this.notify();
    await this.pending?.catch(() => {});
  }
}

/** Test seam accepts explicit method fingerprints; production apply never does. */
export function installReadOnlySessions(ctx, config = {}, expectedMethods = METHODS) {
  const actual = methodFingerprints(ctx);
  const interval = config.pollIntervalMs ?? 500;
  const supported = Number.isInteger(interval) && interval >= 250 && interval <= 5000 &&
    Object.keys(METHODS).every(key => actual[key] === expectedMethods[key]);
  const controller = originalOf(ctx.sessionController);
  const host = {ctx, interval, observers: new Map(),
    broadcast: frame => controller.controlState.broadcast(frame)};
  const restores = [];
  const wrap = (object, key, factory) => {
    const original = object[key];
    const replacement = factory(original);
    object[key] = replacement;
    restores.push(() => { if (object[key] === replacement) object[key] = original; });
  };
  const requireSupported = () => { if (!supported) throw failure("NATIVE_VIEW_UNSUPPORTED"); };
  const target = address => address?.kind === "session" ? address.sessionId : address?.childSessionId;
  const isManaged = async (id, signal) => (await cloudLineage(ctx, id, signal)).managed;

  // A failed fingerprint check leaves these Cloud refusals installed. Throwing
  // out of apply would let Cordis unload the plugin and restore writable follow.
  if (controller.agents) wrap(controller.agents, "resolve", original => async function(sessionId, ...args) {
    if (await isManaged(sessionId)) return {error: failure(supported ? undefined : "NATIVE_VIEW_UNSUPPORTED")};
    return original.call(this, sessionId, ...args);
  });
  for (const key of ["create", "prompt", "rename", "selectModel", "updateQueue", "cancel", "fork"]) {
    if (typeof controller[key] !== "function") continue;
    wrap(controller, key, original => async function(request, ...args) {
      if (await isManaged(request?.sessionId)) throw failure();
      return original.call(this, request, ...args);
    });
  }
  wrap(originalOf(ctx.sessionQuery), "observeSession", original => async function(sessionId, options = {}) {
    const lineage = await cloudLineage(ctx, sessionId, options.signal);
    if (!lineage.managed) return original.call(this, sessionId, options);
    requireSupported();
    const active = host.observers.get(sessionId);
    if (active?.error) throw active.error;
    if (active && active.lineage.identity !== lineage.identity) throw failure("SESSION_IDENTITY_CHANGED");
    const snapshot = active?.current ?? await readDurable(ctx, sessionId,
      options.signal ?? new AbortController().signal);
    return observation(snapshot, options.projectionMode);
  });
  wrap(controller, "projections", original => async function(request, signal) {
    if (!await isManaged(request.sessionId, signal)) return original.call(this, request, signal);
    requireSupported();
    const source = await ctx.sessionQuery.observeSession(request.sessionId, {signal});
    try { return {kind: "sequenced", ...source.projections}; }
    finally { source[Symbol.dispose](); }
  });
  wrap(controller, "page", original => async function(request, signal) {
    if (await isManaged(target(request.address), signal)) requireSupported();
    return original.call(this, request, signal);
  });
  wrap(controller, "follow", original => async function* (request, signal) {
    const id = target(request.address);
    const lineage = await cloudLineage(ctx, id, signal);
    if (!lineage.managed) { yield* original.call(this, request, signal); return; }
    requireSupported();
    let observer = host.observers.get(id);
    if (!observer) { observer = new Observer(host, id, lineage); host.observers.set(id, observer); }
    await observer.acquire(signal);
    try {
      // Reuse native address validation and message-aligned pagination. The
      // original follow is NEVER invoked, so no background promotion can run.
      const source = await this.history.sourceFor(request.address, signal, true);
      let cursor;
      try {
        cursor = source.cursor;
        const page = await this.history.page({...request, throughSeq: cursor}, signal);
        yield {type: "snapshot", header: source.header, cursor, records: page.records,
          hasMore: page.hasMore, projections: source.projections,
          ...(request.assistantStream === true ? {assistantStream: {revision: 0}} : {})};
      } finally { source[Symbol.dispose](); }
      while (!signal.aborted) {
        const next = await observer.after(cursor, signal);
        for (const event of next.events.slice(cursor + 1)) {
          signal.throwIfAborted();
          if (event.seq !== cursor + 1) throw failure("SESSION_LOG_NOT_CONTIGUOUS");
          cursor = event.seq;
          yield {type: "event", event};
        }
      }
    } finally { observer.release(); }
  });
  if (!supported) ctx.logger.error("HyperTest native Cloud view version is unsupported; Cloud view and writes remain blocked");
  return {
    supported,
    async dispose() {
      await Promise.all([...host.observers.values()].map(observer => observer.dispose()));
      host.observers.clear();
      for (const restore of restores.reverse()) restore();
    },
  };
}

export function apply(ctx, config) {
  const installed = installReadOnlySessions(ctx, config);
  ctx.effect(() => () => installed.dispose(), "hypertest-cloud-readonly-view");
}
