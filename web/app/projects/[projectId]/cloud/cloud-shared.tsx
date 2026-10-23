"use client";

import { Alert, Button, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";
import type { useCloudOperation } from "@/lib/cloud-operation";
import type { CloudCapabilities } from "@/lib/cloud";

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
        ? t("Private submission metadata could not be saved. Enable this browser's session storage before writing; no automatic retry will run.", "无法保存私有提交元数据。请先允许浏览器会话存储；系统不会自动重试写入。")
        : operation.issue ? <Space direction="vertical"><span>{t("Check the form and current authorization. Loaded records and non-secret fields remain available.", "请检查表单及当前授权。已加载记录与非秘密字段保留。")}</span>{operation.rejection ? <span>{operation.rejection}</span> : null}{operation.rejectedOperation ? <Typography.Text code>{operation.rejectedOperation.operation_key}</Typography.Text> : null}</Space>
          : <Space direction="vertical"><span>{t("The exact accepted version or resource metadata has been read back. This does not imply test PASS.", "已读回确切接受版本或资源元数据；这不表示测试通过。")}</span>{operation.receipt?.task_id ? <Link href={`/cloud-tasks/${operation.receipt.task_id}?projectId=${operation.receipt.project_id}`}>{t("Open the accepted task", "打开已接受的任务")}</Link> : null}</Space>}
    action={operation.pending ? <Button loading={operation.busy} onClick={() => void operation.reconcile()}>{t("Query original key", "查询原 key")}</Button> : undefined} />;
}

export function CloudCapabilitiesNotice({ configured, capabilities }: { configured: boolean; capabilities?: CloudCapabilities }) {
  const { t } = useI18n();
  if (!configured) return <Alert showIcon type="info" message={t("Cloud Web setup required", "需要配置云端 Web 访问")}
    description={t("The deployment operator must enable the Cloud Web boundary and configure its server-side authorization. Existing Local tasks remain available.", "部署操作者需启用云端 Web 入口并配置服务端授权。现有 Local 任务仍可使用。")} />;
  if (!capabilities) return <Alert showIcon type="warning" message={t("Cloud capabilities have not been read", "尚未读取云端能力")} description={t("Refresh and check server authorization if this persists. Your inputs remain available; no execution is submitted by a capability read.", "请刷新；若持续失败，请核对服务端授权。保留当前输入，能力读取不会下发执行。")} />;
  if (!capabilities?.enabled) return <Alert showIcon type="info" message={t("Cloud dispatch is disabled", "云端下发尚未启用")}
    description={t("Previously saved records remain readable. Resource changes and new execution require the deployment operator to enable Cloud.", "已保存记录仍可读取；修改资源和新增执行需要部署操作者启用 Cloud。")} />;
  return <Alert showIcon type="info" message={t("Current execution boundary", "当前执行能力")}
    description={<><Typography.Paragraph style={{ marginBottom: 8 }}>{t("DeepSeek Harness uses the official Python SDK to work with HTTPS repositories and workspace-local project tests. Claude Code is reserved for future configuration; general remote shell and CI are unavailable.", "DeepSeek Harness 通过官方 Python SDK 处理 HTTPS 仓库及工作区内项目测试。Claude Code 保留占位；通用远端 Shell 和 CI 尚不可用。")}</Typography.Paragraph>
      <Tag>{t("Project framework", "项目原有框架")}</Tag><Tag>{t("Workspace-local", "工作区内执行")}</Tag>
      {capabilities.supported?.codex_delegation ? <Tag>{capabilities.configuration?.codex_enabled ? t("Codex delegation enabled", "Codex 委派已启用") : t("Codex delegation implemented · disabled", "Codex 委派已实现 · 未启用")}</Tag> : null}
      {capabilities.supported?.ssh_fixed_diagnostics ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("A separate fixed SSH diagnostics profile is implemented. It requires an exact approved configuration and does not authorize staging SSH or 166dev cloud execution.", "独立的固定 SSH 诊断配置已实现，需要确切的受权配置；不授权 staging SSH 或 166dev 云端执行。")}</Typography.Paragraph> : null}
      <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("These are configured capabilities. Provider authentication and real execution are verified separately for each task.", "这里显示配置能力；模型身份与真实执行按每个任务分别核验。 ")}</Typography.Paragraph>
      {!capabilities.worker_enabled ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("The Cloud worker is disabled. You can prepare inputs; dispatch stays disabled until a worker is enabled.", "Cloud Worker 尚未启用。可以准备输入，启用 Worker 后才能下发。")}</Typography.Paragraph> : null}</>} />;
}
