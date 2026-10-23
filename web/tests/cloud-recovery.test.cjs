const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

const recoveryHelpers = () => load("lib/cloud-recovery.ts");
const attempt = (change = {}) => ({ id: "attempt-1", status: "RECOVERY_REQUIRED", checkpoint: {}, runtime_metadata: {}, ...change });
const capabilities = { enabled: true, supported: { resume_attempt: false, reconcile_attempt: true }, recovery: { resume_supported: false, reconcile_supported: true } };
const recovery = { resume_supported: false, resume_reason: "SDK_RESUME_UNSUPPORTED", old_owner_fenced: true,
  local_processes_stopped_observed: false, pending_operation_keys: [], remote_operations_reconciled: true,
  can_reconcile: true, blocking_reasons: [], reconciliation_source: "OPERATOR_ATTESTATION", budget_disposition: "KEEP_HELD", phase: "RECONCILIATION_REQUIRED" };

test("Manual closure needs matching server preconditions and cannot erase an original UNKNOWN key", () => {
  const { cloudRecoveryView } = recoveryHelpers();
  assert.equal(cloudRecoveryView(attempt(), capabilities, recovery).canReconcile, true);
  for (const [current, caps, live] of [
    [attempt(), undefined, recovery], [attempt(), capabilities, undefined],
    [attempt(), capabilities, { ...recovery, old_owner_fenced: false }],
    [attempt(), capabilities, { ...recovery, remote_operations_reconciled: false }],
    [attempt(), capabilities, { ...recovery, can_reconcile: false }],
    [attempt(), capabilities, { ...recovery, pending_operation_keys: ["ssh:original"] }],
    [attempt({ checkpoint: { pending_operation_keys: ["report:original"] } }), capabilities, recovery],
    [attempt({ status: "WAITING_INPUT" }), capabilities, recovery],
    [attempt({ status: "CANCELLED" }), capabilities, recovery],
  ]) assert.equal(cloudRecoveryView(current, caps, live).canReconcile, false);
});

test("Cancellation, stop uncertainty, reconciliation and terminal state remain distinct from session resume", () => {
  const { cloudRecoveryView } = recoveryHelpers();
  assert.equal(cloudRecoveryView(attempt(), capabilities, recovery).phase, "RECONCILIATION_REQUIRED");
  assert.equal(cloudRecoveryView(attempt(), capabilities, { ...recovery, phase: "CANCELLATION_REQUESTED" }).phase, "CANCELLATION_REQUESTED");
  assert.equal(cloudRecoveryView(attempt({ checkpoint: { cancellation_requested: true } }), capabilities, { ...recovery, phase: "CANCELLATION_REQUESTED", old_owner_fenced: false }).phase, "CANCELLATION_REQUESTED");
  assert.equal(cloudRecoveryView(attempt({ checkpoint: { cancellation_requested: true } }), capabilities, { ...recovery, phase: "STOP_UNCONFIRMED" }).phase, "STOP_UNCONFIRMED");
  assert.equal(cloudRecoveryView(attempt({ status: "CANCELLED", checkpoint: { cancellation_requested: true } }), capabilities, recovery).phase, "TERMINATED");
  for (const status of ["WAITING_INPUT", "RECOVERY_REQUIRED"]) {
    const view = cloudRecoveryView(attempt({ status, checkpoint: { runtime_context: { session_id: "original", workspace: "original" } } }), capabilities, recovery);
    assert.equal(view.resumeSupported, false, "a checkpoint cannot imply supported SDK resume");
  }
});

function componentHarness(changes = {}) {
  const slots = []; let cursor = 0;
  const writes = [];
  const ui = Object.fromEntries(["Alert", "Button", "Checkbox", "Input", "Select", "Space", "Tag"].map((name) => [name, name]));
  ui.Form = { Item: "Form.Item" };
  ui.Input = { TextArea: "Input.TextArea" };
  ui.Typography = { Paragraph: "Paragraph", Text: "Text" };
  const jsx = (type, props) => ({ type, props });
  const shared = load("app/projects/[projectId]/cloud/cloud-shared.tsx", { require: (name) => {
    if (name === "react") return { useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = initial; return [slots[index], (value) => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }]; } };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "next/link") return "Link";
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en }) };
    if (name === "@/lib/cloud-recovery") return recoveryHelpers();
    return require(name);
  } });
  const props = { attempt: attempt(), capabilities, recovery, blocked: false, onSubmit: async (fields) => { writes.push(fields); }, ...changes };
  const nodes = (value) => !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children), ...nodes(value.props?.description)];
  const render = () => { cursor = 0; return nodes(shared.CloudAttemptRecovery(props)); };
  const submit = () => render().find((node) => node.type === ui.Form)?.props.onFinish();
  function fill() {
    for (let index = 0; index < 3; index++) render().filter((node) => node.type === "Checkbox")[index].props.onChange({ target: { checked: true } });
    render().find((node) => node.type === "Input.TextArea").props.onChange({ target: { value: "Host observation at fixture-time; target fixture, original key operation:1" } });
    render().find((node) => node.type === ui.Input).props.onChange({ target: { value: "Confirmed fixture closure" } });
  }
  return { render, writes, props, submit, fill };
}

