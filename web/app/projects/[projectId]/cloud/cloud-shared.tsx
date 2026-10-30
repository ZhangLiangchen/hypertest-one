"use client";

import { Alert, Button, Checkbox, Form, Input, Select, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { useCloudOperation } from "@/lib/cloud-operation";
import type { CloudAttempt, CloudCapabilities, CloudRecord, CloudRecoverySummary } from "@/lib/cloud";
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
      <Form layout="vertical" onFinish={() => void reconcile()}>
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

export function CloudCapabilitiesNotice({ configured, capabilities, compact = false }: { configured: boolean; capabilities?: CloudCapabilities; compact?: boolean }) {
  const { t } = useI18n();
  if (!configured) return <Alert showIcon type="info" message={t("Cloud Web setup required", "需要配置云端 Web 访问")}
    description={t("The deployment operator must enable the Cloud Web boundary and configure its server-side authorization. Existing Local tasks remain available.", "部署操作者需启用云端 Web 入口并配置服务端授权。现有 Local 任务仍可使用。")} />;
  if (!capabilities) return <Alert showIcon type="warning" message={t("Cloud capabilities have not been read", "尚未读取云端能力")} description={t("Refresh and check server authorization if this persists. Your inputs remain available; no execution is submitted by a capability read.", "请刷新；若持续失败，请核对服务端授权。保留当前输入，能力读取不会下发执行。")} />;
  if (!capabilities?.enabled) return <Alert showIcon type="info" message={t("Cloud dispatch is disabled", "云端下发尚未启用")}
    description={t("Previously saved records remain readable. Resource changes and new execution require the deployment operator to enable Cloud.", "已保存记录仍可读取；修改资源和新增执行需要部署操作者启用 Cloud。")} />;
  const details = <><Typography.Paragraph style={{ marginBottom: 8 }}>{t("DeepSeek Harness uses the official Python SDK to work with HTTPS repositories and workspace-local project tests. Claude Code is reserved for future configuration; general remote shell and CI are unavailable.", "DeepSeek Harness 通过官方 Python SDK 处理 HTTPS 仓库及工作区内项目测试。Claude Code 保留占位；通用远端 Shell 和 CI 尚不可用。")}</Typography.Paragraph>
      <Tag>{t("Project framework", "项目原有框架")}</Tag><Tag>{t("Workspace-local", "工作区内执行")}</Tag>
      {capabilities.supported?.codex_delegation ? <Tag>{capabilities.configuration?.codex_enabled ? t("Codex delegation enabled", "Codex 委派已启用") : t("Codex delegation implemented · disabled", "Codex 委派已实现 · 未启用")}</Tag> : null}
      <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{capabilities.recovery?.resume_supported === true
        ? t("Runtime resume capability is reported; the original session, workspace and unresolved operations still require explicit verification.", "运行端声明具有续接能力；原会话、工作区和未决操作仍须显式核验。")
        : t("Original SDK session resume is unavailable. Cancellation, original-key reconciliation and authorized manual closure remain separate controls; closing an attempt does not release HELD budget.", "当前不支持原 SDK 会话续接。请求取消、原 key 对账和有权人工收尾是独立操作；人工收尾不释放 HELD 预算。")}</Typography.Paragraph>
      {capabilities.supported?.ssh_fixed_diagnostics ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("A separate fixed SSH diagnostics profile is implemented. It requires an exact approved configuration and does not authorize staging SSH or 166dev cloud execution.", "独立的固定 SSH 诊断配置已实现，需要确切的受权配置；不授权 staging SSH 或 166dev 云端执行。")}</Typography.Paragraph> : null}
      <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("These are configured capabilities. Provider authentication and real execution are verified separately for each task.", "这里显示配置能力；模型身份与真实执行按每个任务分别核验。 ")}</Typography.Paragraph>
      {!compact && !capabilities.worker_enabled ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("The Cloud worker is disabled. You can prepare inputs; dispatch stays disabled until a worker is enabled.", "Cloud Worker 尚未启用。可以准备输入，启用 Worker 后才能下发。")}</Typography.Paragraph> : null}</>;
  return <Alert showIcon type="info" className={compact ? "cloud-capabilities-compact" : undefined} message={t("Current execution boundary", "当前执行能力")}
    description={compact ? <>
      {!capabilities.worker_enabled ? <p className="cloud-worker-notice">{t("The Cloud worker is disabled. You can prepare inputs; dispatch stays disabled until a worker is enabled.", "Cloud Worker 尚未启用。可以准备输入，启用 Worker 后才能下发。")}</p> : null}
      <details className="cloud-capabilities-details"><summary>{t("View execution capabilities", "查看执行能力说明")}</summary><div>{details}</div></details>
    </> : details} />;
}
