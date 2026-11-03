const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

function deletionView(changes = {}) {
  const writes = [];
  const props = {
    projectId: "project-1", detail: { task: { id: "task-1", version: 22 } },
    operational: { valid: true, status: "RECOVERY_REQUIRED", resolutions: [],
      attempt: { id: "attempt-2", status: "RECOVERY_REQUIRED", checkpoint: { cancellation_requested: true } } },
    recovery: { old_owner_fenced: true, pending_operation_keys: ["original-unknown-key"], can_reconcile: false },
    management: { can_delete: true, delete_blocking_reasons: [], native_scope_unobserved: false },
    operation: { blocked: false, submit: async (fields) => { writes.push(fields); } }, ...changes,
  };
  props.operation = { ...props.operation, submit: async (fields) => { writes.push(fields); } };
  const jsx = (type, props) => ({ type, props });
  const { CloudTaskDelete } = load("app/cloud-tasks/[taskId]/delete-task.tsx", { require: (name) => {
    if (name === "react") return { useEffect() {} };
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
    if (name === "antd") return { Button: "Button", Popconfirm: "Popconfirm" };
    if (name === "next/navigation") return { useRouter: () => ({ push() {} }) };
    if (name === "@tanstack/react-query") return { useQueryClient: () => ({ invalidateQueries() {} }) };
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en }) };
    if (name === "@/lib/cloud") return load("lib/cloud.ts", { URL, TextEncoder });
    return require(name);
  } });
  const tree = CloudTaskDelete(props);
  return { tree, writes, props, disabled: tree.props.children.props.disabled, confirm: tree.props.onConfirm };
}

test("A cancelled fenced recovery task can be removed without asserting that UNKNOWN actions ended", async () => {
  const view = deletionView();
  assert.equal(view.disabled, false);
  assert.match(view.tree.props.description, /remain in recovery/);
  assert.match(view.tree.props.description, /does not confirm/);
  view.confirm();
  assert.deepEqual(JSON.parse(JSON.stringify(view.writes)), [{ operation: "DELETE_TASK", task_id: "task-1", expected_version: 22 }]);
  assert.deepEqual(view.props.recovery.pending_operation_keys, ["original-unknown-key"]);
});

test("Removal fails closed without current server admission even on a forced confirm", () => {
  const original = deletionView().props;
  for (const changes of [
    { management: undefined }, { management: { can_delete: false, delete_blocking_reasons: ["PENDING_ORIGINAL_OPERATIONS"] } },
    { management: { can_delete: "true", delete_blocking_reasons: [] } },
    { operational: { ...original.operational, valid: false } },
    { detail: { task: { ...original.detail.task, deleted_at: "2026-11-03T00:00:00Z" } } },
    { operation: { ...original.operation, blocked: true } },
  ]) {
    const view = deletionView(changes);
    assert.equal(view.disabled, true);
    view.confirm();
    assert.equal(view.writes.length, 0);
  }
});

test("Fenced input recovery follows server deletion admission without claiming the resolution finished", () => {
  const operational = { valid: true, status: "DRAFT", attempt: null,
    resolutions: [{ id: "resolution-1", status: "RECOVERY_REQUIRED" }] };
  const before = JSON.stringify(operational);
  const view = deletionView({ operational, recovery: undefined });
  assert.equal(view.disabled, false);
  assert.match(view.tree.props.description, /does not confirm/);
  view.confirm();
  assert.deepEqual(JSON.parse(JSON.stringify(view.writes)), [{ operation: "DELETE_TASK", task_id: "task-1", expected_version: 22 }]);
  assert.equal(JSON.stringify(operational), before);

  for (const status of ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"]) {
    const blocked = deletionView({ operational: { ...operational, resolutions: [{ status }] },
      management: { can_delete: false, delete_blocking_reasons: ["UNRESOLVED_INPUT_RESOLUTION"] } });
    assert.equal(blocked.disabled, true);
    blocked.confirm();
    assert.equal(blocked.writes.length, 0);
  }
});

test("Deletion admission cannot be reused across task identities or accepted versions", () => {
  const { cloudOperationalView } = load("lib/cloud.ts", { URL, TextEncoder });
  const detail = { task: { id: "task-1", project_id: "project-1", version: 22,
    latest_attempt_id: null, status: "DRAFT" }, attempts: [], resolutions: [] };
  const live = { ...detail.task, current_attempt: null, resolutions: [], observed_at: "2026-11-03T00:00:00Z" };
  assert.equal(deletionView({ detail, operational: cloudOperationalView(detail, live) }).disabled, false);
  for (const changes of [{ id: "other-task" }, { project_id: "other-project" }, { version: 21 }, { version: 23 }]) {
    const blocked = deletionView({ detail, operational: cloudOperationalView(detail, { ...live, ...changes }) });
    assert.equal(blocked.disabled, true);
    blocked.confirm();
    assert.equal(blocked.writes.length, 0);
  }
});

test("Native completion can be removed only when the server admits it without claiming external closure", () => {
  const original = deletionView().props;
  const operational = { ...original.operational, status: "COMPLETED", attempt: { ...original.operational.attempt,
    status: "COMPLETED", checkpoint: { external_operations_reconciled: false } } };
  const management = { can_delete: true, delete_blocking_reasons: [], native_scope_unobserved: true };
  const view = deletionView({ operational, management });
  assert.equal(view.disabled, false);
  assert.match(view.tree.props.description, /does not confirm/);
  view.confirm();
  assert.equal(view.writes.length, 1);
  assert.equal(operational.attempt.checkpoint.external_operations_reconciled, false);

  const blocked = deletionView({ operational, management: { ...management, can_delete: false, delete_blocking_reasons: ["CLOUD_ACTION_BUSINESS_UNRECONCILED"] } });
  assert.equal(blocked.disabled, true);
  assert.match(blocked.tree.props.children.props.title, /original controlled action/);
  blocked.confirm();
  assert.equal(blocked.writes.length, 0);
});
