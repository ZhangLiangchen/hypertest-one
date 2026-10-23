import type { CloudAttempt, CloudCapabilities, CloudRecoverySummary } from "./cloud";

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
  return {
    terminal, phase, pendingKeys, cancellationRequested,
    resumeSupported: capabilities?.supported?.resume_attempt === true && capabilities.recovery?.resume_supported === true && recovery?.resume_supported === true,
    canReconcile: attempt.status === "RECOVERY_REQUIRED" && capabilities?.supported?.reconcile_attempt === true
      && capabilities.recovery?.reconcile_supported === true && recovery?.can_reconcile === true
      && recovery.old_owner_fenced === true && recovery.remote_operations_reconciled === true && pendingKeys.length === 0,
    blockingReasons: recovery?.blocking_reasons || [],
  };
}
