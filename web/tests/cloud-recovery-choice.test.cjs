const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

function harness(blocked = false) {
  const slots = []; let cursor = 0; const writes = [];
  const ui = Object.fromEntries(["Alert", "Button", "Select", "Space"].map((name) => [name, name]));
  ui.Form = "Form"; ui.Form.Item = "Form.Item";
  ui.Input = { TextArea: "TextArea" }; ui.Typography = { Title: "Title", Paragraph: "Paragraph", Text: "Text" };
  const jsx = (type, props) => ({ type, props });
  const component = load("app/cloud-tasks/[taskId]/recovery-choice.tsx", { require: (name) => {
    if (name === "react") return { useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], (v) => { slots[i] = v; }]; } };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en, formatDate: (v) => v }) };
    return require(name);
  } });
  const props = { attempt: { id: "original", reason: "WORKER_RUNTIME_FAILED" }, blocked,
    document: { runs: [{ id: "run", attempt_id: "original", reported_result: "FAIL" }], assets: [], artifacts: [], recovery_choices: [] },
    onSubmit: async (value) => { writes.push(value); } };
  const nodes = (v) => !v || typeof v !== "object" ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children), ...nodes(v.props?.description)];
  const render = () => { cursor = 0; return nodes(component.RecoveryChoice(props)); };
  return { render, writes, props };
}

test("A human decision saves an explicit choice and note without starting work", async () => {
  for (const selected of ["CONTINUE_ORIGINAL_SESSION", "RETEST", "END_EXECUTION"]) {
    const h = harness();
    const form = () => h.render().find((node) => node.type === "Form");
    assert.deepEqual(Array.from(h.render().find((node) => node.type === "Select").props.options, (item) => item.value), ["CONTINUE_ORIGINAL_SESSION", "RETEST", "END_EXECUTION"]);
    form().props.onFinish(); assert.equal(h.writes.length, 0);
    h.render().find((node) => node.type === "TextArea").props.onChange({ target: { value: "Preserve existing work" } });
    h.render().find((node) => node.type === "Select").props.onChange(selected);
    form().props.onFinish();
    assert.equal(h.writes.length, 1);
    assert.equal(h.writes[0].operation, "RECORD_RECOVERY_CHOICE");
    assert.equal(h.writes[0].choice, selected);
    assert.equal(h.writes[0].note, "Preserve existing work");
  }
});

test("Blocked or incomplete decisions cannot be submitted", () => {
  const h = harness(true);
  h.render().find((node) => node.type === "TextArea").props.onChange({ target: { value: "note" } });
  h.render().find((node) => node.type === "Select").props.onChange("CONTINUE_ORIGINAL_SESSION");
  h.render().find((node) => node.type === "Form").props.onFinish();
  assert.equal(h.writes.length, 0);
});
