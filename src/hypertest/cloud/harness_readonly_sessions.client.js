// Native client-module format; no independent page or input implementation.
window.__ModuleLoader__.load({
  id: "hypertest-cloud-readonly-view",
  factory: () => {
    const name = "hypertest-cloud-readonly-view";
    const root = /^cloud-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

    function cloudSession(id, rows) {
      const seen = new Set();
      while (typeof id === "string" && id && !seen.has(id) && seen.size < 64) {
        if (root.test(id)) return true;
        seen.add(id);
        // The native catalog derives parentId from the durable parentSession
        // header or its subagent catalog. Display names are never authority.
        id = rows[id]?.parentId;
      }
      return false;
    }

    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(name, {
        zh: {readonly: "Cloud 会话在此只读，发送消息请使用 HyperTest。"},
        en: {readonly: "This Cloud session is read-only here. Send messages in HyperTest."},
      }), "hypertest: native read-only description");
      const t = ctx.locale.bind(name);
      const protectedSessions = new Map();
      let disposed = false;

      function protect(id) {
        if (protectedSessions.has(id)) return;
        const store = ctx.conversation.blocks.storeFor(id);
        const record = {reason: undefined, dispose: undefined};
        const enforce = () => {
          if (disposed) return;
          const current = store.getSnapshot();
          // Other native reasons remain visible and already disable input. If
          // their owner clears them, the Cloud read-only reason takes over.
          if (current !== undefined && current.reason !== record.reason) return;
          const reason = t("readonly");
          record.reason = reason;
          if (current?.reason !== reason) ctx.conversation.blocks.set(id, {reason});
        };
        record.enforce = enforce;
        record.dispose = store.subscribe(enforce);
        protectedSessions.set(id, record);
        enforce();
      }

      const sync = () => {
        if (disposed) return;
        const rows = ctx.sessions.list.getSnapshot().byId;
        for (const id of Object.keys(rows)) if (cloudSession(id, rows)) protect(id);
        // A catalog refresh may temporarily omit an already opened session.
        // Immutable known Cloud lineage must not become editable in that gap.
        for (const record of protectedSessions.values()) record.enforce();
      };
      const stopSessions = ctx.sessions.list.subscribe(sync);
      const stopLocale = ctx.locale.subscribe(sync);
      ctx.effect(() => () => {
        disposed = true;
        stopSessions();
        stopLocale();
        for (const [id, record] of protectedSessions) {
          record.dispose();
          if (record.reason !== undefined &&
              ctx.conversation.blocks.storeFor(id).getSnapshot()?.reason === record.reason) {
            ctx.conversation.blocks.set(id, undefined);
          }
        }
        protectedSessions.clear();
      }, "hypertest: native read-only composer");
      sync();
    }

    return {name, inject: ["conversation", "sessions", "locale"], apply};
  },
});
