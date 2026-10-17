"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Drawer, Empty, Popconfirm, Space, Spin, Table, Tag, Timeline, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";

import { cancelJob, createJob, errorText, getJob, getJobs, getMission, retryJob, retryMission } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { BackgroundJob, JobCreate, JobOperation, JobStatus, Mission } from "@/lib/types";

const activeStatuses: JobStatus[] = ["QUEUED", "RUNNING", "CANCEL_REQUESTED"];
const retryableStatuses: JobStatus[] = ["FAILED", "INTERRUPTED", "CANCELLED"];
function jobColor(status: JobStatus) {
  if (status === "SUCCEEDED") return "green";
  if (status === "FAILED") return "red";
  if (["CANCEL_REQUESTED", "INTERRUPTED"].includes(status)) return "gold";
  if (status === "RUNNING") return "blue";
  return "default";
}

function Status({ job }: { job: BackgroundJob }) {
  const { label } = useI18n();
  return <Tag color={jobColor(job.status)}>{label(job.status)}</Tag>;
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value).filter(([, entry]) => entry !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function useRunJobs(runId: string, useWorkspace: (workspace: string) => void, onViewResult: (section: string, key?: string) => void) {
  const { t, label, locale, formatDate } = useI18n();
  const client = useQueryClient();
  const [notifications, contextHolder] = message.useMessage();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pendingRequests = useRef(new Map<string, { signature: string; key: string }>());
  const statuses = useRef(new Map<string, JobStatus>());
  const jobs = useQuery({ queryKey: ["jobs", runId], queryFn: () => getJobs(runId), refetchInterval: 1_500 });
  const selected = useQuery({ queryKey: ["job", selectedId], queryFn: () => getJob(selectedId!), enabled: !!selectedId, refetchInterval: 1_500 });

  function pendingKey(scope: string, request: unknown) {
    const storageKey = `hypertest.pending-job.${runId}.${scope}`;
    const signature = stableJson(request);
    let previous = pendingRequests.current.get(storageKey);
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) previous = JSON.parse(saved);
    } catch { /* The in-memory key still protects repeated requests in this tab. */ }
    const record = previous?.signature === signature ? previous : { signature, key: `web:${crypto.randomUUID()}` };
    pendingRequests.current.set(storageKey, record);
    try { localStorage.setItem(storageKey, JSON.stringify(record)); } catch { /* Storage may be disabled by the browser. */ }
    return { key: record.key, storageKey };
  }

  function accepted(storageKey: string) {
    pendingRequests.current.delete(storageKey);
    try { localStorage.removeItem(storageKey); } catch { /* No automatic submission occurs on page load. */ }
  }

  function updateJob(job: BackgroundJob) {
    client.setQueryData<BackgroundJob[]>(["jobs", runId], (current = []) => [job, ...current.filter((item) => item.id !== job.id)]);
    client.setQueryData(["job", job.id], job);
  }

  async function confirmSubmission(request: () => Promise<BackgroundJob>, key: string) {
    try { return await request(); }
    catch (error) {
      // A POST may commit even when its response is lost. Recover that exact task;
      // if this read also fails, retain the key so an explicit retry is safe.
      try {
        const recorded = (await getJobs(runId)).find((job) => job.idempotency_key === key);
        if (recorded) return recorded;
      } catch { /* The original submission error remains the useful failure. */ }
      throw error;
    }
  }

  async function submit(operation: JobOperation, payload: Record<string, unknown>, missionId?: string) {
    const options = { ...payload };
    if (operation === "EXECUTE_TESTS") delete options.idempotency_key;
    const request = { operation, payload: options, ...(missionId ? { mission_id: missionId } : {}) };
    const pending = pendingKey(`${operation}:${missionId || "run"}`, request);
    const job = await confirmSubmission(() => createJob(runId, {
      ...request,
      payload: operation === "EXECUTE_TESTS" ? { ...options, idempotency_key: `${pending.key}:execution` } : options,
      idempotency_key: pending.key,
    } as JobCreate), pending.key);
    accepted(pending.storageKey);
    updateJob(job);
    if (operation !== "PREPARE_WORKSPACE") { setSelectedId(job.id); onViewResult("tasks"); }
    notifications.success(t("Task saved. It continues independently of this browser tab.", "任务已保存。Worker 将独立于浏览器继续处理。"));
    return job;
  }

  useEffect(() => {
    if (!jobs.data) return;
    let canonicalChanged = false;
    for (const job of jobs.data) {
      const previous = statuses.current.get(job.id);
      if (previous && previous !== job.status && !activeStatuses.includes(job.status)) {
        canonicalChanged = true;
        if (job.status === "SUCCEEDED") {
          notifications.success(`${label(job.job_type)} · ${t("Task finished. Review the quality verdict for the testing decision.", "任务已完成。测试结论请查看质量判定。")}`);
          if (job.job_type === "PREPARE_WORKSPACE" && typeof job.result?.workspace === "string") useWorkspace(job.result.workspace);
        } else if (job.status === "INTERRUPTED") notifications.warning(t("A task was interrupted. Review its recorded work before retrying.", "任务已中断。请先查看已记录的工作，再重试。"));
        else if (job.status === "FAILED") notifications.error(`${label(job.job_type)} · ${t("Task failed. Open Tasks for the recorded error.", "任务失败，请打开后台任务查看错误记录。")}`);
      }
      statuses.current.set(job.id, job.status);
    }
    if (canonicalChanged) {
      for (const key of ["run", "requirements", "risks", "test-cases", "coverage", "missions", "implementations", "executions", "evidence", "findings", "verdicts"]) {
        void client.invalidateQueries({ queryKey: [key, runId] });
      }
      for (const key of ["mission", "attempts", "proposals"]) void client.invalidateQueries({ queryKey: [key] });
    }
  }, [jobs.data, client, runId, notifications, useWorkspace, t, label]);

  const cancellation = useMutation({
    mutationFn: (job: BackgroundJob) => cancelJob(job.id),
    onSuccess: (job) => { updateJob(job); notifications.info(job.status === "CANCELLED" ? t("Task cancelled.", "任务已取消。") : t("Cancellation requested. The worker will stop at a safe boundary.", "已请求取消。Worker 会在安全边界停止。")); },
  });
  const retry = useMutation({
    mutationFn: async (job: BackgroundJob) => {
      if (job.job_type === "EXECUTE_MISSION" && job.mission_id) {
        const mission = await getMission(job.mission_id);
        if (mission.status === "CANCELLED") throw new Error(t("This mission was cancelled. Plan a new mission instead of retrying its task.", "此测试任务已取消。请规划新任务，而非重试原任务。"));
        if (mission.status === "FAILED") await retryMission(mission.id);
      }
      const pending = pendingKey(`retry:${job.id}`, { job_id: job.id });
      const next = await confirmSubmission(() => retryJob(job.id, pending.key), pending.key);
      accepted(pending.storageKey);
      return next;
    },
    onSuccess: (job) => { updateJob(job); setSelectedId(job.id); notifications.success(t("A new recovery task was queued. The previous task remains in history.", "恢复任务已入队，原任务记录会保留在历史中。")); },
  });

  const rows = [...(jobs.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const active = rows.filter((job) => activeStatuses.includes(job.status));
  const current = selected.data || rows.find((job) => job.id === selectedId);
  const latestPrepared = rows.find((job) => job.job_type === "PREPARE_WORKSPACE" && job.status === "SUCCEEDED" && typeof job.result?.workspace === "string");

  function actions(job: BackgroundJob) {
    const mission = job.mission_id ? client.getQueryData<Mission[]>(["missions", runId])?.find((item) => item.id === job.mission_id) : undefined;
    const cancelledMission = job.job_type === "EXECUTE_MISSION" && mission?.status === "CANCELLED";
    const unknownMission = job.job_type === "EXECUTE_MISSION" && !mission;
    return <Space wrap>
      <Button size="small" onClick={() => { setSelectedId(job.id); cancellation.reset(); retry.reset(); }}>{t("Details", "详情")}</Button>
      {activeStatuses.includes(job.status) && job.status !== "CANCEL_REQUESTED" && <Popconfirm title={t("Cancel this background task?", "确认取消此后台任务？")} description={t("The worker stops at a safe boundary. Accepted canonical testing state remains available.", "Worker 会在安全边界停止，已接受的正式测试状态仍会保留。")} onConfirm={() => cancellation.mutate(job)}><Button size="small" danger loading={cancellation.isPending && cancellation.variables?.id === job.id}>{t("Cancel task", "取消任务")}</Button></Popconfirm>}
      {retryableStatuses.includes(job.status) && (cancelledMission ? <Typography.Text type="secondary">{t("Mission cancelled. Plan a new mission.", "测试任务已取消，请规划新任务。")}</Typography.Text> : <Button size="small" disabled={active.length > 0 || unknownMission} loading={retry.isPending && retry.variables?.id === job.id} onClick={() => retry.mutate(job)}>{unknownMission ? t("Checking mission state", "正在检查任务状态") : t("Retry as new task", "新建重试任务")}</Button>)}
    </Space>;
  }

  const columns = [
    { title: t("Task", "后台任务"), key: "task", render: (_: unknown, job: BackgroundJob) => <Space direction="vertical" size={2}><Typography.Text strong>{label(job.job_type)}</Typography.Text><span className="entity-key">{job.key}</span></Space> },
    { title: t("Status", "状态"), key: "status", render: (_: unknown, job: BackgroundJob) => <Status job={job} /> },
    { title: t("Created", "创建时间"), dataIndex: "created_at", render: formatDate },
    { title: t("Actions", "操作"), key: "actions", render: (_: unknown, job: BackgroundJob) => actions(job) },
  ];

  const taskTab = {
    key: "tasks", label: `${t("Tasks", "后台任务")} (${rows.length})`, children: <>
      <Typography.Paragraph className="muted">{t("Tasks are saved by HyperTest and processed by an independent worker. Reloading or closing this page leaves the recorded work available here.", "任务由 HyperTest 持久保存并交给独立 Worker 处理。刷新或关闭页面后，仍可在这里查看记录。")}</Typography.Paragraph>
      {jobs.isLoading ? <div className="pane-loading"><Spin /></div> : jobs.error && !jobs.data ? <Alert type="error" showIcon message={t("Unable to load background tasks", "无法加载后台任务")} description={errorText(jobs.error, locale)} action={<Button onClick={() => void jobs.refetch()}>{t("Retry", "重试")}</Button>} /> : rows.length ? <Table rowKey="id" columns={columns} dataSource={rows} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("No background tasks yet. Run a test cycle or start an individual operation.", "暂无后台任务。可运行完整测试周期，或单独发起操作。")} />}
      {(cancellation.error || retry.error) && <Alert type="error" showIcon message={t("Task action failed", "任务操作失败")} description={errorText(cancellation.error || retry.error, locale)} style={{ marginTop: 16 }} />}
    </>,
  };

  const monitor = <>
    {jobs.error && <Alert type="warning" showIcon message={t("Background task status is unavailable", "后台任务状态暂不可用")} description={t("Refresh task status before starting additional work.", "请刷新任务状态，再发起新操作。")} action={<Button onClick={() => void jobs.refetch()}>{t("Refresh tasks", "刷新任务")}</Button>} style={{ marginBottom: 16 }} />}
    {active.length > 0 && <Card className="section-card" title={<Space><Spin size="small" />{t("Background tasks", "后台任务")} ({active.length})</Space>} style={{ marginBottom: 20 }}>
      <Typography.Paragraph className="muted">{t("Work continues on the worker. You can leave this page and return to the same tasks.", "Worker 会继续处理。离开页面后，返回仍可查看同一任务。")}</Typography.Paragraph>
      <Table rowKey="id" size="small" columns={columns} dataSource={active} pagination={false} scroll={{ x: 750 }} />
    </Card>}
    {rows[0] && ["FAILED", "INTERRUPTED"].includes(rows[0].status) && <Alert type={rows[0].status === "INTERRUPTED" ? "warning" : "error"} showIcon message={rows[0].status === "INTERRUPTED" ? t("A background task needs recovery", "后台任务需要恢复") : t("The latest background task failed", "最新后台任务失败")} description={rows[0].error_message || t("Review the task details and recorded canonical state before retrying.", "请先查看任务详情及已记录的正式状态，再决定是否重试。")} action={<Button onClick={() => setSelectedId(rows[0].id)}>{t("Review task", "查看任务")}</Button>} style={{ marginBottom: 20 }} />}
  </>;

  function viewResult(section: string, key?: string) {
    setSelectedId(null);
    onViewResult(section, key);
  }
  const steps = Array.isArray(current?.result?.steps) ? current.result.steps.filter((step): step is { action: string; key: string; status: string } => !!step && typeof step === "object" && typeof (step as Record<string, unknown>).action === "string" && typeof (step as Record<string, unknown>).key === "string" && typeof (step as Record<string, unknown>).status === "string") : [];
  const dialog = <>
    {contextHolder}
    <Drawer title={current ? `${label(current.job_type)} · ${current.key}` : t("Background task", "后台任务")} open={!!selectedId} width={850} onClose={() => setSelectedId(null)}>
      {selected.isLoading ? <Spin /> : selected.error && !current ? <Alert type="error" message={t("Unable to load task", "无法加载任务详情")} description={errorText(selected.error, locale)} action={<Button onClick={() => void selected.refetch()}>{t("Retry", "重试")}</Button>} /> : current && <>
        <Space wrap style={{ marginBottom: 16 }}><Status job={current} />{actions(current)}</Space>
        {selected.error && <Alert type="warning" showIcon message={t("Task refresh failed; showing recorded data", "任务刷新失败，正在显示已加载记录")} description={errorText(selected.error, locale)} action={<Button onClick={() => void selected.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
        {current.status === "SUCCEEDED" && <Alert type="info" showIcon message={t("Task completed; the quality verdict determines test readiness", "后台任务已完成，测试质量以质量判定为准")} description={t("A successful task means the requested operation finished. Tests may still fail and the release may remain blocked. Inspect the execution, evidence and latest verdict below.", "任务成功表示请求的操作已完成。测试仍可能失败，发布仍可能被阻止。请继续查看执行、证据和最新质量判定。")} style={{ marginBottom: 16 }} />}
        <Space wrap style={{ marginBottom: 20 }}>
          <Button onClick={() => viewResult("missions")}>{t("View missions", "查看测试任务")}</Button>
          <Button onClick={() => viewResult("executions")}>{t("View executions", "查看执行")}</Button>
          <Button onClick={() => viewResult("evidence")}>{t("View evidence", "查看证据")}</Button>
          <Button onClick={() => viewResult("findings")}>{t("View findings", "查看发现")}</Button>
          <Button onClick={() => viewResult("verdicts")}>{t("View quality verdicts", "查看质量判定")}</Button>
        </Space>
        {current.status === "QUEUED" && <Alert type="info" showIcon message={t("Waiting for an available worker", "等待可用 Worker")} description={t("The task is saved. Keep the worker service running; this browser does not execute the task.", "任务已保存。请保持 Worker 服务运行，任务由 Worker 执行。")} style={{ marginBottom: 20 }} />}
        {current.status === "INTERRUPTED" && <Alert type="warning" showIcon message={t("Worker execution was interrupted", "Worker 执行已中断")} description={t("Review the recorded missions, executions and evidence. Retry creates a new task and preserves this task's history; completed canonical state remains available.", "请检查已记录的智能体任务、执行和证据。重试会创建新任务并保留原历史，已完成的正式状态仍会保留。")} style={{ marginBottom: 20 }} />}
        {current.status === "CANCEL_REQUESTED" && <Alert type="info" showIcon message={t("Waiting for the worker to acknowledge cancellation", "等待 Worker 确认取消")} description={t("The recorded status changes to CANCELLED after the worker stops at a safe boundary.", "Worker 在安全边界停止后，状态会更新为“已取消”（CANCELLED）。")} style={{ marginBottom: 20 }} />}
        {current.error_message && <Alert type="error" showIcon message={current.error_code || t("Task error", "任务错误")} description={<span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{current.error_message}</span>} style={{ marginBottom: 20 }} />}
        <Descriptions bordered column={1} size="small" items={[
          { key: "operation", label: t("Operation", "操作"), children: label(current.job_type) },
          { key: "retry", label: t("Previous task", "前一任务"), children: current.retry_of_job_id ? <Button type="link" onClick={() => setSelectedId(current.retry_of_job_id!)}>{current.retry_of_job_id}</Button> : t("First attempt", "首次任务") },
          { key: "attempts", label: t("Worker claims", "Worker 领取次数"), children: current.attempts ?? "—" },
          { key: "worker", label: t("Worker", "Worker"), children: current.worker_id || t("Not assigned", "尚未分配") },
        ]} />
        <Typography.Title level={4}>{t("Task timeline", "任务时间线")}</Typography.Title>
        <Timeline items={[
          { color: "blue", children: <>{t("Saved", "已保存")} · {formatDate(current.created_at)}</> },
          ...(current.started_at ? [{ color: "blue", children: <>{t("Started", "已开始")} · {formatDate(current.started_at)}</> }] : []),
          ...(current.heartbeat_at ? [{ color: "blue", children: <>{t("Last worker heartbeat", "最近 Worker 心跳")} · {formatDate(current.heartbeat_at)}</> }] : []),
          ...(current.cancel_requested_at ? [{ color: "orange", children: <>{t("Cancellation requested", "已请求取消")} · {formatDate(current.cancel_requested_at)}</> }] : []),
          ...(current.finished_at ? [{ color: current.status === "SUCCEEDED" ? "green" : "red", children: <>{label(current.status)} · {formatDate(current.finished_at)}</> }] : []),
        ]} />
        {typeof current.result?.reason === "string" && <Typography.Paragraph><strong>{t("Result", "结果")}: </strong>{label(current.result.reason)}</Typography.Paragraph>}
        {current.result && ["mission_key", "execution_key", "verdict_key", "decision", "outcome"].some((key) => typeof current.result?.[key] === "string") && <>
          <Typography.Title level={4}>{t("Recorded result", "已记录结果")}</Typography.Title>
          <Descriptions bordered column={1} size="small" items={[
            ...["mission_key", "execution_key", "verdict_key"].filter((key) => typeof current.result?.[key] === "string").map((key) => ({ key, label: key === "mission_key" ? t("Mission", "测试任务") : key === "execution_key" ? t("Execution", "执行") : t("Verdict", "质量判定"), children: <Typography.Text code copyable>{current.result![key] as string}</Typography.Text> })),
            ...["decision", "outcome"].filter((key) => typeof current.result?.[key] === "string").map((key) => ({ key, label: key === "decision" ? t("Quality decision", "质量判定") : t("Execution outcome", "执行结果"), children: <Tag color={["PASS", "RELEASE_READY"].includes(current.result![key] as string) ? "green" : "red"}>{label(current.result![key] as string)}</Tag> })),
          ]} />
        </>}
        {steps.length > 0 && <>
          <Typography.Title level={4}>{t("Recorded cycle steps", "已记录的周期步骤")}</Typography.Title>
          <Table size="small" rowKey={(step) => `${step.action}:${step.key}`} dataSource={steps} pagination={false} columns={[
            { title: t("Stage", "阶段"), dataIndex: "action", render: (value: string) => value === "mission" ? t("Agent mission", "智能体任务") : value === "execution" ? t("Runner execution", "Runner 执行") : t("Quality verdict", "质量判定") },
            { title: t("Record", "记录"), key: "record", render: (_: unknown, step: { action: string; key: string }) => <Button type="link" style={{ padding: 0 }} onClick={() => viewResult(step.action === "mission" ? "missions" : step.action === "execution" ? "executions" : "verdicts", step.key)}>{step.key}</Button> },
            { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => label(value) },
          ]} />
        </>}
        {typeof current.result?.workspace === "string" && <><Typography.Title level={5}>{t("Prepared workspace", "已准备的工作目录")}</Typography.Title><Typography.Paragraph><Typography.Text code copyable>{current.result.workspace}</Typography.Text></Typography.Paragraph><Button onClick={() => useWorkspace(current.result!.workspace as string)}>{t("Use this workspace", "使用此目录")}</Button></>}
        {(cancellation.error || retry.error) && <Alert type="error" showIcon message={t("Task action failed", "任务操作失败")} description={errorText(cancellation.error || retry.error, locale)} style={{ marginTop: 16 }} />}
      </>}
    </Drawer>
  </>;

  return { jobs, rows, active, busy: active.length > 0 || jobs.isLoading || !!jobs.error, submit, taskTab, monitor, dialog, latestPrepared };
}
