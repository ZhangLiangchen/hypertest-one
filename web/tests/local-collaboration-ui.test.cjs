const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const load = require("./load-helper.cjs");
function nodes(element) { if (!element || typeof element !== "object") return []; if (Array.isArray(element)) return element.flatMap(nodes); return [element, ...nodes(element.props?.children)]; }
function text(element) { if (element === null || element === undefined || typeof element === "boolean") return ""; if (typeof element !== "object") return String(element); if (Array.isArray(element)) return element.map(text).join(""); return text(element.props?.children); }
const ui = { Alert: "Alert", Button: "Button", Descriptions: "Descriptions", Empty: "Empty", Input: Object.assign(() => null, { TextArea: "TextArea" }), Select: "Select", Space: "Space", Table: "Table", Tag: "Tag", Typography: { Title: "Title", Text: "Text", Paragraph: "Paragraph" } };
function harness() {
  const slots = []; let cursor = 0, locale = "en", queried = 0;
  const task = { id: "task-a", project_id: "project-a", version: 4, binding_state: "BOUND", owner_actor_ref: "owner-a", session_id: "original-root", provider: "codex", reported_result: "FAIL" };
  const state = { enabled: true, primary_participant_id: "primary-a", primary_generation: 3, participants: [{ id: "primary-a", provider: "codex", session_id: "original-root", actor_ref: "owner-a", status: "ACTIVE", role: "PRIMARY", initial_binding: true }, { id: "member-b", provider: "codex", session_id: "root-b", actor_ref: "owner-a", status: "ACTIVE", role: "CONTRIBUTOR", assignment: "Review failures" }, { id: "member-c", provider: "codex", session_id: "root-c", actor_ref: "owner-a", status: "AUTHORIZED", role: "CONTRIBUTOR" }], contributions: [{ id: "contribution-1", participant_id: "member-b", kind: "REPORT", stable_key: "same-key", revision: 1, task_version: 4, actor_ref: "owner-a", provider: "codex", session_id: "root-b", content: { markdown: "Original FAIL report", reported_result: "FAIL" } }], publications: [] };
  const document = { task, collaboration: state, operation_history: [] }, requests = [];
  const operation = { pending: null, busy: false, blocked: false, ready: true, storageError: false, error: null, submit: async (request) => { requests.push(request); return null; }, reconcile: async () => { queried++; return null; } };
  const hooks = { ...React, useState(value) { const index = cursor++; if (!(index in slots)) slots[index] = value; return [slots[index], (next) => { slots[index] = typeof next === "function" ? next(slots[index]) : next; }]; } };
  const deps = { react: hooks, antd: ui, "@tanstack/react-query": { useQuery: () => ({ data: document, isLoading: false, isFetching: false, refetch: async () => document }), useQueryClient: () => ({ setQueryData() {}, invalidateQueries: async () => {} }) },
    "@/lib/api": { errorText: (error) => error.message, getTaskCollaboration() {} }, "@/lib/local-collaboration": { collaborationProfile: "local-task-collaboration/v1alpha1" }, "@/lib/local-collaboration-operation": { useCollaborationOperation: () => operation }, "@/lib/i18n": { useI18n: () => ({ locale, t: (en, zh) => locale === "zh" ? zh : en, formatDate: (value) => value || "—" }) }, "@/lib/uuid": { createUuid: () => "new-explicit-intent" }, "./task-records": { ReportedResultTag: "ReportedResultTag" } };
  const { LocalTaskCollaboration } = load("app/tasks/local-task-collaboration.tsx", { require: (name) => name in deps ? deps[name] : require(name) });
  const render = () => { cursor = 0; return LocalTaskCollaboration({ task }); };
  return { render, task, state, operation, requests, setLocale: (value) => { locale = value; }, get queried() { return queried; } };
}
const button = (tree, label) => nodes(tree).find((node) => node.type === ui.Button && text(node) === label);
const input = (tree, suffix) => nodes(tree).find((node) => node.props?.id?.endsWith(`-${suffix}`));

test("retired Local collaboration keeps participation and contributions visible without new writes", () => {
  const h = harness();
  for (const locale of ["en", "zh"]) {
    h.setLocale(locale); const tree = h.render();
    assert.equal(button(tree, locale === "en" ? "Authorize session" : "授权会话加入"), undefined);
    assert.equal(nodes(tree).some((node) => node.type === "form"), false);
    const table = nodes(tree).find((node) => node.type === ui.Table && node.props.dataSource === h.state.participants);
    const actions = table.props.columns.find((column) => column.key === "actions");
    for (const participant of h.state.participants) assert.equal(actions.render(null, participant), "—");
    assert.ok(text(tree).includes(locale === "en" ? "explicit CLI archives" : "CLI 显式归档"));
  }
  assert.equal(h.requests.length, 0);
});

test("pending operations offer original-key recovery, while initial binding and original FAIL keep their meanings", async () => {
  const h = harness(); h.operation.pending = { operation: "AUTHORIZE", idempotency_key: "original-key", expected_version: 4 }; h.operation.blocked = true;
  const tree = h.render(); assert.equal(button(tree, "Authorize session"), undefined);
  const tables = nodes(tree).filter((node) => node.type === ui.Table), participants = tables[0];
  assert.equal(text(participants.props.columns.find((c) => c.key === "time").render(null, h.state.participants[0])), "Initial binding retained");
  const result = tables[1].props.columns.find((c) => c.key === "result").render(null, h.state.contributions[0]); assert.equal(result.props.result, "FAIL");
  const notice = nodes(tree).find((node) => node.type === ui.Alert && node.props.action);
  await notice.props.action.props.onClick(); assert.equal(h.queried, 1); assert.equal(h.requests.length, 0);
});
