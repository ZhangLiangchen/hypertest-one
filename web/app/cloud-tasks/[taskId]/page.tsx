"use client";

import { ExportOutlined, ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Modal, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReportedResultTag } from "@/app/tasks/task-records";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { CloudCapabilitiesNotice, CloudOperationNotice } from "@/app/projects/[projectId]/cloud/cloud-shared";
import { CloudTaskForm } from "@/app/projects/[projectId]/cloud/task-form";
import { cloudCapabilities, cloudDocument, cloudOperationalView, cloudSetup, cloudSummary } from "@/lib/cloud";
import type { CloudRecord, CloudTask } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { cloudPollingVersion, cloudSummaryPollInterval, readCloudPollingDocument } from "@/lib/run-polling";
import { getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { CloudTaskRecords } from "./records";
import { ConversationPanel } from "./conversation-panel";

const text = (value: unknown) => typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value, null, 2);
const isUuid = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);

export default function CloudTaskPage() {
  const { taskId } = useParams<{ taskId: string }>(); const search = useSearchParams();
  const projectId = search.get("projectId") || "";
  const { t, label } = useI18n();
  const [editing, setEditing] = useState<CloudTask | null>(null);
  useEffect(() => { setEditing(null); }, [projectId, taskId]);
  const operation = useCloudOperation(projectId);
  const setup = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup });
  const configured = setup.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: configured });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true), enabled: configured && isUuid(projectId) });
  const live = useQuery({ queryKey: ["cloud-task-live", projectId, taskId], queryFn: () => cloudSummary(projectId, taskId), enabled: configured && isUuid(projectId) && isUuid(taskId),
    refetchInterval: (query) => cloudSummaryPollInterval(projectId, taskId, query.state.data), refetchOnWindowFocus: true });
  const observedVersion = cloudPollingVersion(projectId, taskId, live.data);
  const document = useQuery({ queryKey: ["cloud-task", projectId, taskId], queryFn: () => readCloudPollingDocument(projectId, taskId, live.data, cloudDocument),
    enabled: configured && isUuid(projectId) && isUuid(taskId) && observedVersion !== undefined, staleTime: Infinity });
  useEffect(() => {
    // Reports refresh when a newer accepted version exists; conversation has its own cursor.
    if (observedVersion !== undefined && (!document.data || observedVersion > document.data.task.version) && !document.isFetching) void document.refetch();
  }, [observedVersion, live.dataUpdatedAt, document.data?.task.version, taskId, projectId, document.refetch]);
  useEffect(() => {
    if (editing && operation.receipt?.operation === "UPDATE_TASK" && operation.receipt.task_id === editing.id && operation.receipt.version === editing.version + 1) {
      setEditing(null); void live.refetch(); void document.refetch();
    }
  }, [editing, operation.receipt, live.refetch, document.refetch]);

  async function start() {
    if (!document.data || document.data.task.deleted_at || operation.blocked || capabilities.data?.enabled !== true || capabilities.data?.worker_enabled !== true || live.isError) return;
    const current = cloudOperationalView(document.data, live.data);
    if (!current.valid || current.status !== "DRAFT" || current.resolutions.some((row) => ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"].includes(String(row.status)))) return;
    const receipt = await operation.submit({ operation: "START_TASK", task_id: taskId, expected_version: document.data.task.version });
    if (receipt) { await document.refetch(); await live.refetch(); }
  }
  function openArtifacts() {
    const target = window.document.getElementById("cloud-assets-title");
    target?.focus({ preventScroll: true }); target?.scrollIntoView({ block: "start" });
  }
  if (!isUuid(projectId)) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref="/" backLabel={t("Projects", "项目")} /><Alert showIcon type="error" message={t("Open this task from its project.", "请从所属项目打开此任务。")}/></main>;
  if (!configured) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{setup.isLoading ? <WorkspaceLoading label={t("Checking Cloud access", "正在检查云端访问")} /> : <CloudCapabilitiesNotice configured={false} />}</main>;
  if (!document.data) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{live.isLoading || document.isLoading ? <WorkspaceLoading label={t("Loading task", "正在读取任务")} /> : <Alert showIcon type="error" message={t("The task could not be loaded.", "无法读取任务。")}
    action={<Button onClick={() => { void live.refetch(); void document.refetch(); }}>{t("Retry", "重试")}</Button>} />}</main>;

  const detail = document.data, task = detail.task, operational = cloudOperationalView(detail, live.data);
  // Previously loaded conversations stay readable while the report version refreshes.
  const attempt = operational.attempt || detail.attempts.find((row) => row.id === task.latest_attempt_id);
  const status = operational.status || task.status;
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(status);
  const enabled = capabilities.data?.enabled === true;
  const inResolution = operational.resolutions.some((row) => row.source_draft_version === task.version && ["PENDING", "RESOLVING"].includes(String(row.status)));
  const preparationBlocked = operational.resolutions.some((row) => ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"].includes(String(row.status)));
  const blocked = operation.blocked || !enabled || !operational.valid || live.isError || !!task.deleted_at;
  const resolution = task.frozen_manifest?.resolution || detail.resolutions.find((row) => row.status === "ACCEPTED" && row.accepted_task_version === task.version)?.result;
  const repositories = (resolution as CloudRecord | undefined)?.repositories as Record<string, CloudRecord> | undefined;
  const sessionId = typeof attempt?.runtime_metadata?.session_id === "string" ? attempt.runtime_metadata.session_id : attempt ? `cloud-${attempt.id}` : null;

  return <main className="workspace-page cloud-task-detail">
    <WorkspaceHeading title={task.title} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")}
      metadata={<Space><Tag>DeepSeek Harness</Tag><span>{t("Agent-reported result", "Agent 报告结果")}</span><ReportedResultTag result={task.reported_result} /></Space>}
      actions={<Space>{status === "DRAFT" && !task.frozen_manifest && !task.deleted_at ? <Button disabled={blocked || inResolution || !project.data || project.isError} onClick={() => setEditing(task)}>{t("Edit draft", "编辑草稿")}</Button> : null}
        {terminal ? <Link className="ant-btn ant-btn-default" href={`/projects/${projectId}/tasks/new?mode=cloud`}>{t("New test", "新建测试")}</Link> : null}
        <Button icon={<ReloadOutlined aria-hidden />} loading={document.isFetching || live.isFetching} onClick={() => { void document.refetch(); void live.refetch(); }}>{t("Refresh", "刷新")}</Button></Space>} />
    {task.deleted_at ? <Alert showIcon type="info" message={t("Removed from the task list. Saved records are read only.", "已从任务列表移除，保存的记录只读。")} /> : null}
    {document.isError || live.isError ? <Alert showIcon type="warning" message={t("Task details could not be refreshed. Previously loaded records remain visible.", "任务信息刷新失败，已加载记录仍可查看。")} /> : null}
    {status !== "DRAFT" && operation.pending ? <CloudOperationNotice operation={operation} /> : null}
    <Modal open={!!editing} title={null} footer={null} width={1000} destroyOnHidden closable={!operation.busy && !operation.pending} maskClosable={!operation.busy && !operation.pending} keyboard={!operation.busy && !operation.pending} onCancel={() => { if (!operation.busy && !operation.pending) setEditing(null); }}>
      {editing ? <><CloudOperationNotice operation={operation} />
        <CloudTaskForm key={`${editing.id}:${editing.version}`} project={project.data} operation={operation} enabled={enabled && !project.isError && !project.isFetching && operational.valid && !task.deleted_at && status === "DRAFT" && !task.frozen_manifest && !inResolution && task.version === editing.version} editTask={editing} onCancel={() => setEditing(null)} onCreated={() => { setEditing(null); void live.refetch(); void document.refetch(); }} />
      </> : null}
    </Modal>
    {status === "DRAFT" ? <section className="overview-section cloud-task-start">
      <Typography.Paragraph>{inResolution ? t("Preparing repository versions. The Agent will be dispatched automatically.", "正在准备仓库版本，完成后会自动连接 Agent。") : t("Start the test in DeepSeek Harness.", "通过 DeepSeek Harness 开始测试。")}</Typography.Paragraph>
      {preparationBlocked && !inResolution ? <Typography.Paragraph className="muted">{t("The earlier start is still unconfirmed. Refresh to check its status.", "此前开始请求的结果仍待确认，请刷新查看状态。")}</Typography.Paragraph> : null}
      <CloudOperationNotice operation={operation} />
      <Button type="primary" loading={operation.busy || inResolution} disabled={blocked || capabilities.data?.worker_enabled !== true || preparationBlocked} onClick={() => void start()}>{inResolution ? t("Preparing test", "正在准备测试") : t("Start test", "开始测试")}</Button>
    </section> : null}
    {attempt ? <ConversationPanel key={`${projectId}:${taskId}`} projectId={projectId} taskId={taskId} attempt={attempt} attempts={detail.attempts}
      blocked={!enabled || !!task.deleted_at} artifactCount={detail.assets.length + detail.artifacts.length} onArtifacts={openArtifacts} /> : null}
    <details className="cloud-session-info"><summary>{t("Session information", "会话信息")}</summary>
      <Descriptions column={2} layout="vertical" items={[
        { key: "status", label: t("Task state", "任务状态"), children: status === "RECOVERY_REQUIRED" ? t("Session disconnected", "会话已断开") : label(status) },
        ...(sessionId ? [{ key: "session", label: t("Session ID", "会话 ID"), children: <Typography.Text code copyable>{sessionId}</Typography.Text> }] : []),
        { key: "mr", label: t("MR / PR", "MR / PR"), span: 2, children: <span className="session-literal">{text(task.inputs.mr_url)}</span> },
        ...(task.inputs.prompt ? [{ key: "prompt", label: t("Testing instructions", "测试说明"), span: 2, children: <span className="session-literal">{text(task.inputs.prompt)}</span> }] : []),
        ...(repositories ? (["sut", "framework"] as const).map((role) => ({ key: role, label: role === "sut" ? t("SUT source SHA", "被测对象源码 SHA") : t("Framework SHA", "框架 SHA"), children: <Typography.Text code>{text(repositories[role]?.commit_sha)}</Typography.Text> })) : []),
      ]} />
      {setup.data?.harness_web_url ? <Button href={setup.data.harness_web_url} target="_blank" rel="noopener noreferrer" icon={<ExportOutlined aria-hidden />}>{t("Open DeepSeek Harness", "打开 DeepSeek Harness")}</Button> : null}
    </details>
    <CloudTaskRecords document={detail} />
  </main>;
}
