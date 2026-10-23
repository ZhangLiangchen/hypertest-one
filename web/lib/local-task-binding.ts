import type { LocalTaskCreate, SessionTask, SessionTaskDetail } from "@/lib/types";

export type LocalTaskCreateValues = { title: string; objective?: string; plan_markdown?: string; intended_actor_ref?: string | null };

export function localTaskCreatePayload(values: LocalTaskCreateValues, idempotencyKey: string): LocalTaskCreate {
  return { idempotency_key: idempotencyKey, title: values.title.trim(), objective: values.objective || "",
    plan_markdown: values.plan_markdown || "", intended_actor_ref: values.intended_actor_ref || null };
}

export function validateLocalTaskCreation(detail: SessionTaskDetail, projectId: string, key: string): SessionTaskDetail {
  const receipt = detail?.creation_receipt;
  if (!receipt || receipt.status !== "ACCEPTED" || receipt.operation !== "CREATE" || receipt.idempotency_key !== key
    || receipt.project_id !== projectId || detail.task?.project_id !== projectId || typeof receipt.task_id !== "string" || !receipt.task_id || receipt.task_id !== detail.task?.id
    || receipt.version !== detail.task?.version || !Number.isInteger(receipt.version) || receipt.version < 1) {
    throw new Error("LOCAL_TASK_CREATION_RECEIPT_MISMATCH");
  }
  return detail;
}

export function pendingLocalTaskCreation(raw: string, projectId: string): LocalTaskCreate {
  const stored = JSON.parse(raw) as { project_id?: unknown; payload?: LocalTaskCreate };
  const payload = stored.payload;
  if (stored.project_id !== projectId || !payload || typeof payload.idempotency_key !== "string"
    || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(payload.idempotency_key)
    || typeof payload.title !== "string" || !payload.title.trim() || payload.title.length > 512
    || (payload.objective !== undefined && (typeof payload.objective !== "string" || payload.objective.length > 16000))
    || (payload.plan_markdown !== undefined && (typeof payload.plan_markdown !== "string" || payload.plan_markdown.length > 262144))
    || (payload.intended_actor_ref != null && typeof payload.intended_actor_ref !== "string")) {
    throw new Error("LOCAL_TASK_PENDING_REQUEST_INVALID");
  }
  return { idempotency_key: payload.idempotency_key, title: payload.title,
    ...(Object.prototype.hasOwnProperty.call(payload, "objective") ? { objective: payload.objective } : {}),
    ...(Object.prototype.hasOwnProperty.call(payload, "plan_markdown") ? { plan_markdown: payload.plan_markdown } : {}),
    ...(Object.prototype.hasOwnProperty.call(payload, "intended_actor_ref") ? { intended_actor_ref: payload.intended_actor_ref } : {}) };
}

export function localTaskCreateWasRejected(error: unknown): boolean {
  if ((error as { detail?: unknown } | null)?.detail === "TASK_OPERATION_KEY_CONFLICT") return false;
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status === "number" && [400, 401, 403, 404, 409, 422].includes(status);
}

/** This flow supports native Codex callers; the client validates every MCP call. */
export function taskBindingTemplate(task: Pick<SessionTask, "id" | "project_id" | "version">): string {
  return JSON.stringify({ project_id: task.project_id, task_id: task.id,
    provider: "codex", session_id: "<REAL_PARENT_SESSION_ID_FROM_NATIVE_SESSION_START>",
    expected_version: task.version, idempotency_key: "<FREEZE_ONE_KEY_FOR_THIS_BIND_REQUEST>" }, null, 2);
}
