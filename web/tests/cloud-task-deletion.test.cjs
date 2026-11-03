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

test("Recovery removal requires current matching state, cancellation and writer fencing even on a forced confirm", () => {
  const original = deletionView().props;
  for (const changes of [
    { recovery: undefined }, { recovery: { old_owner_fenced: false } },
    { operational: { ...original.operational, valid: false } },
    { operational: { ...original.operational, status: "RUNNING" } },
    { operational: { ...original.operational, attempt: { ...original.operational.attempt, checkpoint: {} } } },
    { operational: { ...original.operational, resolutions: [{ status: "RESOLVING" }] } },
    { detail: { task: { ...original.detail.task, deleted_at: "2026-11-03T00:00:00Z" } } },
    { operation: { ...original.operation, blocked: true } },
  ]) {
    const view = deletionView(changes);
    assert.equal(view.disabled, true);
    view.confirm();
    assert.equal(view.writes.length, 0);
  }
});
