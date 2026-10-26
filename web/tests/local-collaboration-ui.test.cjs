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

test("exact session authorization preserves bilingual input across a version conflict and explicitly adopts the reviewed version", async () => {
  const h = harness(); button(h.render(), "Authorize session").props.onClick();
  input(h.render(), "session").props.onChange({ target: { value: "new-real-root" } });
  input(h.render(), "assignment").props.onChange({ target: { value: "Preserve original review draft" } });
  h.operation.error = new Error("TASK_VERSION_CONFLICT"); h.task.version = 6; h.setLocale("zh");
  let tree = h.render(); assert.equal(input(tree, "session").props.value, "new-real-root"); assert.equal(input(tree, "assignment").props.value, "Preserve original review draft");
  const review = nodes(tree).find((node) => node.type === ui.Button && text(node).startsWith("使用已核对的最新版本")); review.props.onClick();
  tree = h.render(); await nodes(tree).find((node) => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(h.requests.length, 1); assert.equal(h.requests[0].actor_ref, "owner-a"); assert.equal(h.requests[0].expected_version, 6); assert.equal(h.requests[0].session_id, "new-real-root"); assert.equal(h.requests[0].assignment, "Preserve original review draft");
  assert.equal(input(h.render(), "session").props.value, "new-real-root", "failure retains the form");
});

test("only joined sessions can become primary, and handoff carries explicit unresolved materials", async () => {
  const h = harness(), table = nodes(h.render()).find((node) => node.type === ui.Table && node.props.dataSource === h.state.participants);
  const actions = table.props.columns.find((column) => column.key === "actions");
  assert.equal(button(actions.render(null, h.state.participants[2]), "Make primary"), undefined);
  button(actions.render(null, h.state.participants[1]), "Make primary").props.onClick();
  input(h.render(), "materials").props.onChange({ target: { value: "Accepted report\nOriginal FAIL revision" } });
  input(h.render(), "unresolved").props.onChange({ target: { value: "Old journal unobserved" } });
  await nodes(h.render()).find((node) => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.deepEqual(JSON.parse(JSON.stringify(h.requests[0].handoff)), { materials: ["Accepted report", "Original FAIL revision"], unresolved_items: ["Old journal unobserved"], private_journals_observed: false });
  assert.equal(h.requests[0].participant_id, "member-b"); assert.equal(h.requests[0].expected_primary_generation, 3);
});

test("pending operations offer original-key recovery, while initial binding and original FAIL keep their meanings", async () => {
  const h = harness(); h.operation.pending = { operation: "AUTHORIZE", idempotency_key: "original-key", expected_version: 4 }; h.operation.blocked = true;
  const tree = h.render(); assert.equal(button(tree, "Authorize session").props.disabled, true);
  const tables = nodes(tree).filter((node) => node.type === ui.Table), participants = tables[0];
  assert.equal(text(participants.props.columns.find((c) => c.key === "time").render(null, h.state.participants[0])), "Initial binding retained");
  const result = tables[1].props.columns.find((c) => c.key === "result").render(null, h.state.contributions[0]); assert.equal(result.props.result, "FAIL");
  const notice = nodes(tree).find((node) => node.type === ui.Alert && node.props.action);
  await notice.props.action.props.onClick(); assert.equal(h.queried, 1); assert.equal(h.requests.length, 0);
});
