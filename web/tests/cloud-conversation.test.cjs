const assert = require("node:assert/strict");
const test = require("node:test");
const { IDBFactory } = require("fake-indexeddb");
const load = require("./load-helper.cjs");

const project = "00000000-0000-4000-8000-000000000001";
const task = "00000000-0000-4000-8000-000000000002";
const attempt = "00000000-0000-4000-8000-000000000003";
const otherTask = "00000000-0000-4000-8000-000000000004";
const otherAttempt = "00000000-0000-4000-8000-000000000005";
const target = { project_id: project, task_id: task, attempt_id: attempt, generation: 1 };
const cloud = load("lib/cloud.ts", { TextEncoder, Uint8Array, DataView, Int32Array });
let sequence = 10;
const id = () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, "0")}`;
const message = (change = {}) => ({ ...target, id: "message-1", cursor: 1, role: "USER", text: "Original reply",
  status: "QUEUED", created_at: "2026-11-04T10:00:00Z", session_id: "cloud-session", source: "OPERATOR", ...change });

function setup(request, factory = new IDBFactory()) {
  const journals = load("lib/operation-journal.ts", { indexedDB: factory });
  return load("lib/cloud-conversation.ts", { URLSearchParams, require: name => {
    if (name === "./cloud") return { ...cloud, cloudRequest: request };
    if (name === "./operation-journal") return journals;
    if (name === "./uuid") return { createUuid: id };
    return require(name);
  } });
}

test("message revisions update delivery without duplicating or reordering the conversation", () => {
  const api = setup();
  const first = message();
  const second = message({ id: "message-2", cursor: 2, role: "ASSISTANT", created_at: "2026-11-04T10:01:00Z" });
  const revised = api.mergeConversationMessages([first, second], [{ ...first, cursor: 3, status: "DELIVERED" }]);
  assert.deepEqual(Array.from(revised, row => row.id), ["message-1", "message-2"]);
  assert.equal(revised[0].status, "DELIVERED");
  assert.equal(api.mergeConversationMessages(revised, [first])[0].status, "DELIVERED");
});

test("incremental reads reject another attempt and never advance a regressed cursor", async () => {
  for (const changes of [{ messages: [message({ attempt_id: otherAttempt })] }, { next_cursor: 1 }]) {
    const api = setup(async () => ({ messages: [message()], next_cursor: 3, session: { can_send: true, blocking_reasons: [] }, ...changes }));
    await assert.rejects(api.readConversation(project, task, attempt, 2), /MISMATCH/);
  }
});

test("uncertain sends retain identity without message bodies and do not block another task", async () => {
  const calls = [];
  const api = setup(async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); throw new Error("response lost"); });
  const results = await Promise.all([
    api.sendConversationMessage(target, "Original reply"),
    api.sendConversationMessage({ ...target, task_id: otherTask, attempt_id: otherAttempt }, "Other task reply"),
  ]);
  assert.equal(results.every(row => row.state === "PENDING"), true);
  const pending = await api.conversationJournal.read(project);
  assert.equal(pending.length, 2);
  assert.equal(JSON.stringify(pending).includes("reply"), false);
  assert.equal(pending.every(row => row.state === "UNKNOWN"), true);
  assert.equal((await api.sendConversationMessage(target, "Do not duplicate")).state, "PENDING");
  assert.equal(calls.length, 2);
});

test("two browser reservations send only one message for the same attempt", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const request = async () => { posts++; throw new Error("response lost"); };
  const a = setup(request, factory), b = setup(request, factory);
  await Promise.all([a.sendConversationMessage(target, "Original reply"), b.sendConversationMessage(target, "Another reply")]);
  assert.equal(posts, 1);
  assert.equal((await a.conversationJournal.read(project)).length, 1);
});

test("reopening an uncertain send queries its original key only, including NOT_FOUND", async () => {
  const factory = new IDBFactory(); let posts = 0;
  const original = setup(async () => { posts++; throw new Error("response lost"); }, factory);
  await original.sendConversationMessage(target, "Original reply");
  const [pending] = await original.conversationJournal.read(project);
  let found = false; const reads = [];
  const reopened = setup(async (path, options) => {
    assert.equal(options, undefined); reads.push(path);
    if (!found) throw new cloud.CloudApiError(404, "not found");
    return message({ operation_key: pending.operation_key });
  }, factory);
  await assert.rejects(reopened.reconcileConversationMessage(pending));
  assert.equal((await reopened.conversationJournal.read(project))[0].operation_key, pending.operation_key);
  assert.equal((await reopened.sendConversationMessage(target, "Original reply")).state, "PENDING");
  found = true;
  await reopened.reconcileConversationMessage(pending);
  assert.equal((await reopened.conversationJournal.read(project)).length, 0);
  assert.equal(posts, 1);
  assert.equal(reads.every(path => path.includes(encodeURIComponent(pending.operation_key))), true);
});

test("mismatched receipt identities or text never settle the original message", async () => {
  for (const mismatch of [{ generation: 2 }, { attempt_id: otherAttempt }, { text: "Changed text" }, { role: "ASSISTANT" }]) {
    let body;
    const api = setup(async (_path, options) => {
      body = JSON.parse(options.body);
      return message({ operation_key: body.operation_key, ...mismatch });
    });
    assert.equal((await api.sendConversationMessage(target, "Original reply")).state, "PENDING");
    assert.equal((await api.conversationJournal.read(project))[0].state, "UNKNOWN");
  }
});

test("an accepted message settles only its own key; definite rejection permits an explicit new message", async () => {
  const accepted = setup(async (_path, options) => message({ ...JSON.parse(options.body) }));
  assert.equal((await accepted.sendConversationMessage(target, " Original reply ")).state, "ACCEPTED");
  assert.equal((await accepted.conversationJournal.read(project)).length, 0);
  const rejected = setup(async () => { throw new cloud.CloudApiError(422, "not accepted"); });
  assert.equal((await rejected.sendConversationMessage(target, "Original reply")).state, "REJECTED");
  assert.equal((await rejected.conversationJournal.read(project)).length, 0);
});

test("unavailable durable storage prevents sending", async () => {
  let posts = 0;
  const api = setup(async () => { posts++; }, { open() { throw new Error("storage denied"); } });
  await assert.rejects(api.sendConversationMessage(target, "Original reply"));
  assert.equal(posts, 0);
});

test("conversation renders untrusted Markdown as text and separates delivery from handling", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const api = setup();
  const { ConversationPanel, conversationStatus } = load("app/cloud-tasks/[taskId]/conversation-panel.tsx", { require: name => {
    if (name === "@tanstack/react-query") return { useQuery: () => ({ data: {
      messages: [message({ text: "<script>private()</script>\n## Agent output", status: "DELIVERED", source: "IMPORTED_HISTORY", observed_at: "2026-11-03T09:00:00Z" })],
      next_cursor: 1, observed_at: "2026-11-04T10:00:00Z", session: { can_send: false, state: "OFFLINE", blocking_reasons: [] },
    }, refetch() {} }) };
    if (name === "@/lib/cloud-conversation") return api;
    if (name === "@/lib/cloud") return cloud;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: en => en, formatDate: date => date }) };
    if (name === "./live-questions-panel") return { LiveQuestionsPanel: () => null };
    return require(name);
  } });
  const row = { id: attempt, attempt_no: 1, status: "RECOVERY_REQUIRED" };
  const html = renderToStaticMarkup(React.createElement(ConversationPanel, { projectId: project, taskId: task, attempt: row,
    attempts: [row], blocked: false, artifactCount: 0, onRecovery() {}, onArtifacts() {} }));
  assert.ok(html.includes("&lt;script&gt;private()&lt;/script&gt;"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("View execution and recovery"));
  assert.ok(html.includes("Imported from the original session"));
  assert.ok(html.includes("Original message"));
  assert.ok(html.includes("2026-11-03T09:00:00Z"));
  assert.ok(html.includes("Imported"));
  assert.equal(conversationStatus("DELIVERED", en => en), "Delivered to the session");
  assert.ok(html.includes("Delivery does not confirm processing"));
});

test("a selected historical attempt is read only even if the session projection permits sending", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const api = setup();
  const { ConversationPanel } = load("app/cloud-tasks/[taskId]/conversation-panel.tsx", { require: name => {
    if (name === "react") return { ...React, useState: initial => initial === attempt ? [otherAttempt, () => {}] : React.useState(initial) };
    if (name === "@tanstack/react-query") return { useQuery: () => ({ data: {
      messages: [], next_cursor: 1, has_more: true, session: { can_send: true, generation: 1, state: "AWAITING_REPLY", blocking_reasons: [] },
    }, refetch() {} }) };
    if (name === "@/lib/cloud-conversation") return api;
    if (name === "@/lib/cloud") return cloud;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: en => en, formatDate: date => date }) };
    if (name === "./live-questions-panel") return { LiveQuestionsPanel: props => React.createElement("span", null, props.blocked ? "question-read-only" : "question-writable") };
    return require(name);
  } });
  const row = { id: attempt, attempt_no: 2, status: "RUNNING" };
  const html = renderToStaticMarkup(React.createElement(ConversationPanel, { projectId: project, taskId: task, attempt: row,
    attempts: [{ ...row, id: otherAttempt, attempt_no: 1, status: "FAILED" }, row], blocked: false, artifactCount: 0, onRecovery() {}, onArtifacts() {} }));
  assert.ok(html.includes("History · read only"));
  assert.ok(html.includes("question-read-only"));
  assert.ok(html.includes("Load more messages"));
  assert.ok(!html.includes("<textarea"));
  assert.ok(!html.includes("Send message"));
});