test("The closure form requires all declarations, observations and reason before its single typed mutation", async () => {
  const harness = componentHarness();
  assert.equal(harness.render().find((node) => node.type === "Button").props.disabled, true);
  harness.submit(); assert.equal(harness.writes.length, 0);
  harness.fill();
  assert.equal(harness.render().find((node) => node.type === "Button").props.disabled, false);
  harness.render().find((node) => node.type === "Select").props.onChange("CANCELLED");
  harness.submit();
  assert.equal(harness.writes.length, 1);
  const request = harness.writes[0];
  assert.equal(request.operation, "RECONCILE_ATTEMPT");
  assert.equal(request.attempt_id, "attempt-1");
  assert.equal(request.status, "CANCELLED");
  assert.equal(request.reconciliation.reconciliation_source, "OPERATOR_ATTESTATION");
  assert.equal(request.reconciliation.independent_stop_proof, false);
  assert.equal(request.reconciliation.model_budget_disposition, "KEEP_HELD");
  assert.equal(request.reconciliation.model_drain_observed, false);
  assert.deepEqual([...request.reconciliation.pending_operation_keys], []);
});

test("Blocked authorization, original pending keys and changed server preconditions refuse a forced form submit", () => {
  for (const changes of [{ blocked: true }, { recovery: undefined }, { recovery: { ...recovery, pending_operation_keys: ["ssh:original"] } },
    { recovery: { ...recovery, old_owner_fenced: false } }, { recovery: { ...recovery, can_reconcile: false } }]) {
    const harness = componentHarness(changes);
    harness.fill(); harness.submit();
    assert.equal(harness.writes.length, 0);
    assert.equal(harness.render().find((node) => node.type === "Button").props.disabled, true);
  }
});

test("Waiting checkpoints never offer SDK resume or manual terminal closure before cancellation", () => {
  const harness = componentHarness({ attempt: attempt({ status: "WAITING_INPUT", checkpoint: { runtime_context: { session_id: "original" } } }) });
  const nodes = harness.render();
  assert.equal(nodes.some((node) => node.type === "Button"), false);
  assert.equal(nodes.some((node) => node.type === "Tag" && node.props.children === "Original session resume unavailable"), true);
  assert.equal(harness.writes.length, 0);
});

test("A manually closed attempt keeps its declaration and HELD limitation visible with no further mutation", () => {
  const harness = componentHarness({ attempt: attempt({ status: "FAILED", checkpoint: { reconciliation: { reconciliation_source: "OPERATOR_ATTESTATION" } } }) });
  const nodes = harness.render();
  assert.equal(nodes.some((node) => node.type === "Tag" && node.props.children === "Terminated"), true);
  assert.equal(nodes.some((node) => node.type === "Paragraph" && node.props.children.includes("uncertain budget stays HELD")), true);
  assert.equal(nodes.some((node) => node.type === "Button"), false);
  assert.equal(harness.writes.length, 0);
});

test("A 409 is a version conflict only with an explicit code or known stale-version detail", async () => {
  const cloud = load("lib/cloud.ts", { fetch: async () => new Response(JSON.stringify({ detail: "safe precondition", code: "REQUEST_PRECONDITION_REQUIRED" }), { status: 409 }) });
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Unknown conflict")), "REQUEST_PRECONDITION_REQUIRED");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Cloud Task version is stale")), "VERSION_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "VERSION_CONFLICT")), "VERSION_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "SDK_RESUME_UNSUPPORTED")), "SDK_RESUME_UNSUPPORTED");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "OPERATION_KEY_CONFLICT")), "OPERATION_KEY_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Cloud operation key conflicts with its original actor or request")), "OPERATION_KEY_CONFLICT");
  assert.equal(cloud.canReleaseCloudPending(409, false, "OPERATION_KEY_CONFLICT"), false);
  await assert.rejects(cloud.cloudRequest("operations"), (error) => error.status === 409 && error.code === "REQUEST_PRECONDITION_REQUIRED");
});
