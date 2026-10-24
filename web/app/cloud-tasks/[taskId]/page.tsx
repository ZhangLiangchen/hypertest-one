"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Form, Input, Space, Steps, Table, Tabs, Tag, Typography } from "antd";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReportedResultTag } from "@/app/tasks/task-records";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { CloudAttemptRecovery, CloudCapabilitiesNotice, CloudOperationNotice } from "@/app/projects/[projectId]/cloud/cloud-shared";
import { cloudCapabilities, cloudCancellation, cloudConfiguration, cloudDocument, cloudOperationalView, cloudProgressTone, cloudSetup, cloudSummary } from "@/lib/cloud";
import type { CloudRecord } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import { CloudTaskRecords } from "./records";

const text = (value: unknown) => typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value, null, 2);
const isUuid = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);

export default function CloudTaskPage() {
  const { taskId } = useParams<{ taskId: string }>(); const search = useSearchParams();
  const projectId = search.get("projectId") || "";
  const { t, label } = useI18n(); const [answers, setAnswers] = useState<Record<string, string>>({});
  useEffect(() => { setAnswers({}); }, [projectId, taskId]);
  const operation = useCloudOperation(projectId);
  const setup = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup });
  const configured = setup.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: configured });
  const configurations = useQuery({ queryKey: ["cloud-config", projectId], queryFn: () => cloudConfiguration(projectId), enabled: configured && isUuid(projectId) });
  const document = useQuery({ queryKey: ["cloud-task", projectId, taskId], queryFn: () => cloudDocument(projectId, taskId),
    enabled: configured && isUuid(projectId) && isUuid(taskId), refetchInterval: (query) => {
      const status = query.state.data?.task.status; return status && ["QUEUED", "PREPARING", "RUNNING", "DRAFT"].includes(status) ? 3000 : false;
    } });
  const live = useQuery({ queryKey: ["cloud-task-live", projectId, taskId], queryFn: () => cloudSummary(projectId, taskId), enabled: configured && isUuid(projectId) && isUuid(taskId),
    refetchInterval: (query) => { const status = query.state.data?.status; return !status || ["DRAFT", "QUEUED", "PREPARING", "RUNNING"].includes(status) ? 3000 : false; } });
  useEffect(() => {
    if (live.data && document.data && live.data.id === taskId && live.data.project_id === projectId && live.data.version > document.data.task.version) void document.refetch();
  }, [live.data?.version, document.data?.task.version, taskId, projectId, document.refetch]);
  async function mutate(fields: CloudRecord) {
    if (!document.data || !cloudOperationalView(document.data, live.data).valid) return;
    const receipt = await operation.submit({ task_id: taskId, expected_version: document.data.task.version, ...fields });
    if (receipt) { await document.refetch(); await live.refetch(); }
  }
  if (!isUuid(projectId)) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref="/" backLabel={t("Projects", "项目")} /><Alert showIcon type="error" message={t("Project context is required", "需要项目上下文")} description={t("Open this task from its Project's Cloud directory. A task ID alone does not grant access.", "请从所属项目的云端任务目录打开；仅有任务 ID 不构成访问授权。 ")} /></main>;
  if (!configured) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{setup.isLoading ? <WorkspaceLoading label={t("Checking Cloud access", "正在检查云端访问")} /> : <CloudCapabilitiesNotice configured={false} />}</main>;
  if (!document.data) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{document.isLoading ? <WorkspaceLoading label={t("Loading task records", "正在读取任务记录")} /> : <Alert showIcon type="error" message={t("The fixed task version could not be read", "无法读取固定任务版本")} description={t("Check access and retry. No execution will be submitted by this read.", "请检查访问权限后重试；读取不会下发执行。 ")} action={<Button onClick={() => void document.refetch()}>{t("Retry", "重试")}</Button>} />}</main>;
  const detail = document.data; const task = detail.task; const operational = cloudOperationalView(detail, live.data); const attempt = operational.attempt;
  const status = operational.status;
  const accepted = detail.resolutions.find((row) => row.status === "ACCEPTED" && row.accepted_task_version === task.version);
  const resolution = (accepted?.result || task.frozen_manifest?.resolution) as CloudRecord | undefined;
  const repositories = resolution?.repositories as Record<string, CloudRecord> | undefined;
  const inResolution = operational.resolutions.some((row) => ["PENDING", "RESOLVING"].includes(String(row.status)));
  const enabled = capabilities.data?.enabled === true; const dispatchEnabled = enabled && capabilities.data?.worker_enabled === true;
  const config = configurations.data?.items.find((row) => row.id === task.config_id)?.configuration;
  const remote = config?.environment.connection || ((task.frozen_manifest?.configuration as CloudRecord)?.environment as CloudRecord)?.connection;
  const unsupportedResources = (remote !== undefined && remote !== "NONE") || !!config && (!config.sut.url.startsWith("https://") || !config.framework.url.startsWith("https://"));
  const blocked = operation.blocked || !enabled || !operational.valid;
  const answered = new Set(detail.answers.map((row) => row.question_id));
  const questions = detail.questions.filter((row) => !answered.has(row.id));
  // State identifies current work, not a history of completed business phases.
  // Unknown/recovery/failed/cancelled states cannot establish how far work got.
  const step = status === "DRAFT" ? accepted ? 2 : 1
    : ["QUEUED", "PREPARING", "RUNNING", "WAITING_INPUT"].includes(status || "") ? 3
      : status === "COMPLETED" ? 5 : -1;
  return <main className="workspace-page">
    <WorkspaceHeading title={task.title} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")}
      metadata={<Space wrap><Tag>Cloud · DeepSeek</Tag><Tag color={cloudProgressTone(status || "")}>{status === "PREPARING" ? t("Preparing", "准备中") : status ? label(status) : t("Live state unavailable", "当前运行状态不可用")}</Tag><Typography.Text>{t("Reported test result", "报告的测试结果")}: <ReportedResultTag result={task.reported_result} /></Typography.Text><Typography.Text type="secondary">{t("Accepted version", "接受版本")}: {task.version}</Typography.Text></Space>}
      actions={<Button icon={<ReloadOutlined aria-hidden />} loading={document.isFetching || live.isFetching} onClick={() => { void document.refetch(); void live.refetch(); }}>{t("Refresh records", "刷新记录")}</Button>} />
    <Alert showIcon type="info" message={t("Progress and test results are separate", "任务进度与测试结果分别记录")} description={t("Completed means the agreed work was delivered. FAIL, ERROR and BLOCKED results remain visible with their original reports.", "已完成表示约定工作已交付；失败、错误和阻塞结果及其原始报告继续保留。 ")} style={{ marginBottom: 20 }} />
    {document.isError ? <Alert showIcon type="warning" message={t("Refresh failed; previously verified records are retained.", "刷新失败；保留此前已核验记录。 ")} style={{ marginBottom: 20 }} /> : null}
    {!operational.valid || live.isError ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={operational.newerVersion ? t("Reading a newer accepted version", "正在读取更新的接受版本") : t("Live operational state is not verified", "当前运行状态尚未核验")}
      description={t("Accepted artifacts remain unchanged. Controls wait for matching Project, Task, Attempt and version observations; refresh both views to continue.", "已接受产物保持原样；控制操作等待 Project、Task、Attempt 和版本一致的观察，请刷新两类视图后继续。 ")} /> : null}
    <CloudOperationNotice operation={operation} />
    <Steps current={step} size="small" responsive style={{ marginBottom: 28 }} items={[t("Project resources", "项目资源"), t("Task inputs", "任务输入"), t("Resolve and freeze", "解析与冻结"), t("Harness work", "Harness 工作"), t("Test artifacts", "测试产物"), t("Execution and report", "执行与汇报")].map((title) => ({ title }))} />
    {step < 0 ? <Typography.Paragraph className="muted">{t("Phase completion is unknown in this view. This state alone does not establish which earlier phases completed.", "当前视图无法确定各阶段完成情况；不依据此状态推断此前阶段已经完成。")}</Typography.Paragraph> : null}
    <Tabs className="workspace-tabs" animated={false} items={[
      { key: "overview", label: t("Inputs and control", "输入与控制"), children: <div className="workspace-section-stack">
        <section className="overview-section"><Typography.Title level={2}>{t("Exact source versions", "确切源码版本")}</Typography.Title>
          {repositories ? <Descriptions column={1} items={(["sut", "framework"] as const).map((role) => ({ key: role, label: role === "sut" ? t("SUT SHA", "被测 SHA") : t("Framework SHA", "框架 SHA"), children: <><Typography.Text code>{text(repositories[role]?.commit_sha)}</Typography.Text>{repositories[role]?.base_sha ? <Typography.Paragraph className="entity-key">base: {text(repositories[role].base_sha)} · head: {text(repositories[role].head_sha)}</Typography.Paragraph> : null}</> }))} /> : <Typography.Paragraph className="muted">{t("The worker has not accepted immutable repository identities yet.", "Worker 尚未接受不可变仓库版本。 ")}</Typography.Paragraph>}
          {status === "DRAFT" ? <Space wrap><Button loading={inResolution} disabled={blocked || inResolution || !!accepted || !config || unsupportedResources} onClick={() => void mutate({ operation: "RESOLVE_INPUTS" })}>{inResolution ? t("Resolving versions", "正在解析版本") : t("Resolve both repositories", "解析双仓版本")}</Button>
            <Button type="primary" disabled={operation.blocked || !operational.valid || !dispatchEnabled || !accepted || !config || unsupportedResources} onClick={() => void mutate({ operation: "DISPATCH", resolution_id: accepted?.id })}>{t("Dispatch these exact versions", "下发上述确切版本")}</Button></Space> : null}
          {unsupportedResources ? <Alert showIcon type="warning" style={{ marginTop: 16 }} message={t("These resources cannot run in the current profile", "当前运行配置无法执行这些资源")} description={t("Only HTTPS Git repositories and workspace-local fixtures are supported. Preserve this draft and configure supported resources for a new task.", "当前仅支持 HTTPS Git 仓库和工作区内测试。请保留此草稿，并配置受支持资源后创建新任务。 ")} /> : null}
          {!dispatchEnabled ? <Typography.Paragraph className="muted" style={{ marginTop: 16 }}>{t("Dispatch requires enabled Cloud admission and an enabled worker. Historical reads remain available.", "下发需要启用 Cloud 准入和 Worker；历史读取继续可用。 ")}</Typography.Paragraph> : null}
          {operational.resolutions.some((row) => ["FAILED", "RECOVERY_REQUIRED"].includes(String(row.status))) ? <Alert showIcon type="warning" style={{ marginTop: 16 }} message={t("Input resolution needs attention", "输入解析需要处理")} description={t("Check repository access, selectors and the original operation. Do not restart an uncertain resolution automatically.", "请核对仓库访问、版本选择和原操作；不要自动重新开始结果不明的解析。 ")} /> : null}
        </section>
        <section className="overview-section"><Typography.Title level={2}>{t("Frozen task intent", "任务输入意图")}</Typography.Title>
          <Descriptions column={1} items={[{ key: "objective", label: t("Objective", "目标"), children: <span className="session-literal">{text(task.inputs.objective)}</span> },
            { key: "flow", label: t("Basic flow", "基本流程"), children: <span className="session-literal">{text(task.inputs.basic_flow)}</span> },
            { key: "scope", label: t("Scope", "范围"), children: <span className="session-literal">{text(task.inputs.test_scope)}</span> },
            { key: "entrypoints", label: t("Framework entrypoints", "框架入口"), children: <pre className="session-literal">{text(task.inputs.framework_entrypoints)}</pre> },
            { key: "budgets", label: t("Frozen budgets", "冻结预算"), children: <pre className="session-literal">{text(task.inputs.budgets)}</pre> },
          ]} /><details><summary>{t("Read original PRD", "查看 PRD 原文")}</summary><pre className="artifact-content session-markdown">{text(task.inputs.prd_markdown)}</pre></details>
        </section>
        {attempt ? <section className="overview-section"><Typography.Title level={2}>{t("Current attempt", "当前执行尝试")}</Typography.Title><Typography.Paragraph className="entity-key">{attempt.id} · #{attempt.attempt_no}</Typography.Paragraph><Typography.Paragraph>{attempt.reason}</Typography.Paragraph>
          {attempt.status === "WAITING_INPUT" ? questions.map((question) => <Form key={String(question.id)} className="workspace-form form-section" layout="vertical" onFinish={() => void mutate({ operation: "ANSWER_INPUT", attempt_id: attempt.id, question_id: question.id, answer: answers[String(question.id)] })}>
            <Typography.Title level={3}>{text(question.question)}</Typography.Title>
            {Array.isArray(question.options) ? <ul>{question.options.map((option, index) => <li key={index}>{text(option)}</li>)}</ul> : null}
            <Form.Item label={t("Answer within the existing authorization", "在现有授权范围内回答")} required><Input.TextArea rows={3} maxLength={16000} value={answers[String(question.id)] || ""} onChange={(event) => setAnswers((current) => ({ ...current, [String(question.id)]: event.target.value }))} /></Form.Item>
            <Button htmlType="submit" disabled={operation.blocked || !operational.valid || !answers[String(question.id)]?.trim()}>{t("Save answer", "保存回答")}</Button>
          </Form>) : null}
          <CloudAttemptRecovery key={`${projectId}:${taskId}:${attempt.id}`} attempt={attempt} capabilities={capabilities.data} recovery={live.data?.recovery}
            blocked={operation.blocked || !operational.valid} onSubmit={mutate} />
        </section> : null}
        {status && !["COMPLETED", "FAILED", "CANCELLED"].includes(status) ? <section className="overview-section"><Typography.Title level={2}>{t("Cancel this task or attempt", "取消当前任务或尝试")}</Typography.Title>
          <Typography.Paragraph className="muted">{t("Cancellation fences the writer first. Active or uncertain work stays in recovery until cleanup and external operations are reconciled.", "取消会先隔离写入权；活动或未知工作在清理及外部操作完成对账前保持待恢复。 ")}</Typography.Paragraph>
          <Typography.Paragraph className="muted">{t("This control records the fixed reason OPERATOR_REQUESTED_CANCELLATION. It remains a single keyed request, including when credential decryption is unavailable.", "本操作记录固定原因 OPERATOR_REQUESTED_CANCELLATION；即使凭据暂时无法解密，也使用同一个幂等请求完成隔离控制。 ")}</Typography.Paragraph>
          <Button danger disabled={operation.blocked || !operational.valid || attempt?.checkpoint.cancellation_requested === true} onClick={() => void mutate(cloudCancellation(attempt?.id))}>{attempt?.checkpoint.cancellation_requested === true ? t("Cancellation requested", "已请求取消") : t("Request cancellation", "请求取消")}</Button>
        </section> : null}
      </div> },
      { key: "artifacts", label: t("Artifacts and results", "产物与结果"), children: <CloudTaskRecords document={detail} /> },
      { key: "attempts", label: t("Attempt history", "尝试历史"), children: <div className="data-surface"><Table rowKey="id" dataSource={detail.attempts} scroll={{ x: 650 }} pagination={false} columns={[
        { title: t("Attempt", "尝试"), dataIndex: "attempt_no" }, { title: t("Progress", "进度"), dataIndex: "status", render: (value: string) => <Tag color={cloudProgressTone(value)}>{label(value)}</Tag> },
        { title: t("Reported result", "报告结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> }, { title: t("Reason", "原因"), dataIndex: "reason" },
      ]} /></div> },
    ]} />
  </main>;
}
