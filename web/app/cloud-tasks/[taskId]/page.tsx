"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Form, Input, Modal, Space, Steps, Table, Tabs, Tag, Typography } from "antd";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReportedResultTag } from "@/app/tasks/task-records";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { CloudAttemptRecovery, CloudCapabilitiesNotice, CloudOperationNotice } from "@/app/projects/[projectId]/cloud/cloud-shared";
import { cloudCapabilities, cloudCancellation, cloudDocument, cloudManagementMessage, cloudOperationalView, cloudProgressTone, cloudSetup, cloudSummary } from "@/lib/cloud";
import type { CloudRecord } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { cloudPollingVersion, cloudSummaryPollInterval, readCloudPollingDocument } from "@/lib/run-polling";
import { getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { CloudTaskRecords } from "./records";
import { LiveQuestionsPanel } from "./live-questions-panel";
import { CloudTaskForm } from "@/app/projects/[projectId]/cloud/task-form";
import { CloudTaskDelete } from "./delete-task";
import { RetryDialog } from "./retry-dialog";
import type { CloudTask } from "@/lib/cloud";

const text = (value: unknown) => typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value, null, 2);
const isUuid = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);

export default function CloudTaskPage() {
  const { taskId } = useParams<{ taskId: string }>(); const search = useSearchParams();
  const projectId = search.get("projectId") || "";
  const { t, label } = useI18n(); const [editing, setEditing] = useState<CloudTask | null>(null); const [answers, setAnswers] = useState<Record<string, string>>({});
  const [tab, setTab] = useState("overview");
  const [retry, setRetry] = useState<{ attemptId: string; version: number } | null>(null);
  const [destination, setDestination] = useState<{ tab: string; id: string } | null>(null);
  useEffect(() => { setAnswers({}); setEditing(null); setTab("overview"); setDestination(null); setRetry(null); }, [projectId, taskId]);
  useEffect(() => {
    if (!destination || destination.tab !== tab) return;
    const frame = window.requestAnimationFrame(() => {
      const target = window.document.getElementById(destination.id);
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "start" });
      setDestination(null);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [destination, tab]);
  function goToSection(event: React.MouseEvent<HTMLAnchorElement>, nextTab: string, id: string) {
    event.preventDefault();
    setTab(nextTab);
    setDestination({ tab: nextTab, id });
  }
  const operation = useCloudOperation(projectId);
  const setup = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup });
  const configured = setup.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: configured });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true), enabled: configured && isUuid(projectId) });
  const live = useQuery({ queryKey: ["cloud-task-live", projectId, taskId], queryFn: () => cloudSummary(projectId, taskId), enabled: configured && isUuid(projectId) && isUuid(taskId),
    refetchInterval: (query) => cloudSummaryPollInterval(projectId, taskId, query.state.data), refetchOnWindowFocus: true });
  const observedVersion = cloudPollingVersion(projectId, taskId, live.data);
  const document = useQuery({ queryKey: ["cloud-task", projectId, taskId], queryFn: () => readCloudPollingDocument(projectId, taskId, live.data, cloudDocument),
    enabled: configured && isUuid(projectId) && isUuid(taskId) && observedVersion !== undefined,
    staleTime: Infinity });
  useEffect(() => {
    // Heavy accepted records are fetched once per observed version. A failed read
    // keeps the old document and can retry on the next successful summary read.
    if (observedVersion !== undefined && (!document.data || observedVersion > document.data.task.version) && !document.isFetching) void document.refetch();
  }, [observedVersion, live.dataUpdatedAt, document.data?.task.version, taskId, projectId, document.refetch]);
  useEffect(() => {
    if (editing && operation.receipt?.operation === "UPDATE_TASK" && operation.receipt.task_id === editing.id && operation.receipt.version === editing.version + 1) {
      setEditing(null); void live.refetch(); void document.refetch();
    }
  }, [editing, operation.receipt, live.refetch, document.refetch]);
  useEffect(() => {
    // A lost dispatch response is resolved by original key. Once that receipt
    // is read back, close the original form instead of allowing a new intent.
    if (retry && operation.receipt?.operation === "DISPATCH" && operation.receipt.task_id === taskId && operation.receipt.version === retry.version + 1) {
      setRetry(null); void live.refetch(); void document.refetch();
    }
  }, [retry, taskId, operation.receipt, live.refetch, document.refetch]);
  async function mutate(fields: CloudRecord) {
    if (!document.data || (document.data.task.deleted_at && fields.operation !== "RECONCILE_ATTEMPT") || !cloudOperationalView(document.data, live.data).valid) return;
    const receipt = await operation.submit({ task_id: taskId, expected_version: document.data.task.version, ...fields });
    if (receipt) { await document.refetch(); await live.refetch(); }
  }
  if (!isUuid(projectId)) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref="/" backLabel={t("Projects", "项目")} /><Alert showIcon type="error" message={t("Project context is required", "需要项目上下文")} description={t("Open this task from its Project's Cloud directory. A task ID alone does not grant access.", "请从所属项目的云端任务目录打开；仅有任务 ID 不构成访问授权。 ")} /></main>;
  if (!configured) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{setup.isLoading ? <WorkspaceLoading label={t("Checking Cloud access", "正在检查云端访问")} /> : <CloudCapabilitiesNotice configured={false} />}</main>;
  if (!document.data) return <main className="workspace-page"><WorkspaceHeading title={t("Cloud task", "云端任务")} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")} />{live.isLoading || document.isLoading ? <WorkspaceLoading label={t("Loading task records", "正在读取任务记录")} /> : <Alert showIcon type="error" message={t("The fixed task version could not be read", "无法读取固定任务版本")} description={t("Check access and retry. No execution will be submitted by this read.", "请检查访问权限后重试；读取不会下发执行。 ")} action={<Button onClick={() => { void live.refetch(); void document.refetch(); }}>{t("Retry", "重试")}</Button>} />}</main>;
  const detail = document.data; const task = detail.task; const operational = cloudOperationalView(detail, live.data); const attempt = operational.attempt;
  const status = operational.status;
  const accepted = detail.resolutions.find((row) => row.status === "ACCEPTED" && row.accepted_task_version === task.version);
  const resolution = (accepted?.result || task.frozen_manifest?.resolution) as CloudRecord | undefined;
  const repositories = resolution?.repositories as Record<string, CloudRecord> | undefined;
  const inResolution = operational.resolutions.some((row) => row.source_draft_version === task.version && ["PENDING", "RESOLVING"].includes(String(row.status)));
  const preparationBlocked = operational.resolutions.some((row) => ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"].includes(String(row.status)));
  const enabled = capabilities.data?.enabled === true; const dispatchEnabled = enabled && capabilities.data?.worker_enabled === true;
  const blocked = operation.blocked || !enabled || !operational.valid || live.isError || !!task.deleted_at;
  const management = operational.valid && !live.isError ? live.data?.management : undefined;
  const terminalAttempt = !!attempt && ["COMPLETED", "FAILED", "CANCELLED"].includes(status || "") && attempt.status === status;
  const canRetry = terminalAttempt && management?.can_retry === true;
  const answered = new Set(detail.answers.map((row) => row.question_id));
  const questions = detail.questions.filter((row) => !answered.has(row.id));
  // State identifies current work, not a history of completed business phases.
  // Unknown/recovery/failed/cancelled states cannot establish how far work got.
  const step = live.isError ? -1 : status === "DRAFT" ? accepted || inResolution ? 1 : 0
    : ["QUEUED", "PREPARING", "RUNNING", "WAITING_INPUT"].includes(status || "") ? 2
      : status === "COMPLETED" ? 4 : -1;
  // A record can confirm a specific fact without proving every earlier or later phase.
  const currentResolution = !live.isError && status === "DRAFT"
    ? operational.resolutions.filter((row) => row.source_draft_version === task.version && ["PENDING", "RESOLVING", "FAILED", "RECOVERY_REQUIRED"].includes(String(row.status))).slice(-1)[0] : undefined;
  const phaseStates: { tone: "complete" | "active" | "failed" | "unknown" | "waiting"; text: string }[] = [
    { tone: "complete", text: t("Inputs saved", "输入已保存") },
    currentResolution?.status === "FAILED" ? { tone: "failed", text: t("Resolution failed", "解析失败") }
      : currentResolution?.status === "RECOVERY_REQUIRED" ? { tone: "unknown", text: t("Needs recovery", "需要恢复") }
      : currentResolution ? { tone: "active", text: t("Resolving", "解析中") }
      : task.frozen_manifest?.resolution ? { tone: "complete", text: t("Frozen", "已冻结") }
      : accepted ? { tone: "complete", text: t("Resolved", "已解析") } : { tone: "unknown", text: t("Unknown", "未知") },
    !live.isError && attempt?.status === "COMPLETED" ? { tone: "complete", text: t("Work delivered", "工作已交付") }
      : !live.isError && attempt?.status === "WAITING_INPUT" ? { tone: "waiting", text: t("Waiting for input", "等待输入") }
      : !live.isError && ["QUEUED", "PREPARING", "RUNNING"].includes(attempt?.status || "") ? { tone: "active", text: attempt?.status === "QUEUED" ? t("Queued", "排队中") : attempt?.status === "PREPARING" ? t("Preparing", "准备中") : t("Running", "进行中") }
      : { tone: "unknown", text: t("Unknown", "未知") },
    !live.isError && attempt?.status === "COMPLETED" ? { tone: "complete", text: t("Required artifacts accepted", "所需产物已接受") }
      : { tone: "unknown", text: detail.assets.some((asset) => asset.attempt_id === task.latest_attempt_id) ? t("Artifacts recorded; completion unknown", "已有产物，完成情况未知") : t("Unknown", "未知") },
    task.reported_result === "PASS" ? { tone: "complete", text: t("Reported pass", "报告通过") }
      : ["FAIL", "ERROR"].includes(task.reported_result) ? { tone: "failed", text: t("Reported failure", "报告失败") }
      : { tone: "unknown", text: task.reported_result === "NOT_RUN" ? t("Not run", "未执行") : task.reported_result === "SKIPPED" ? t("Skipped", "已跳过") : task.reported_result === "BLOCKED" ? t("Blocked", "已阻塞") : t("Result unknown", "结果未知") },
  ];
  return <main className="workspace-page cloud-task-detail">
    <WorkspaceHeading title={task.title} backHref={`/projects/${projectId}/cloud`} backLabel={t("Project cloud tasks", "项目云端任务")}
      metadata={<div className="cloud-task-metadata"><div><span>{t("Source", "来源")}</span><Tag>Cloud · DeepSeek</Tag></div><div><span>{t("Task progress", "任务进度")}</span><Tag color={cloudProgressTone(status || "")}>{status === "PREPARING" ? t("Preparing", "准备中") : status ? label(status) : t("Live state unavailable", "当前运行状态不可用")}</Tag></div><div><span>{t("Reported test result", "报告的测试结果")}</span><ReportedResultTag result={task.reported_result} /></div><div><span>{t("Accepted version", "接受版本")}</span><strong>{task.version}</strong></div></div>}
      actions={<Space wrap>{status === "DRAFT" && !task.frozen_manifest && !task.deleted_at ? <Button disabled={blocked || inResolution || !project.data || project.isError} onClick={() => setEditing(task)}>{t("Edit draft", "编辑草稿")}</Button> : null}<CloudTaskDelete projectId={projectId} detail={detail} operational={operational} recovery={live.isError ? undefined : live.data?.recovery} management={management} operation={operation} /><Button icon={<ReloadOutlined aria-hidden />} loading={document.isFetching || live.isFetching} onClick={() => { void document.refetch(); void live.refetch(); void project.refetch(); }}>{t("Refresh records", "刷新记录")}</Button></Space>} />
    {task.deleted_at ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Removed from the task list", "已从任务列表移除")}
      description={t("Records and original operation references remain available at this link. You can continue reconciliation here; deletion does not confirm stopping or resolve unknown outcomes, and this task cannot start new execution.", "本链接仍可查看历史记录和原操作引用，并继续对账。删除不代表进程已停止或未知结果已确认；此任务不能再下发执行。 ")} /> : null}
    <Modal open={!!editing} title={null} footer={null} width={1000} destroyOnHidden closable={!operation.busy && !operation.pending} maskClosable={!operation.busy && !operation.pending} keyboard={!operation.busy && !operation.pending} onCancel={() => { if (!operation.busy && !operation.pending) setEditing(null); }}>
      {editing ? <><CloudOperationNotice operation={operation} />{(task.deleted_at || task.version !== editing.version || status !== "DRAFT" || !!task.frozen_manifest || !operational.valid || inResolution) ? <Alert showIcon type="warning" message={t("The draft changed or its current state cannot be verified. Close and reopen the editor after refreshing.", "草稿已变化或当前状态无法核验，请关闭编辑并刷新后重新打开。")} /> : null}
        <CloudTaskForm key={`${editing.id}:${editing.version}`} project={project.data} operation={operation} enabled={enabled && !project.isError && !project.isFetching && operational.valid && !task.deleted_at && status === "DRAFT" && !task.frozen_manifest && !inResolution && task.version === editing.version} editTask={editing} onCancel={() => setEditing(null)} onCreated={() => { setEditing(null); void live.refetch(); void document.refetch(); }} />
      </> : null}
    </Modal>
    {retry ? <RetryDialog task={task} actions={live.data?.controlled_actions_history?.flatMap((group) => group.actions.map((action) => ({ ...action, attempt_id: group.attempt_id }))) ?? live.data?.controlled_actions} notice={<CloudOperationNotice operation={operation} />}
      invalid={blocked || !dispatchEnabled || retry.version !== task.version || retry.attemptId !== attempt?.id || !canRetry}
      stale={!operational.valid || live.isError || retry.version !== task.version || retry.attemptId !== attempt?.id || !canRetry}
      busy={operation.busy || !!operation.pending}
      onCancel={() => setRetry(null)} onSubmit={(retryInputs) => {
        if (retry.version !== task.version || retry.attemptId !== attempt?.id || blocked || !dispatchEnabled || !canRetry) return;
        void (async () => {
          const receipt = await operation.submit({ task_id: taskId, expected_version: retry.version, operation: "DISPATCH", retry_of_attempt_id: retry.attemptId,
            retry_scope_confirmed: true, retry_authorization_confirmed: true, retry_inputs: retryInputs, reason: "Operator confirmed scope and authorization for a new attempt" });
          if (receipt) { setRetry(null); await document.refetch(); await live.refetch(); }
        })();
      }} /> : null}
    <Alert showIcon type="info" message={t("Progress and test results are separate", "任务进度与测试结果分别记录")} description={t("Completed means the agreed work was delivered. FAIL, ERROR and BLOCKED results remain visible with their original reports.", "已完成表示约定工作已交付；失败、错误和阻塞结果及其原始报告继续保留。 ")} style={{ marginBottom: 20 }} />
    {document.isError ? <Alert showIcon type="warning" message={t("Refresh failed; previously verified records are retained.", "刷新失败；保留此前已核验记录。 ")} style={{ marginBottom: 20 }} /> : null}
    {!operational.valid || live.isError ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={operational.newerVersion ? t("Reading a newer accepted version", "正在读取更新的接受版本") : t("Live operational state is not verified", "当前运行状态尚未核验")}
      description={t("Accepted artifacts remain unchanged. Controls wait for matching Project, Task, Attempt and version observations; refresh both views to continue.", "已接受产物保持原样；控制操作等待 Project、Task、Attempt 和版本一致的观察，请刷新两类视图后继续。 ")} /> : null}
    <CloudOperationNotice operation={operation} />
    <section className="cloud-task-flow" aria-label={t("Task workflow", "任务流程")}>
      <div className="cloud-flow-summary">
        <div className="cloud-flow-position">{step < 0 ? t("Current phase unknown", "当前阶段未知") : <>{t("Current phase", "当前阶段")} <strong>{step + 1} <span>/</span> 5</strong></>}</div>
        <div className="cloud-flow-facts"><span>{live.isError && status ? t("Last observed progress", "上次观察的进度") : t("Task progress", "任务进度")} <Tag color={cloudProgressTone(status || "")}>{status === "PREPARING" ? t("Preparing", "准备中") : status ? label(status) : t("Unknown", "未知")}</Tag></span><span>{t("Reported test result", "报告的测试结果")} <ReportedResultTag result={task.reported_result} /></span></div>
      </div>
      <Steps current={step} size="small" responsive items={[
        ...[
          { title: t("Task inputs", "任务输入"), tab: "overview", id: "cloud-task-inputs" },
          { title: t("Test preparation", "测试准备"), tab: "overview", id: "cloud-task-resolution" },
          { title: t("Harness work", "Harness 工作"), tab: "attempts", id: "cloud-attempt-history-heading" },
          { title: t("Test artifacts", "测试产物"), tab: "artifacts", id: "cloud-assets-title" },
          { title: t("Execution and report", "执行与汇报"), tab: "artifacts", id: "cloud-runs-title" },
        ].map(({ title, tab: nextTab, id }) => ({ title: <a href={`#${id}`} onClick={(event) => goToSection(event, nextTab, id)}>{title}</a> })),
      ].map((item, index) => ({ ...item, icon: <span className={`cloud-flow-number cloud-flow-${phaseStates[index].tone}`} aria-hidden="true">{index + 1}</span>,
        title: <span aria-current={index === step ? "step" : undefined}>{item.title}</span>,
        description: <span className={`cloud-flow-state cloud-flow-state-${phaseStates[index].tone}`}>{phaseStates[index].text}</span> }))} />
      {step < 0 ? <p className="muted">{t("Phase completion is unknown in this view. This state alone does not establish which earlier phases completed.", "当前视图无法确定各阶段完成情况；不依据此状态推断此前阶段已经完成。")}</p> : null}
    </section>
    {attempt ? <LiveQuestionsPanel key={`${projectId}:${taskId}:${attempt.id}`} projectId={projectId} taskId={taskId} attemptId={attempt.id}
      running={status === "RUNNING" && attempt.status === "RUNNING"} blocked={blocked || live.isError} /> : null}
    <Tabs className="workspace-tabs" activeKey={tab} onChange={setTab} animated={false} items={[
      { key: "overview", label: t("Inputs and control", "输入与控制"), children: <div className="cloud-task-overview">
        <div className="cloud-task-control-grid">
          <section className="overview-section cloud-task-source-versions"><Typography.Title id="cloud-task-resolution" tabIndex={-1} level={2}>{t("Test execution", "测试执行")}</Typography.Title>
            {status === "DRAFT" ? <>
              <Typography.Paragraph className="muted">{t("Start once to prepare the code and dispatch the task automatically. Work continues even if you close this page.", "点击开始后，系统自动准备代码并下发任务。无需另行操作，关闭页面也会继续。")}</Typography.Paragraph>
              <Button type="primary" loading={operation.busy || inResolution} disabled={blocked || !dispatchEnabled || preparationBlocked} onClick={() => void mutate({ operation: "START_TASK" })}>{inResolution ? t("Preparing test", "正在准备测试") : t("Start test", "开始测试")}</Button>
              {inResolution ? <Typography.Paragraph className="muted" role="status" style={{ marginTop: 16 }}>{currentResolution?.start_requested === true
                ? t("Preparing repository versions. The Agent will be dispatched automatically when preparation succeeds.", "正在准备仓库版本，成功后会自动下发给 Agent。")
                : t("A previous code preparation request is running. When it finishes, select Start test to continue.", "此前的代码准备请求正在处理，完成后点击开始测试即可继续。")}</Typography.Paragraph> : null}
            </> : null}
            {!dispatchEnabled ? <Typography.Paragraph className="muted" style={{ marginTop: 16 }}>{t("Dispatch requires enabled Cloud admission and an enabled worker. Historical reads remain available.", "下发需要启用 Cloud 准入和 Worker；历史读取继续可用。 ")}</Typography.Paragraph> : null}
            {status === "DRAFT" && operational.resolutions.some((row) => row.status === "RECOVERY_REQUIRED")
              ? <Alert showIcon type="warning" style={{ marginTop: 16 }} message={t("Code preparation needs recovery", "代码准备需要恢复")} description={t("An earlier preparation result is unconfirmed. Review and reconcile its original record before starting; the Agent has not been dispatched.", "此前的准备结果尚未确认，需先核对原准备记录并完成恢复；Agent 尚未下发。")}/>
              : currentResolution?.status === "FAILED"
              ? <Alert showIcon type="warning" style={{ marginTop: 16 }} message={t("Code preparation failed", "代码准备失败")} description={t("The Agent has not been dispatched. Check repository access, then select Start test to prepare again.", "Agent 尚未下发。请检查仓库访问，处理后点击开始测试重新准备。")}/>
              : operational.resolutions.some((row) => ["FAILED", "RECOVERY_REQUIRED"].includes(String(row.status)))
                ? <Alert showIcon type="info" style={{ marginTop: 16 }} message={t("Historical input resolution issues are retained", "历史输入解析异常记录已保留")} description={t("Use the resolved or frozen versions shown above for the current attempt. Historical unknown outcomes remain unknown; a new attempt does not replay earlier requests.", "当前解析或冻结版本以上方显示为准。历史未知结果仍保留，新尝试不会重放旧请求。")} /> : null}
            <details className="cloud-task-source-details"><summary>{t("Code version details", "代码版本详情")}</summary>
              <Typography.Paragraph className="muted">{t("The MR / PR source and test framework versions are recorded for this task. They do not confirm which version is deployed in the test environment.", "记录本次使用的 MR / PR 源码和测试框架版本，不代表测试环境已部署这些版本。")}</Typography.Paragraph>
              {repositories ? <Descriptions column={1} layout="vertical" items={(["sut", "framework"] as const).map((role) => ({ key: role, label: role === "sut" ? t("SUT source SHA", "被测对象源码 SHA") : t("Framework SHA", "框架 SHA"), children: <div className="cloud-task-sha"><Typography.Text code>{text(repositories[role]?.commit_sha)}</Typography.Text>{repositories[role]?.base_sha ? <div className="entity-key"><div>base: {text(repositories[role].base_sha)}</div><div>head: {text(repositories[role].head_sha)}</div></div> : null}</div> }))} /> : <Typography.Paragraph className="muted">{t("Code versions will appear after preparation succeeds.", "代码准备成功后将在此显示版本。")}</Typography.Paragraph>}
            </details>
          </section>
          {attempt ? <section className="overview-section"><Typography.Title level={2}>{t("Current attempt", "当前执行尝试")}</Typography.Title><Typography.Paragraph className="entity-key">{attempt.id} · #{attempt.attempt_no}</Typography.Paragraph><Typography.Paragraph>{attempt.reason}</Typography.Paragraph>
            {terminalAttempt && !task.deleted_at ? <div style={{ marginBottom: 16 }}>
              <Typography.Paragraph className="muted">{t("Start a new attempt after reviewing its scope and authorization. The previous attempt and its records remain available.", "核对本次范围和授权后可下发新尝试，原尝试及其记录会保留。")}</Typography.Paragraph>
              {management?.native_scope_unobserved ? <Typography.Paragraph className="muted">{t("The direct Harness process exited. Other host processes and external outcomes remain unobserved; starting a new attempt does not change those records.", "已观察到 Harness 直接进程退出；其他宿主进程与外部结果仍未观察，新尝试不会改变这些记录。")}</Typography.Paragraph> : null}
              {(live.data?.controlled_actions_history?.flatMap((group) => group.actions) ?? live.data?.controlled_actions)?.some((action) => action.state === "SENT_UNRECONCILED" || action.state === "IDENTIFIED_UNRECONCILED") ? <Alert showIcon type="warning" style={{ marginBottom: 12 }} message={t("An earlier action remains unreconciled", "此前动作尚未对账")} description={t("Reconcile the original action by its original key before retrying.", "下发前请按原操作键对账。 ")} /> : null}
              {!canRetry ? <Typography.Paragraph className="muted">{cloudManagementMessage(management?.retry_blocking_reasons[0], t)}</Typography.Paragraph> : null}
              <Button disabled={blocked || !dispatchEnabled || !canRetry} onClick={() => { if (!blocked && dispatchEnabled && canRetry) setRetry({ attemptId: attempt.id, version: task.version }); }}>{t("Start new attempt", "新建执行尝试")}</Button>
            </div> : null}
            {attempt.status === "WAITING_INPUT" ? <Alert showIcon type="warning" style={{ marginBottom: 16 }} message={t("Answers are recorded but cannot resume this agent session", "回答只会保存，无法继续此 Agent 会话")} description={t("The current worker does not support original-session continuation. Review previous external operations before planning further work.", "当前 Worker 不支持继续原会话。安排后续工作前，请核对此前的外部操作。 ")} /> : null}
            {attempt.status === "WAITING_INPUT" ? questions.map((question) => <Form key={String(question.id)} className="workspace-form form-section cloud-task-fields" layout="vertical" onFinish={() => void mutate({ operation: "ANSWER_INPUT", attempt_id: attempt.id, question_id: question.id, answer: answers[String(question.id)] })}>
              <Typography.Title level={3}>{text(question.question)}</Typography.Title>
              {Array.isArray(question.options) ? <ul>{question.options.map((option, index) => <li key={index}>{text(option)}</li>)}</ul> : null}
              <Form.Item label={t("Answer within the existing authorization", "在现有授权范围内回答")} required><Input.TextArea rows={3} maxLength={16000} value={answers[String(question.id)] || ""} onChange={(event) => setAnswers((current) => ({ ...current, [String(question.id)]: event.target.value }))} /></Form.Item>
              <Button htmlType="submit" disabled={operation.blocked || !!task.deleted_at || !operational.valid || !answers[String(question.id)]?.trim()}>{t("Save answer", "保存回答")}</Button>
            </Form>) : null}
            <CloudAttemptRecovery key={`${projectId}:${taskId}:${attempt.id}`} attempt={attempt} capabilities={capabilities.data} recovery={live.data?.recovery}
              blocked={operation.blocked || !operational.valid || live.isError} onSubmit={mutate} />
          </section> : null}
          {status && !["COMPLETED", "FAILED", "CANCELLED"].includes(status) ? <section className="overview-section"><Typography.Title level={2}>{t("Cancel this task or attempt", "取消当前任务或尝试")}</Typography.Title>
            <Typography.Paragraph className="muted">{t("Cancellation fences the writer first. Active or uncertain work stays in recovery until cleanup and external operations are reconciled.", "取消会先隔离写入权；活动或未知工作在清理及外部操作完成对账前保持待恢复。 ")}</Typography.Paragraph>
            <Typography.Paragraph className="muted">{t("This control records the fixed reason OPERATOR_REQUESTED_CANCELLATION. It remains a single keyed request, including when credential decryption is unavailable.", "本操作记录固定原因 OPERATOR_REQUESTED_CANCELLATION；即使凭据暂时无法解密，也使用同一个幂等请求完成隔离控制。 ")}</Typography.Paragraph>
            <Button danger disabled={operation.blocked || !!task.deleted_at || !operational.valid || attempt?.checkpoint.cancellation_requested === true} onClick={() => void mutate(cloudCancellation(attempt?.id))}>{attempt?.checkpoint.cancellation_requested === true ? t("Cancellation requested", "已请求取消") : t("Request cancellation", "请求取消")}</Button>
          </section> : null}
        </div>
        <section className="overview-section cloud-task-intent"><Typography.Title id="cloud-task-inputs" tabIndex={-1} level={2}>{t("Frozen task intent", "任务输入意图")}</Typography.Title>
          <Descriptions column={2} layout="vertical" items={[
            ...(task.inputs.prompt != null ? [{ key: "prompt", label: t("Testing instructions", "测试说明"), span: 2, children: <span className="session-literal">{text(task.inputs.prompt)}</span> }] : []),
            ...(task.inputs.objective ? [{ key: "objective", label: t("Objective", "目标"), children: <span className="session-literal">{text(task.inputs.objective)}</span> }] : []),
            ...(task.inputs.test_scope ? [{ key: "scope", label: t("Scope", "范围"), children: <span className="session-literal">{text(task.inputs.test_scope)}</span> }] : []),
            { key: "mr", label: t("MR / PR URL", "MR / PR 地址"), span: 2, children: <span className="session-literal">{text(task.inputs.mr_url)}</span> },
            ...(task.inputs.basic_flow ? [{ key: "flow", label: t("Testing instructions / prompt", "测试说明 / Prompt"), span: 2, children: <span className="session-literal">{text(task.inputs.basic_flow)}</span> }] : []),
            ...(task.inputs.budgets != null ? [{ key: "budgets", label: t("Frozen budgets", "冻结预算"), span: 2, children: <pre className="session-literal">{text(task.inputs.budgets)}</pre> }] : []),
          ]} />{task.inputs.prd_markdown ? <details><summary>{t("Read original PRD", "查看 PRD 原文")}</summary><pre className="artifact-content session-markdown">{text(task.inputs.prd_markdown)}</pre></details> : null}
        </section>
      </div> },
      { key: "artifacts", label: t("Artifacts and results", "产物与结果"), children: <CloudTaskRecords document={detail} /> },
      { key: "attempts", label: t("Attempt history", "尝试历史"), children: <section className="cloud-task-history" aria-labelledby="cloud-attempt-history-heading"><Typography.Title id="cloud-attempt-history-heading" tabIndex={-1} level={2}>{t("Attempt history", "尝试历史")}</Typography.Title><div className="data-surface"><Table rowKey="id" dataSource={detail.attempts} scroll={{ x: 650 }} pagination={false} expandable={{ expandedRowRender: (row) => {
        const inputs = (row.execution_manifest?.inputs || task.inputs) as CloudRecord;
        return <><Typography.Paragraph>{row.execution_manifest ? t("Inputs confirmed for this attempt", "本次尝试确认的输入") : t("This attempt used the original frozen inputs", "本次尝试使用原冻结输入")}</Typography.Paragraph><Descriptions column={1} size="small" layout="vertical" items={[
          ...(inputs.prompt != null ? [{ key: "prompt", label: t("Testing instructions", "测试说明"), children: <span className="session-literal">{text(inputs.prompt)}</span> }] : []),
          { key: "objective", label: t("Objective", "目标"), children: <span className="session-literal">{text(inputs.objective)}</span> },
          { key: "scope", label: t("Scope", "范围"), children: <span className="session-literal">{text(inputs.test_scope)}</span> },
          { key: "flow", label: t("Execution steps", "执行步骤"), children: <span className="session-literal">{text(inputs.basic_flow)}</span> },
          { key: "entrypoints", label: t("Framework entrypoints", "框架入口"), children: <pre className="session-literal">{text(inputs.framework_entrypoints)}</pre> },
          { key: "authorization", label: t("Authorization", "授权"), children: <pre className="session-literal">{text(inputs.authorization)}</pre> },
          { key: "digest", label: t("Input digest", "输入摘要"), children: <span className="entity-key">{text(row.input_digest)}</span> },
        ]} /></>;
      } }} columns={[
        { title: t("Attempt", "尝试"), dataIndex: "attempt_no" }, { title: t("Progress", "进度"), dataIndex: "status", render: (value: string) => <Tag color={cloudProgressTone(value)}>{label(value)}</Tag> },
        { title: t("Reported result", "报告结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> }, { title: t("Reason", "原因"), dataIndex: "reason" },
      ]} /></div>
        <Typography.Title level={2} style={{ marginTop: 32 }}>{t("Controlled action history", "受控动作历史")}</Typography.Title>
        <Typography.Paragraph className="muted">{t("Records retain their original attempt and operation key. A business terminal state alone does not establish a chain receipt or independently observed outcome.", "动作保留原尝试及原操作键。业务终态本身不代表已取得链上回执或独立观察到实际结果。")}</Typography.Paragraph>
        {live.isError || !operational.valid ? <Alert showIcon type="warning" message={t("Action history could not be refreshed", "动作历史无法刷新")} description={t("Refresh the task to read current action records.", "请刷新任务以读取当前动作记录。")}/> :
          <div className="data-surface"><Table rowKey={(row) => String((row as CloudRecord).identity_id)}
            dataSource={(live.data?.controlled_actions_history || []).flatMap((group) => group.actions.map((action) => ({ ...action, attempt_id: group.attempt_id })))}
            scroll={{ x: 850 }} pagination={false} columns={[
              { title: t("Attempt", "尝试"), dataIndex: "attempt_id", render: (id: string) => { const row = detail.attempts.find((item) => item.id === id); return row ? <span>#{row.attempt_no} · <span className="entity-key">{id}</span></span> : <span className="entity-key">{id}</span>; } },
              { title: t("Action", "动作"), dataIndex: "action_key", render: text },
              { title: t("Original operation key", "原操作键"), dataIndex: "operation_key", render: (value: unknown) => <span className="entity-key">{text(value)}</span> },
              { title: t("Recorded state", "记录状态"), dataIndex: "state", render: (value: unknown) => <Tag>{text(value)}</Tag> },
              { title: t("Observations", "观察记录"), dataIndex: "observations", render: (value: unknown) => <details><summary>{t("View observations", "查看观察记录")}</summary><pre className="session-literal">{text(value)}</pre></details> },
            ]}/></div>}
      </section> },
    ]} />
  </main>;
}
