"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Drawer, Empty, Popconfirm, Space, Spin, Table, Tag, Timeline, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";

import { cancelJob, createJob, getJob, getJobs, getMission, retryJob, retryMission } from "@/lib/api";
import type { BackgroundJob, JobCreate, JobOperation, JobStatus, Mission } from "@/lib/types";

const activeStatuses: JobStatus[] = ["QUEUED", "RUNNING", "CANCEL_REQUESTED"];
const retryableStatuses: JobStatus[] = ["FAILED", "INTERRUPTED", "CANCELLED"];
const labels: Record<JobOperation, string> = {
  ADVANCE_RUN: "Run test cycle", EXECUTE_MISSION: "Execute mission", EXECUTE_TESTS: "Execute tests",
  EVALUATE_GATE: "Evaluate quality gate", PREPARE_WORKSPACE: "Prepare pinned checkout",
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function jobColor(status: JobStatus) {
  if (status === "SUCCEEDED") return "green";
  if (status === "FAILED") return "red";
  if (["CANCEL_REQUESTED", "INTERRUPTED"].includes(status)) return "gold";
  if (status === "RUNNING") return "blue";
  return "default";
}

function Status({ job }: { job: BackgroundJob }) {
  return <Tag color={jobColor(job.status)}>{job.status.replaceAll("_", " ")}</Tag>;
}

function timestamp(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value).filter(([, entry]) => entry !== undefined).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function useRunJobs(runId: string, useWorkspace: (workspace: string) => void) {
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

  async function submit(operation: JobOperation, payload: Record<string, unknown>, missionId?: string) {
    const options = { ...payload };
    if (operation === "EXECUTE_TESTS") delete options.idempotency_key;
    const request = { operation, payload: options, ...(missionId ? { mission_id: missionId } : {}) };
    const pending = pendingKey(`${operation}:${missionId || "run"}`, request);
    const job = await createJob(runId, {
      ...request,
      payload: operation === "EXECUTE_TESTS" ? { ...options, idempotency_key: `${pending.key}:execution` } : options,
      idempotency_key: pending.key,
    } as JobCreate);
    accepted(pending.storageKey);
    updateJob(job);
    notifications.success("Task saved. It continues independently of this browser tab.");
    return job;
  }

  useEffect(() => {
    if (!jobs.data) return;
    let canonicalChanged = false;
    for (const job of jobs.data) {
      for (const scope of [`${job.job_type}:${job.mission_id || "run"}`, ...(job.retry_of_job_id ? [`retry:${job.retry_of_job_id}`] : [])]) {
        const storageKey = `hypertest.pending-job.${runId}.${scope}`;
        try {
          const pending = JSON.parse(localStorage.getItem(storageKey) || "null");
          if (pending?.key === job.idempotency_key) accepted(storageKey);
        } catch { /* Job status remains authoritative when local browser storage is unavailable. */ }
      }
      const previous = statuses.current.get(job.id);
      if (previous && previous !== job.status && !activeStatuses.includes(job.status)) {
        canonicalChanged = true;
        if (job.status === "SUCCEEDED") {
          notifications.success(`${labels[job.job_type]} finished. Testing state refreshed.`);
          if (job.job_type === "PREPARE_WORKSPACE" && typeof job.result?.workspace === "string") useWorkspace(job.result.workspace);
        } else if (job.status === "INTERRUPTED") notifications.warning("A task was interrupted. Review its recorded work before retrying.");
        else if (job.status === "FAILED") notifications.error(`${labels[job.job_type]} failed. Open Tasks for the recorded error.`);
      }
      statuses.current.set(job.id, job.status);
    }
    if (canonicalChanged) {
      for (const key of ["run", "requirements", "risks", "test-cases", "coverage", "missions", "implementations", "executions", "evidence", "findings", "verdicts"]) {
        void client.invalidateQueries({ queryKey: [key, runId] });
      }
      for (const key of ["mission", "attempts", "proposals"]) void client.invalidateQueries({ queryKey: [key] });
    }
  }, [jobs.data, client, runId, notifications, useWorkspace]);

  const cancellation = useMutation({
    mutationFn: (job: BackgroundJob) => cancelJob(job.id),
    onSuccess: (job) => { updateJob(job); notifications.info(job.status === "CANCELLED" ? "Task cancelled." : "Cancellation requested. The worker will stop at a safe boundary."); },
  });
  const retry = useMutation({
    mutationFn: async (job: BackgroundJob) => {
      if (job.job_type === "EXECUTE_MISSION" && job.mission_id) {
        const mission = await getMission(job.mission_id);
        if (mission.status === "CANCELLED") throw new Error("This mission was cancelled. Plan a new mission instead of retrying its task.");
        if (mission.status === "FAILED") await retryMission(mission.id);
      }
      const pending = pendingKey(`retry:${job.id}`, { job_id: job.id });
      const next = await retryJob(job.id, pending.key);
      accepted(pending.storageKey);
      return next;
    },
    onSuccess: (job) => { updateJob(job); setSelectedId(job.id); notifications.success("A new recovery task was queued. The previous task remains in history."); },
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
      <Button size="small" onClick={() => { setSelectedId(job.id); cancellation.reset(); retry.reset(); }}>Details</Button>
      {activeStatuses.includes(job.status) && job.status !== "CANCEL_REQUESTED" && <Popconfirm title="Cancel this background task?" description="The worker stops at a safe boundary. Accepted canonical testing state remains available." onConfirm={() => cancellation.mutate(job)}><Button size="small" danger loading={cancellation.isPending && cancellation.variables?.id === job.id}>Cancel task</Button></Popconfirm>}
      {retryableStatuses.includes(job.status) && (cancelledMission ? <Typography.Text type="secondary">Mission cancelled. Plan a new mission.</Typography.Text> : <Button size="small" disabled={active.length > 0 || unknownMission} loading={retry.isPending && retry.variables?.id === job.id} onClick={() => retry.mutate(job)}>{unknownMission ? "Checking mission state" : "Retry as new task"}</Button>)}
    </Space>;
  }

  const columns = [
    { title: "Task", key: "task", render: (_: unknown, job: BackgroundJob) => <Space direction="vertical" size={2}><Typography.Text strong>{labels[job.job_type]}</Typography.Text><span className="entity-key">{job.key}</span></Space> },
    { title: "Status", key: "status", render: (_: unknown, job: BackgroundJob) => <Status job={job} /> },
    { title: "Created", dataIndex: "created_at", render: timestamp },
    { title: "Actions", key: "actions", render: (_: unknown, job: BackgroundJob) => actions(job) },
  ];

  const taskTab = {
    key: "tasks", label: `Tasks (${rows.length})`, children: <>
      <Typography.Paragraph className="muted">Tasks are saved by HyperTest and processed by an independent worker. Reloading or closing this page leaves the recorded work available here.</Typography.Paragraph>
      {jobs.isLoading ? <div className="pane-loading"><Spin /></div> : jobs.error ? <Alert type="error" showIcon message="Unable to load background tasks" description={errorMessage(jobs.error)} action={<Button onClick={() => void jobs.refetch()}>Retry</Button>} /> : rows.length ? <Table rowKey="id" columns={columns} dataSource={rows} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No background tasks yet. Run a test cycle or start an individual operation." />}
      {(cancellation.error || retry.error) && <Alert type="error" showIcon message="Task action failed" description={errorMessage(cancellation.error || retry.error)} style={{ marginTop: 16 }} />}
    </>,
  };

  const monitor = <>
    {jobs.error && <Alert type="warning" showIcon message="Background task status is unavailable" description="Refresh task status before starting additional work." action={<Button onClick={() => void jobs.refetch()}>Refresh tasks</Button>} style={{ marginBottom: 16 }} />}
    {active.length > 0 && <Card className="section-card" title={<Space><Spin size="small" />Background tasks ({active.length})</Space>} style={{ marginBottom: 20 }}>
      <Typography.Paragraph className="muted">Work continues on the worker. You can leave this page and return to the same tasks.</Typography.Paragraph>
      <Table rowKey="id" size="small" columns={columns} dataSource={active} pagination={false} scroll={{ x: 750 }} />
    </Card>}
    {rows[0] && ["FAILED", "INTERRUPTED"].includes(rows[0].status) && <Alert type={rows[0].status === "INTERRUPTED" ? "warning" : "error"} showIcon message={rows[0].status === "INTERRUPTED" ? "A background task needs recovery" : "The latest background task failed"} description={rows[0].error_message || "Review the task details and recorded canonical state before retrying."} action={<Button onClick={() => setSelectedId(rows[0].id)}>Review task</Button>} style={{ marginBottom: 20 }} />}
  </>;

  const dialog = <>
    {contextHolder}
    <Drawer title={current ? `${labels[current.job_type]} · ${current.key}` : "Background task"} open={!!selectedId} width={850} onClose={() => setSelectedId(null)}>
      {selected.isLoading ? <Spin /> : selected.error ? <Alert type="error" message="Unable to load task" description={errorMessage(selected.error)} /> : current && <>
        <Space wrap style={{ marginBottom: 16 }}><Status job={current} />{actions(current)}</Space>
        {current.status === "QUEUED" && <Alert type="info" showIcon message="Waiting for an available worker" description="The task is saved. Keep the worker service running; this browser does not execute the task." style={{ marginBottom: 20 }} />}
        {current.status === "INTERRUPTED" && <Alert type="warning" showIcon message="Worker execution was interrupted" description="Review the recorded missions, executions and evidence. Retry creates a new task and preserves this task's history; completed canonical state remains available." style={{ marginBottom: 20 }} />}
        {current.status === "CANCEL_REQUESTED" && <Alert type="info" showIcon message="Waiting for the worker to acknowledge cancellation" description="The recorded status changes to CANCELLED after the worker stops at a safe boundary." style={{ marginBottom: 20 }} />}
        {current.error_message && <Alert type="error" showIcon message={current.error_code || "Task error"} description={<span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{current.error_message}</span>} style={{ marginBottom: 20 }} />}
        <Descriptions bordered column={1} size="small" items={[
          { key: "operation", label: "Operation", children: labels[current.job_type] },
          { key: "retry", label: "Previous task", children: current.retry_of_job_id ? <Button type="link" onClick={() => setSelectedId(current.retry_of_job_id!)}>{current.retry_of_job_id}</Button> : "First attempt" },
          { key: "attempts", label: "Worker claims", children: current.attempts ?? "—" },
          { key: "worker", label: "Worker", children: current.worker_id || "Not assigned" },
        ]} />
        <Typography.Title level={4}>Task timeline</Typography.Title>
        <Timeline items={[
          { color: "blue", children: <>Saved · {timestamp(current.created_at)}</> },
          ...(current.started_at ? [{ color: "blue", children: <>Started · {timestamp(current.started_at)}</> }] : []),
          ...(current.heartbeat_at ? [{ color: "blue", children: <>Last worker heartbeat · {timestamp(current.heartbeat_at)}</> }] : []),
          ...(current.cancel_requested_at ? [{ color: "orange", children: <>Cancellation requested · {timestamp(current.cancel_requested_at)}</> }] : []),
          ...(current.finished_at ? [{ color: current.status === "SUCCEEDED" ? "green" : "red", children: <>{current.status.replaceAll("_", " ")} · {timestamp(current.finished_at)}</> }] : []),
        ]} />
        {typeof current.result?.reason === "string" && <Typography.Paragraph><strong>Result: </strong>{current.result.reason.replaceAll("_", " ")}</Typography.Paragraph>}
        {current.result && ["mission_key", "execution_key", "verdict_key", "decision", "outcome"].some((key) => typeof current.result?.[key] === "string") && <>
          <Typography.Title level={4}>Recorded result</Typography.Title>
          <Descriptions bordered column={1} size="small" items={[
            ...["mission_key", "execution_key", "verdict_key"].filter((key) => typeof current.result?.[key] === "string").map((key) => ({ key, label: key.replace("_key", "").replace(/^./, (letter) => letter.toUpperCase()), children: <Typography.Text code copyable>{current.result![key] as string}</Typography.Text> })),
            ...["decision", "outcome"].filter((key) => typeof current.result?.[key] === "string").map((key) => ({ key, label: key === "decision" ? "Quality decision" : "Execution outcome", children: <Tag color={["PASS", "RELEASE_READY"].includes(current.result![key] as string) ? "green" : "red"}>{current.result![key] as string}</Tag> })),
          ]} />
        </>}
        {typeof current.result?.workspace === "string" && <><Typography.Title level={5}>Prepared workspace</Typography.Title><Typography.Paragraph><Typography.Text code copyable>{current.result.workspace}</Typography.Text></Typography.Paragraph><Button onClick={() => useWorkspace(current.result!.workspace as string)}>Use this workspace</Button></>}
        {(cancellation.error || retry.error) && <Alert type="error" showIcon message="Task action failed" description={errorMessage(cancellation.error || retry.error)} style={{ marginTop: 16 }} />}
      </>}
    </Drawer>
  </>;

  return { jobs, rows, active, busy: active.length > 0 || jobs.isLoading || !!jobs.error, submit, taskTab, monitor, dialog, latestPrepared };
}
