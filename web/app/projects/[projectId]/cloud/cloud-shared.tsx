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
      ? t("The accepted version changed. Your form is preserved. Refresh the current state, review it, then explicitly submit a new intention.", "接受版本已变化，当前表单保留。请刷新并核对最新状态后，明确提交新的意图。")
      : operation.issue === "PRIVATE_JOURNAL_UNAVAILABLE"
        ? t("Private submission metadata could not be saved. Enable this browser's session storage before writing; no automatic retry will run.", "无法保存私有提交元数据。请先允许浏览器会话存储；系统不会自动重试写入。")
        : operation.issue ? t("Check the form and current authorization. Loaded records and non-secret fields remain available.", "请检查表单及当前授权。已加载记录与非秘密字段保留。")
          : <Space direction="vertical"><span>{t("The exact accepted version or resource metadata has been read back. This does not imply test PASS.", "已读回确切接受版本或资源元数据；这不表示测试通过。")}</span>{operation.receipt?.task_id ? <Link href={`/cloud-tasks/${operation.receipt.task_id}?projectId=${operation.receipt.project_id}`}>{t("Open the accepted task", "打开已接受的任务")}</Link> : null}</Space>}
    action={operation.pending ? <Button loading={operation.busy} onClick={() => void operation.reconcile()}>{t("Query original key", "查询原 key")}</Button> : undefined} />;
}

export function CloudCapabilitiesNotice({ configured, capabilities }: { configured: boolean; capabilities?: CloudCapabilities }) {
  const { t } = useI18n();
  if (!configured) return <Alert showIcon type="info" message={t("Cloud Web setup required", "需要配置云端 Web 访问")}
    description={t("The deployment operator must enable the Cloud Web boundary and configure its server-side authorization. Existing Local tasks remain available.", "部署操作者需启用云端 Web 入口并配置服务端授权。现有 Local 任务仍可使用。")} />;
  if (!capabilities?.enabled) return <Alert showIcon type="info" message={t("Cloud dispatch is disabled", "云端下发尚未启用")}
    description={t("Previously saved records remain readable. Resource changes and new execution require the deployment operator to enable Cloud.", "已保存记录仍可读取；修改资源和新增执行需要部署操作者启用 Cloud。")} />;
  return <Alert showIcon type="info" message={t("Current execution boundary", "当前执行能力")}
    description={<><Typography.Paragraph style={{ marginBottom: 8 }}>{t("DeepSeek can work with prepared repositories and workspace-local test fixtures. SSH, remote CI and external Codex / Claude Code delegation are not available in this runtime.", "DeepSeek 可处理已准备仓库和工作区内测试。当前运行配置尚不支持 SSH、远端 CI 或外部 Codex / Claude Code 委派。")}</Typography.Paragraph>
      <Tag>{t("Project framework", "项目原有框架")}</Tag><Tag>{t("Workspace-local", "工作区内执行")}</Tag>
      <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("These are configured capabilities. Provider authentication and real execution are verified separately for each task.", "这里显示配置能力；模型身份与真实执行按每个任务分别核验。 ")}</Typography.Paragraph>
      {!capabilities.worker_enabled ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}>{t("The Cloud worker is disabled. You can prepare inputs; dispatch stays disabled until a worker is enabled.", "Cloud Worker 尚未启用。可以准备输入，启用 Worker 后才能下发。")}</Typography.Paragraph> : null}</>} />;
}
