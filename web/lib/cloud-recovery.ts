import type { CloudAttempt, CloudCapabilities, CloudRecoverySummary } from "./cloud";

export function cloudRecoveryReason(reason: string, t: (en: string, zh: string) => string) {
  const labels: Record<string, [string, string]> = {
    RECOVERY_REQUIRED_ONLY: ["This attempt is not awaiting recovery.", "当前尝试未处于待恢复状态。"],
    OLD_OWNER_NOT_FENCED: ["The previous Worker still has writing authority.", "原 Worker 的写入权尚未隔离。"],
    PENDING_ORIGINAL_OPERATIONS: ["Reconcile pending requests by their original keys.", "请先按原 key 核对未决请求。"],
    DELEGATIONS_UNRECONCILED: ["A delegated Agent still needs a confirmed ending.", "尚有子 Agent 缺少结束确认。"],
    CLOUD_CONTAINER_UNRECONCILED: ["The earlier execution environment still needs closure confirmation.", "此前执行环境尚需确认收尾。"],
    SSH_REMOTE_OPERATIONS_UNRECONCILED: ["An earlier remote operation needs reconciliation.", "此前远端操作尚需对账。"],
    HTTPS_REMOTE_OPERATIONS_UNRECONCILED: ["An earlier HTTP operation needs reconciliation.", "此前 HTTP 操作尚需对账。"],
    CLOUD_ACTION_BUSINESS_UNRECONCILED: ["An earlier controlled action needs reconciliation.", "此前受控动作尚需对账。"],
    CANCELLATION_REQUESTED: ["Cancellation was requested; this attempt cannot continue.", "本次尝试已请求取消，不能继续。"],
    TASK_DELETED: ["The task was removed and cannot continue.", "任务已移除，不能继续。"],
    NATIVE_RESUME_LEGACY_BUDGET_UNSUPPORTED: ["This attempt's earlier budget format does not support continuation.", "本次尝试使用的旧预算格式不支持续跑。"],
    MESSAGE_DELIVERY_UNKNOWN: ["Confirm the original message's delivery before continuing.", "继续前请先核对原消息的投递结果。"],
    NATIVE_SESSION_INSPECTION_OUTSTANDING: ["An earlier session check is still pending.", "此前会话检查仍待确认。"],
    AUTHORIZATION_UNAVAILABLE: ["This attempt's authorization is no longer available.", "本次尝试的授权已不可用。"],
  };
  return t(...(labels[reason] || ["Review the current recovery conditions and refresh.", "请核对当前恢复条件后刷新。"]));
}

/** The summary supplies server-checked preconditions; declarations cannot replace them. */
export function cloudRecoveryView(attempt: CloudAttempt, capabilities?: CloudCapabilities, recovery?: CloudRecoverySummary) {
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(attempt.status);
  const pending = new Set<string>(recovery?.pending_operation_keys || []);
  if (Array.isArray(attempt.checkpoint.pending_operation_keys)) {
    for (const key of attempt.checkpoint.pending_operation_keys) if (typeof key === "string") pending.add(key);
  }
  const pendingKeys = [...pending];
  const cancellationRequested = attempt.checkpoint.cancellation_requested === true;
  const phase = terminal ? "TERMINATED" : recovery?.phase || (cancellationRequested ? "CANCELLATION_REQUESTED"
    : attempt.status === "RECOVERY_REQUIRED" ? "RECONCILIATION_REQUIRED" : "ACTIVE");
  const resumeSupported = capabilities?.supported?.resume_attempt === true && capabilities.recovery?.resume_supported === true && recovery?.resume_supported === true;
  const resumeIdentitySource = recovery?.identity_anchor === "RECORDED" ? "PRE_PROMPT_ANCHORED" as const
    : recovery?.identity_anchor === "MISSING" ? "OPERATOR_ADOPTED" as const : undefined;
  return {
    terminal, phase, pendingKeys, cancellationRequested,
    resumeSupported, resumeIdentitySource,
    canResume: resumeSupported && recovery?.can_resume === true && !!resumeIdentitySource
      && attempt.status === "RECOVERY_REQUIRED" && !cancellationRequested && pendingKeys.length === 0
      && recovery.old_owner_fenced === true && recovery.remote_operations_reconciled === true,
    resumeBlockingReasons: recovery?.resume_blocking_reasons || recovery?.blocking_reasons || [],
    canReconcile: attempt.status === "RECOVERY_REQUIRED" && capabilities?.supported?.reconcile_attempt === true
      && capabilities.recovery?.reconcile_supported === true && recovery?.can_reconcile === true
      && recovery.old_owner_fenced === true && recovery.remote_operations_reconciled === true && pendingKeys.length === 0,
    blockingReasons: recovery?.blocking_reasons || [],
  };
}
