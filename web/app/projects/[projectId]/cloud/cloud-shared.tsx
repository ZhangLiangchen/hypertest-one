"use client";

import { Alert, Button, Checkbox, Form, Input, Select, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { useCloudOperation } from "@/lib/cloud-operation";
import type { CloudAgentAuthEntry, CloudAttempt, CloudAuthStatus, CloudCapabilities, CloudRecord, CloudRecoverySummary } from "@/lib/cloud";
import { cloudRecoveryView } from "@/lib/cloud-recovery";

export function CloudOperationNotice({ operation }: { operation: ReturnType<typeof useCloudOperation> }) {
  const { t } = useI18n();
  if (!operation.issue && !operation.pending && !operation.receipt) return null;
  return <Alert showIcon style={{ marginBottom: 20 }} type={operation.pending ? "warning" : operation.issue ? "error" : "info"}
    message={operation.pending ? t("Submission needs reconciliation", "提交结果需要对账") : operation.issue ? t("Cloud submission was not completed", "云端提交未完成") : t("Accepted and read back", "已接受并完整读回")}
    description={operation.pending ? <Space direction="vertical">
      <span>{t("This request may already have been accepted. Only query its original key; a missing receipt does not permit another submission.", "原请求可能已经接受。请只查询原操作 key；暂未找到回执也不能重新提交。")}</span>
      <Typography.Text code>{operation.pending.operation_key}</Typography.Text>
    </Space> : operation.issue === "VERSION_CONFLICT"
      ? <Space direction="vertical"><span>{t("The accepted version changed. Your form is preserved. Refresh the current state, review it, then explicitly submit a new intention.", "接受版本已变化，当前表单保留。请刷新并核对最新状态后，明确提交新的意图。")}</span>{operation.rejectedOperation ? <Typography.Text code>{operation.rejectedOperation.operation_key}</Typography.Text> : null}</Space>
      : operation.issue === "PRIVATE_JOURNAL_UNAVAILABLE"
        ? t("Private submission metadata could not be saved. Allow this browser's persistent storage before writing. No POST or automatic retry will run.", "无法保存私有提交元数据。请先允许浏览器持久存储；不会发送 POST 或自动重试写入。")
        : operation.issue === "SDK_RESUME_UNSUPPORTED"
          ? t("This runtime cannot resume the original SDK session. The original attempt and checkpoint are preserved. Reconcile uncertain actions before authorized manual closure.", "当前运行端不支持原 SDK 会话续接；保留原尝试与 checkpoint。请先核对未决动作，再进行有权人工收尾。")
          : operation.issue === "REQUEST_PRECONDITION_REQUIRED"
            ? t("The current state or operation preconditions changed. Refresh the live state and check the original operations before a new explicit intention. No automatic retry will run.", "当前状态或操作前置条件已变化。请刷新当前状态并核对原操作，再明确提交新意图；不会自动重试。")
        : operation.issue ? <Space direction="vertical"><span>{t("Check the form and current authorization. Loaded records and non-secret fields remain available.", "请检查表单及当前授权。已加载记录与非秘密字段保留。")}</span>{operation.rejection ? <span>{operation.rejection}</span> : null}{operation.rejectedOperation ? <Typography.Text code>{operation.rejectedOperation.operation_key}</Typography.Text> : null}</Space>
          : <Space direction="vertical"><span>{t("The exact accepted version or resource metadata has been read back. This does not imply test PASS.", "已读回确切接受版本或资源元数据；这不表示测试通过。")}</span>{operation.receipt?.task_id ? <Link href={`/cloud-tasks/${operation.receipt.task_id}?projectId=${operation.receipt.project_id}`}>{t("Open the accepted task", "打开已接受的任务")}</Link> : null}</Space>}
    action={operation.pending ? <Button loading={operation.busy} onClick={() => void operation.reconcile()}>{t("Query original key", "查询原 key")}</Button> : undefined} />;
}

/** Manual terminal reconciliation is an operator declaration, never a Worker stop observation. */
export function CloudAttemptRecovery({ attempt, capabilities, recovery, blocked, onSubmit }: {
  attempt: CloudAttempt; capabilities?: CloudCapabilities; recovery?: CloudRecoverySummary;
  blocked: boolean; onSubmit: (fields: CloudRecord) => Promise<void>;
}) {
  const { t } = useI18n();
  const [confirmed, setConfirmed] = useState({ old_owner_fenced: false, local_processes_stopped: false, external_operations_reconciled: false });
  const [observations, setObservations] = useState("");
  const [reason, setReason] = useState("");
  const [terminalStatus, setTerminalStatus] = useState<"CANCELLED" | "FAILED">(attempt.checkpoint.cancellation_requested === true ? "CANCELLED" : "FAILED");
  const view = cloudRecoveryView(attempt, capabilities, recovery);
  const canSubmit = !blocked && view.canReconcile && Object.values(confirmed).every(Boolean) && !!observations.trim() && !!reason.trim();
  async function reconcile() {
    if (!canSubmit) return;
    await onSubmit({ operation: "RECONCILE_ATTEMPT", attempt_id: attempt.id, status: terminalStatus, reason: reason.trim(), reconciliation: {
      ...confirmed, observations: observations.trim(), pending_operation_keys: [],
      reconciliation_source: "OPERATOR_ATTESTATION", independent_stop_proof: false,
      model_budget_disposition: "KEEP_HELD", model_drain_observed: false,
    } });
  }
  const phaseLabel = view.phase === "TERMINATED" ? t("Terminated", "已终止")
    : view.phase === "STOP_UNCONFIRMED" ? t("Stop awaiting confirmation", "停止待确认")
      : view.phase === "CANCELLATION_REQUESTED" ? t("Cancellation requested", "已请求取消")
        : view.phase === "RECONCILIATION_REQUIRED" ? t("Reconciliation required", "待对账")
          : attempt.status === "WAITING_INPUT" ? t("Waiting for input", "等待输入") : t("Attempt active", "尝试进行中");
  return <div style={{ marginTop: 20 }}>
    <Space wrap><Tag>{phaseLabel}</Tag><Tag>{view.resumeSupported ? t("Resume capability reported", "运行端声明可续接") : t("Original session resume unavailable", "原会话续接不可用")}</Tag></Space>
    {view.phase === "CANCELLATION_REQUESTED" ? <Typography.Paragraph className="muted">{t("The cancellation request is recorded. Refresh the live state to verify the writer fence and process status before reconciliation.", "取消请求已记录；请刷新当前状态，核验写入权隔离与进程状态后再对账。")}</Typography.Paragraph> : null}
    {view.phase === "STOP_UNCONFIRMED" ? <Typography.Paragraph className="muted">{t("Cancellation fenced the platform writer. The server has no independent observation confirming that all runtime and remote processes stopped. Reconcile the original actions before closing this attempt.", "取消已隔离平台写入权；服务端尚无独立观察确认全部运行及远端进程已停止。请核对原动作后再收尾本次尝试。")}</Typography.Paragraph> : null}
    {["WAITING_INPUT", "RECOVERY_REQUIRED"].includes(attempt.status) ? <Typography.Paragraph className="muted">{view.resumeSupported
      ? t("A resume capability alone does not verify the original session, workspace, checkpoint or remaining budget. Continue only through a separately verified runtime recovery path.", "续接能力声明不能核验原会话、工作区、checkpoint 或剩余预算，须通过另行核验的运行端恢复路径继续。")
      : t("This runtime cannot resume the original SDK session. Saving an answer or having a checkpoint does not make it resumable. No prompt or external action will be replayed. To end a waiting attempt, request cancellation first, then reconcile it.", "当前运行端不支持原 SDK 会话续接；保存回答或已有 checkpoint 不代表可恢复。不会重放 prompt 或外部动作。需要结束等待中的尝试时，请先请求取消，再进行对账。")}</Typography.Paragraph> : null}
    {attempt.status === "RECOVERY_REQUIRED" ? <details>
      <summary>{t("Reconcile and close this attempt", "对账并人工收尾本次尝试")}</summary>
      <Alert showIcon type="warning" style={{ marginTop: 16, marginBottom: 16 }} message={t("Operator declaration", "操作者声明")}
        description={t("This records your observations under cloud:control authorization. It does not stop processes or provide independent proof of stopping. Original results, artifacts, receipts and any HELD budget remain preserved; UNKNOWN actions must be reconciled by their original keys first.", "本操作在 cloud:control 授权下记录人工观察，不会停止进程，也不是独立的进程停止证明。原结果、原件、回执和 HELD 预算保留；UNKNOWN 动作必须先按原 key 对账。")}/>
      {!view.canReconcile ? <Alert showIcon type="info" style={{ marginBottom: 16 }} message={t("Server preconditions are not satisfied", "服务端前置条件尚未满足")}
        description={<Space direction="vertical"><span>{t("Refresh the live state after fencing the old owner and reconciling all original operations. This form cannot clear an unresolved key.", "请在旧 owner 失权、全部原操作完成对账后刷新当前状态；此表单不能清除未决 key。")}</span>
          {view.pendingKeys.map((key) => <Typography.Text code key={key}>{key}</Typography.Text>)}
          {view.blockingReasons.map((entry) => <Typography.Text key={entry}>{entry}</Typography.Text>)}</Space>} /> : null}
      <Form className="cloud-task-fields" layout="vertical" onFinish={() => void reconcile()}>
        <Form.Item label={t("Observed preconditions", "已观察的前置条件")} required>
          <Space direction="vertical">{(Object.keys(confirmed) as (keyof typeof confirmed)[]).map((key) => <Checkbox key={key} checked={confirmed[key]} onChange={(event) => setConfirmed((value) => ({ ...value, [key]: event.target.checked }))}>
            {({ old_owner_fenced: t("I verified that the old owner is fenced", "我已核对旧 owner 已失权"), local_processes_stopped: t("I observed that the managed processes stopped", "我已观察受管进程已停止"), external_operations_reconciled: t("I reconciled external actions by their original keys", "我已按原 key 核对外部动作") })[key]}
          </Checkbox>)}</Space>
        </Form.Item>
        <Form.Item label={t("Observed evidence, targets, times and original operation references", "观察证据、目标、时间及原操作引用")} htmlFor={`reconcile-observations-${attempt.id}`} required><Input.TextArea id={`reconcile-observations-${attempt.id}`} rows={4} maxLength={16000} value={observations} onChange={(event) => setObservations(event.target.value)} /></Form.Item>
        <Form.Item label={t("Terminal status", "收尾状态")} htmlFor={`reconcile-status-${attempt.id}`} required><Select id={`reconcile-status-${attempt.id}`} value={terminalStatus} onChange={setTerminalStatus} options={[{ value: "CANCELLED", label: t("Cancelled", "已取消") }, { value: "FAILED", label: t("Failed", "失败") }]} /></Form.Item>
        <Form.Item label={t("Closure reason", "收尾原因")} htmlFor={`reconcile-reason-${attempt.id}`} required><Input id={`reconcile-reason-${attempt.id}`} maxLength={4096} value={reason} onChange={(event) => setReason(event.target.value)} /></Form.Item>
        <Button htmlType="submit" disabled={!canSubmit}>{t("Record reconciliation and close", "记录对账并收尾")}</Button>
      </Form>
    </details> : null}
    {view.terminal && attempt.checkpoint.reconciliation ? <Typography.Paragraph className="muted">{t("This attempt was closed using an operator declaration. It remains distinct from an independent process-stop observation; uncertain budget stays HELD.", "本次尝试已按操作者声明收尾。该声明仍与独立进程停止观察区分；不确定预算继续 HELD。")}</Typography.Paragraph> : null}
  </div>;
}

export function cloudAuthObservationStatus(entry: CloudAgentAuthEntry | undefined, now: number): CloudAgentAuthEntry["status"] {
  if (!entry || (entry.status !== "VALID" && entry.status !== "INVALID")) return entry?.status === "NOT_SUPPORTED" ? "NOT_SUPPORTED" : "UNKNOWN";
  const observed = entry.checked_at ? Date.parse(entry.checked_at) : NaN;
  const age = now - observed;
  return Number.isFinite(observed) && age >= 0 && age < 180_000 ? entry.status : "UNKNOWN";
}

export function CloudCapabilitiesNotice({ configured, capabilities, authStatus }: { configured: boolean; capabilities?: CloudCapabilities; authStatus?: CloudAuthStatus; compact?: boolean }) {
  const { t, formatDate } = useI18n();
  const [authNow, setAuthNow] = useState(() => Date.now());
  useEffect(() => {
    const now = Date.now();
    setAuthNow(now);
    const expires = Object.values(authStatus?.agents || {})
      .filter((entry) => entry?.status === "VALID" || entry?.status === "INVALID")
      .map((entry) => entry.checked_at ? Date.parse(entry.checked_at) + 180_000 : NaN)
      .filter((time) => Number.isFinite(time) && time > now);
    const timers = expires.map((time) => window.setTimeout(() => setAuthNow(Date.now()), time - now));
    const update = () => setAuthNow(Date.now());
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    return () => { timers.forEach((timer) => window.clearTimeout(timer)); window.removeEventListener("focus", update); document.removeEventListener("visibilitychange", update); };
  }, [authStatus]);
  if (!configured) return <Alert showIcon type="info" message={t("Cloud Web setup required", "需要配置云端 Web 访问")}
    description={t("The deployment operator must enable the Cloud Web boundary and configure its server-side authorization. Existing Local tasks remain available.", "部署操作者需启用云端 Web 入口并配置服务端授权。现有 Local 任务仍可使用。")} />;
  if (!capabilities) return <Alert showIcon type="warning" message={t("Cloud capabilities have not been read", "尚未读取云端能力")} description={t("Refresh and check server authorization if this persists. Your inputs remain available; no execution is submitted by a capability read.", "请刷新；若持续失败，请核对服务端授权。保留当前输入，能力读取不会下发执行。")} />;
  if (!capabilities?.enabled) return <Alert showIcon type="info" message={t("Cloud dispatch is disabled", "云端下发尚未启用")}
    description={t("Previously saved records remain readable. Resource changes and new execution require the deployment operator to enable Cloud.", "已保存记录仍可读取；修改资源和新增执行需要部署操作者启用 Cloud。")} />;
  type CapabilityTone = "ready" | "partial" | "unavailable" | "unknown";
  const supported = capabilities.supported;
  const rootTone: CapabilityTone = supported?.root_agent === true ? "ready" : supported?.root_agent === false ? "unavailable" : "unknown";
  const codexTone: CapabilityTone = supported?.codex_delegation === false ? "unavailable"
    : supported?.codex_delegation !== true ? "unknown"
      : capabilities.configuration?.codex_enabled === true ? "ready" : capabilities.configuration?.codex_enabled === false ? "partial" : "unknown";
  const claudeTone: CapabilityTone = supported?.claude_code_delegation === true ? "partial" : supported?.claude_code_delegation === false ? "unavailable" : "unknown";
  const unknown = t("Unknown", "状态未知");
  function authView(entry?: CloudAgentAuthEntry) {
    switch (cloudAuthObservationStatus(entry, authNow)) {
      case "VALID": return { tone: "ready", text: t("Valid", "有效") };
      case "INVALID": return { tone: "unavailable", text: t("Invalid", "无效") };
      case "NOT_SUPPORTED": return { tone: "unknown", text: t("Not supported", "暂不支持") };
      default: return { tone: "unknown", text: t("Unconfirmed", "未确认") };
    }
  }
  const agents = [
    { name: "DeepSeek Harness", role: t("Root agent", "主 Agent"), tone: rootTone, auth: authStatus?.agents?.deepseek,
      status: rootTone === "ready" ? t("Adapted", "已适配") : rootTone === "unavailable" ? t("Not supported", "暂未支持") : unknown },
    { name: "Codex", role: t("Delegation", "委派"), tone: codexTone, auth: authStatus?.agents?.codex,
      status: codexTone === "ready" ? t("Delegation enabled", "委派已启用") : codexTone === "partial" ? t("Implemented · not enabled", "已实现 · 未启用") : codexTone === "unavailable" ? t("Not supported", "暂未支持") : unknown },
    { name: "Claude Code", role: t("Delegation", "委派"), tone: claudeTone, auth: authStatus?.agents?.claude_code,
      status: claudeTone === "partial" ? t("Implemented", "已实现") : claudeTone === "unavailable" ? t("Not supported", "暂未支持") : unknown },
  ];
  return <section className="cloud-capabilities" aria-labelledby="cloud-capabilities-heading">
    <div className="cloud-capabilities-header">
      <div><h2 id="cloud-capabilities-heading">{t("Current execution capabilities", "当前执行能力")}</h2>
        <p>{t("Agent integration", "Agent 适配")}</p></div>
      <span className={`cloud-capabilities-worker ${capabilities.worker_enabled === true ? "is-enabled" : "is-disabled"}`}>
        <span className="cloud-capabilities-dot" aria-hidden="true" />
        {capabilities.worker_enabled === true ? t("Worker enabled", "Worker 已启用") : capabilities.worker_enabled === false ? t("Worker disabled", "Worker 未启用") : t("Worker status unknown", "Worker 状态未知")}
      </span>
    </div>
    {!capabilities.worker_enabled ? <p className="cloud-worker-notice">{t("The Cloud worker is disabled or its configuration is unknown. You can prepare inputs; dispatch requires an enabled worker.", "Cloud Worker 未启用或配置状态未知。可以准备输入；下发需要启用 Worker。")}</p> : null}
    <div className="cloud-capabilities-agents" aria-label={t("Agent integration status", "Agent 适配状态")}>
      {agents.map((agent) => { const auth = authView(agent.auth); return <div className="cloud-capability-agent" key={agent.name}>
        <div className="cloud-capability-agent-name">{agent.name}<span>{agent.role}</span></div>
        <div className={`cloud-capability-status is-${agent.tone}`}><span className="cloud-capabilities-dot" aria-hidden="true" />{agent.status}</div>
        <div className="cloud-capability-auth"><span>{t("Authentication", "认证")}</span><span className={`cloud-capability-auth-state is-${auth.tone}`}><span className="cloud-capabilities-dot" aria-hidden="true" />{auth.text}</span></div>
        {agent.auth?.checked_at ? <p className="cloud-capability-checked">{t("Checked", "核验时间")}: <time dateTime={agent.auth.checked_at}>{formatDate(agent.auth.checked_at)}</time></p> : null}
      </div>; })}
    </div>
    <details className="cloud-capabilities-details">
      <summary>{t("View execution capability details", "查看执行能力说明")}</summary>
      <div>
        <p>{t("DeepSeek Harness uses the official Python SDK with HTTPS repositories and workspace-local project tests. Codex is an optional delegation path in the existing integration; the native profile currently connects only the official DeepSeek provider. General remote shell and CI are unavailable.", "DeepSeek Harness 通过官方 Python SDK 处理 HTTPS 仓库及工作区内的项目测试。Codex 是现有集成中的可选委派路径；原生模式目前仅接通 DeepSeek 官方 provider。通用远端 Shell 和 CI 尚不可用。")}</p>
        <p>{capabilities.recovery?.resume_supported === true
          ? t("A reported resume capability does not verify the original session, workspace or unresolved operations.", "运行端声明可续接，不代表原会话、工作区及未决操作已核验。")
          : t("The original SDK session cannot be resumed. Cancellation, original-key reconciliation and authorized manual closure are separate; closure does not release HELD budget.", "当前不支持原 SDK 会话续接。取消、原 key 对账与有权人工收尾相互独立；人工收尾不会释放 HELD 预算。")}</p>
        {supported?.ssh_fixed_diagnostics ? <p>{t("The separate fixed SSH diagnostics profile requires exact authorization; it does not authorize staging SSH or 166dev cloud execution.", "独立的固定 SSH 诊断配置需要确切授权；不授权 staging SSH 或 166dev 云端执行。")}</p> : null}
        <p>{t("Integration and authentication are separate. Authentication status describes the observation at the time shown and can change; it does not guarantee Worker health or a successful test. Task execution is verified separately.", "适配与认证分别显示。认证状态仅反映所示时间的观察结果，可能随时变化；不代表 Worker 健康或测试通过。任务执行仍需单独核验。")}</p>
      </div>
    </details>
  </section>;
}
