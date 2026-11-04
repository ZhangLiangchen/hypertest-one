const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

const jsx = (type, props) => ({ type, props });
const component = load("app/cloud-tasks/[taskId]/recovery-choice-history.tsx", { require: (name) => {
  if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
  if (name === "antd") return { Typography: { Title: "Title", Paragraph: "Paragraph", Text: "Text" } };
  if (name === "@/lib/i18n") return { useI18n: () => ({ t: (_en, zh) => zh, formatDate: (v) => v }) };
  return require(name);
} });
const contents = (value) => value == null ? "" : Array.isArray(value) ? value.map(contents).join(" ")
  : typeof value === "object" ? contents(value.props?.children) : String(value);
const choice = (changes = {}) => ({ attempt_id: "first", operation_key: "key:1", choice: "CONTINUE_ORIGINAL_SESSION",
  note: "保留原结果", actor_ref: "operator:test", recorded_at: "2026-11-04T01:00:00Z", identity_anchor: "MISSING", action_started: false, ...changes });

test("Historical choices remain visible under their own execution, with actor and identity limitations", () => {
  const other = choice({ attempt_id: "second", operation_key: "key:2", note: "other execution" });
  const content = contents(component.RecoveryChoiceHistory({ attemptId: "first", choices: [choice(), other] }));
  for (const text of ["继续原会话", "保留原结果", "operator:test", "2026-11-04T01:00:00Z", "缺少早期会话身份记录", "记录选择时，所选操作尚未开始"]) assert.ok(content.includes(text), text);
  assert.equal(content.includes("other execution"), false);
});

test("Snapshots created before recovery decisions remain readable", () => {
  assert.equal(component.RecoveryChoiceHistory({ attemptId: "first" }), null);
  assert.equal(component.RecoveryChoiceHistory({ attemptId: "first", choices: [] }), null);
});

test("Present identity records and unknown values do not imply identity was verified", () => {
  const recorded = contents(component.RecoveryChoiceHistory({ attemptId: "first", choices: [choice({ identity_anchor: "RECORDED" })] }));
  assert.ok(recorded.includes("不能核实会话身份"));
  const unknown = contents(component.RecoveryChoiceHistory({ attemptId: "first", choices: [choice({ identity_anchor: "UNKNOWN" })] }));
  assert.ok(unknown.includes("情况未知"));
});
