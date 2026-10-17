"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert, Button, Descriptions, Drawer, Empty, Form, Input, InputNumber,
  Popconfirm, Select, Space, Spin, Table, Tag, Typography, message,
} from "antd";
import type { TabsProps } from "antd";
import { useCallback, useEffect, useState } from "react";
import { ClientModal as Modal } from "@/app/client-modal";

import {
  cancelMission, getEvidence,
  getEvidenceContent, getExecution, getExecutions, getFindings, getImplementations,
  getCapabilities, getMission, getMissionAttempts, getMissionProposals, getVerdicts, retryMission, transitionFinding,
} from "@/lib/api";
import { useRunJobs } from "./use-run-jobs";

import type { Evidence, ExecutionCreate, Finding, Mission, MissionProposal, TestExecution, TestImplementation, Verdict } from "@/lib/types";

function color(value: string | null | undefined) {
  if (["PASS", "RELEASE_READY", "COMPLETED", "ACCEPTED", "VERIFIED", "VALIDATED", "FINAL", "RESOLVED", "CLOSED"].includes(value || "")) return "green";
  if (["FAIL", "FAILED", "ERROR", "TIMED_OUT", "RELEASE_BLOCKED", "REJECTED", "BLOCKER", "CRITICAL"].includes(value || "")) return "red";
  if (["BLOCKED", "INCONCLUSIVE", "RETEST_REQUIRED", "NEW", "REOPENED", "PARTIAL"].includes(value || "")) return "gold";
  if (["RUNNING", "DISPATCHED", "VERIFYING", "COLLECTING", "TRIAGED"].includes(value || "")) return "blue";
  return "default";
}

function Badge({ value }: { value?: string | null }) {
  return <Tag color={color(value)}>{value || "Pending"}</Tag>;
}

function Keys({ values }: { values?: string[] }) {
  return <Space wrap size={[0, 4]}>{values?.length ? values.map((key) => <Tag key={key}>{key}</Tag>) : <Typography.Text type="secondary">—</Typography.Text>}</Space>;
}

function Timestamp({ value }: { value?: string | null }) {
  return <span>{value ? new Date(value).toLocaleString() : "—"}</span>;
}

function failure(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function Pane({ loading, error, empty, children, description, retry }: {
  loading: boolean; error: unknown; empty: boolean; children: React.ReactNode; description: string; retry: () => void;
}) {
  if (loading) return <div className="pane-loading"><Spin /></div>;
  if (error) return <Alert type="error" showIcon message="Unable to load this testing state" description={failure(error)} action={<Button onClick={retry}>Retry</Button>} />;
  if (empty) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />;
  return <>{children}</>;
}

function FindingLifecycle({ finding, onUpdated }: { finding: Finding; onUpdated: (finding: Finding) => void }) {
  const [form] = Form.useForm<{ status: string; reason: string; resolution?: string }>();
  const status = Form.useWatch("status", form);
  const allowed: Record<string, string[]> = {
    NEW: ["TRIAGED"], TRIAGED: ["CONFIRMED", "INVALID"], CONFIRMED: ["RESOLVED"],
    RESOLVED: ["CLOSED", "REOPENED"], CLOSED: ["REOPENED"], REOPENED: ["TRIAGED", "CONFIRMED"], INVALID: [],
  };
  const transition = useMutation({
    mutationFn: (values: { status: string; reason: string; resolution?: string }) => transitionFinding(finding.id, {
      status: values.status, reason: values.reason.trim(),
      resolution: ["RESOLVED", "CLOSED"].includes(values.status) ? values.resolution : undefined,
      expected_row_version: finding.row_version,
    }),
    onSuccess: onUpdated,
  });
  if (!allowed[finding.status]?.length) return null;
  return <>
    <Typography.Title level={4}>Update finding</Typography.Title>
    <Form name={`finding-${finding.id}`} form={form} layout="vertical" initialValues={{ status: allowed[finding.status][0] }} disabled={transition.isPending} onFinish={(values) => transition.mutate(values)}>
      <Form.Item name="status" label="Next status" rules={[{ required: true }]}><Select options={allowed[finding.status].map((value) => ({ value, label: value }))} /></Form.Item>
      {status === "RESOLVED" && <Form.Item name="resolution" label="Resolution" rules={[{ required: true, message: "Choose how this finding was resolved." }]}><Select options={["FIXED", "DUPLICATE", "WONT_FIX", "RISK_ACCEPTED", "NOT_REPRODUCIBLE", "ENVIRONMENT_FIXED", "TEST_FIXED"].map((value) => ({ value, label: value }))} /></Form.Item>}
      <Form.Item name="reason" label="Reason" rules={[{ required: true, whitespace: true, message: "Record the reason for this lifecycle change." }]} extra="Saved in the audit history. Confirmation requires verified supporting evidence."><Input.TextArea rows={3} placeholder="Describe the evidence and reason for this change." /></Form.Item>
      {transition.error && <Alert type="error" showIcon message="Finding was not updated" description={failure(transition.error)} style={{ marginBottom: 16 }} />}
      <Button type="primary" htmlType="submit" loading={transition.isPending}>Update finding</Button>
    </Form>
  </>;
}

export function useRunOperations(runId: string) {
  const client = useQueryClient();
  const [notifications, contextHolder] = message.useMessage();
  const [workspace, setWorkspace] = useState("");
  const [missionSelection, setMissionSelection] = useState<Mission | null>(null);
  const [missionDialog, setMissionDialog] = useState(false);
  const [executionDialog, setExecutionDialog] = useState<"execution" | "cycle" | null>(null);
  const [executionSelection, setExecutionSelection] = useState<TestExecution | null>(null);
  const [evidenceSelection, setEvidenceSelection] = useState<Evidence | null>(null);
  const [findingSelection, setFindingSelection] = useState<Finding | null>(null);
  const [verdictSelection, setVerdictSelection] = useState<Verdict | null>(null);
  const [missionForm] = Form.useForm<{ workspace: string }>();
  const [executionForm] = Form.useForm<ExecutionCreate>();

  useEffect(() => {
    setWorkspace(localStorage.getItem(`hypertest.workspace.${runId}`) || "");
  }, [runId]);

  function rememberWorkspace(value: string) {
    setWorkspace(value);
    localStorage.setItem(`hypertest.workspace.${runId}`, value);
  }

  const applyWorkspace = useCallback((value: string) => {
    setWorkspace(value);
    localStorage.setItem(`hypertest.workspace.${runId}`, value);
    missionForm.setFieldsValue({ workspace: value });
    executionForm.setFieldsValue({ workspace: value });
  }, [runId, missionForm, executionForm]);
  const tasks = useRunJobs(runId, applyWorkspace);
  useEffect(() => {
    if (!workspace && typeof tasks.latestPrepared?.result?.workspace === "string") applyWorkspace(tasks.latestPrepared.result.workspace);
  }, [workspace, tasks.latestPrepared, applyWorkspace]);

  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: getCapabilities, refetchInterval: 5_000 });
  const implementations = useQuery({ queryKey: ["implementations", runId], queryFn: () => getImplementations(runId), refetchInterval: 5_000 });
  const executions = useQuery({ queryKey: ["executions", runId], queryFn: () => getExecutions(runId), refetchInterval: 5_000 });
  const evidence = useQuery({ queryKey: ["evidence", runId], queryFn: () => getEvidence(runId), refetchInterval: 5_000 });
  const findings = useQuery({ queryKey: ["findings", runId], queryFn: () => getFindings(runId), refetchInterval: 5_000 });
  const verdicts = useQuery({ queryKey: ["verdicts", runId], queryFn: () => getVerdicts(runId), refetchInterval: 5_000 });
  const selectedMission = useQuery({ queryKey: ["mission", missionSelection?.id], queryFn: () => getMission(missionSelection!.id), enabled: !!missionSelection, refetchInterval: 3_000 });
  const attempts = useQuery({ queryKey: ["attempts", missionSelection?.id], queryFn: () => getMissionAttempts(missionSelection!.id), enabled: !!missionSelection, refetchInterval: 3_000 });
  const proposals = useQuery({ queryKey: ["proposals", missionSelection?.id], queryFn: () => getMissionProposals(missionSelection!.id), enabled: !!missionSelection, refetchInterval: 3_000 });
  const executionDetail = useQuery({ queryKey: ["execution", executionSelection?.id], queryFn: () => getExecution(executionSelection!.id), enabled: !!executionSelection, refetchInterval: executionSelection && !["COMPLETED", "ERROR", "TIMED_OUT", "CANCELLED"].includes(executionSelection.status) ? 3_000 : false });
  const evidenceContent = useQuery({ queryKey: ["evidence-content", evidenceSelection?.id], queryFn: () => getEvidenceContent(evidenceSelection!.id), enabled: !!evidenceSelection, retry: false });

  async function refresh() {
    await Promise.all([
      ...["run", "requirements", "risks", "test-cases", "coverage", "missions", "implementations", "executions", "evidence", "findings", "verdicts"].map((key) => client.invalidateQueries({ queryKey: [key, runId] })),
      ...["mission", "attempts", "proposals"].map((key) => client.invalidateQueries({ queryKey: [key] })),
    ]);
  }

  const mission = selectedMission.data || missionSelection;
  const missionExecution = useMutation({
    mutationFn: async (values: { workspace: string }) => {
      if (!mission) throw new Error("Select a mission first.");
      rememberWorkspace(values.workspace);
      if (mission.status === "FAILED") await retryMission(mission.id);
      return tasks.submit("EXECUTE_MISSION", { workspace: values.workspace, provider: "codex" }, mission.id);
    },
    onSuccess: () => setMissionDialog(false),
    onSettled: refresh,
  });
  const missionCancellation = useMutation({
    mutationFn: (id: string) => cancelMission(id),
    onSuccess: (result) => { setMissionSelection(result); notifications.info("Mission cancelled."); },
    onSettled: refresh,
  });
  const execution = useMutation({
    mutationFn: (values: ExecutionCreate) => { rememberWorkspace(values.workspace); return tasks.submit("EXECUTE_TESTS", { ...values, purpose: "OFFICIAL" }); },
    onSuccess: () => setExecutionDialog(null),
    onSettled: refresh,
  });
  const gate = useMutation({
    mutationFn: () => tasks.submit("EVALUATE_GATE", { finalize: true }),
    onSettled: refresh,
  });
  const cycle = useMutation({
    mutationFn: (values: ExecutionCreate) => {
      rememberWorkspace(values.workspace);
      return tasks.submit("ADVANCE_RUN", { workspace: values.workspace, backend: values.backend, timeout_seconds: values.timeout_seconds, max_steps: 12 });
    },
    onSuccess: () => setExecutionDialog(null),
    onSettled: refresh,
  });
  const preparation = useMutation({
    mutationFn: (_target: "mission" | "runner") => tasks.submit("PREPARE_WORKSPACE", {}),
  });
  const preparingCheckout = tasks.active.find((job) => job.job_type === "PREPARE_WORKSPACE");


  function openMissionExecution(item: Mission) {
    setMissionSelection(item);
    missionExecution.reset();
    preparation.reset();
    missionForm.setFieldsValue({ workspace });
    setMissionDialog(true);
  }

  const missionActions = (item: Mission) => (
    <Space wrap>
      <Button size="small" onClick={() => { setMissionSelection(item); missionCancellation.reset(); }}>Details</Button>
      {["CREATED", "READY", "RETRYING", "FAILED"].includes(item.status) && (
        <Button size="small" type="primary" disabled={missionExecution.isPending || tasks.busy || !capabilities.data?.agent_providers.includes("codex")} onClick={() => openMissionExecution(item)}>
          {item.status === "FAILED" ? "Retry mission" : "Execute mission"}
        </Button>
      )}
    </Space>
  );

  const implementationColumns = [
    { title: "Implementation", key: "implementation", render: (_: unknown, item: TestImplementation) => <Space direction="vertical" size={1}><Typography.Text strong>{item.file_path}</Typography.Text><span className="entity-key">{item.symbol}</span></Space> },
    { title: "Framework", dataIndex: "framework" },
    { title: "Validation", dataIndex: "validation_status", render: (value: string) => <Badge value={value} /> },
    { title: "Test cases", key: "test-cases", render: (_: unknown, item: TestImplementation) => <Keys values={item.test_case_keys || item.testcase_keys} /> },
    { title: "Commit", dataIndex: "commit_sha", render: (value: string) => <Typography.Text code title={value}>{value.slice(0, 12)}</Typography.Text> },
  ];
  const executionColumns = [
    { title: "Execution", dataIndex: "key", render: (_: unknown, item: TestExecution) => <Button type="link" style={{ padding: 0 }} onClick={() => setExecutionSelection(item)}>{item.key}</Button> },
    { title: "Purpose", dataIndex: "purpose", render: (value: string) => <Tag color={value === "OFFICIAL" ? "blue" : "default"}>{value}</Tag> },
    { title: "Runner", dataIndex: "runner_backend" },
    { title: "Status", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: "Outcome", dataIndex: "outcome", render: (value: string) => <Badge value={value} /> },
    { title: "Exit code", dataIndex: "exit_code", render: (value: number | null) => value ?? "—" },
    { title: "Started", dataIndex: "started_at", render: (value: string) => <Timestamp value={value} /> },
  ];
  const evidenceColumns = [
    { title: "Artifact", dataIndex: "evidence_type", render: (_: unknown, item: Evidence) => <Space direction="vertical" size={1}><Button type="link" style={{ padding: 0 }} onClick={() => setEvidenceSelection(item)}>{item.evidence_type}</Button><span className="entity-key">{item.key}</span></Space> },
    { title: "Trust", dataIndex: "trust_level", render: (value: string) => <Tag color={value === "RUNNER" ? "blue" : "default"}>{value}</Tag> },
    { title: "Status", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: "Size", dataIndex: "size_bytes", render: (value?: number | null) => value == null ? "—" : `${value.toLocaleString()} B` },
    { title: "SHA-256", dataIndex: "sha256", render: (value: string) => <Typography.Text code title={value}>{value.slice(0, 16)}…</Typography.Text> },
  ];
  const findingColumns = [
    { title: "Finding", key: "finding", render: (_: unknown, item: Finding) => <Space direction="vertical" size={1}><Button type="link" style={{ padding: 0 }} onClick={() => setFindingSelection(item)}>{item.title}</Button><span className="entity-key">{item.key}</span></Space> },
    { title: "Classification", dataIndex: "classification" },
    { title: "Severity", dataIndex: "severity", render: (value: string) => <Badge value={value} /> },
    { title: "Status", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: "Evidence", dataIndex: "evidence_keys", render: (values: string[]) => <Keys values={values} /> },
  ];
  const verdictColumns = [
    { title: "Decision", dataIndex: "decision", render: (_: unknown, item: Verdict) => <Button type="link" style={{ padding: 0 }} onClick={() => setVerdictSelection(item)}><Badge value={item.decision} /></Button> },
    { title: "Sequence", dataIndex: "sequence_no" },
    { title: "Status", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: "Reason", dataIndex: "reason", ellipsis: true },
    { title: "Issued", dataIndex: "created_at", render: (value: string) => <Timestamp value={value} /> },
  ];

  const tabs: NonNullable<TabsProps["items"]> = [
    tasks.taskTab,
    { key: "automation", label: `Automation (${implementations.data?.length ?? 0})`, children: <Pane loading={implementations.isLoading} error={implementations.error} empty={!implementations.data?.length} retry={() => void implementations.refetch()} description="No accepted implementations yet. Plan an IMPLEMENT_TESTS mission after test design coverage is complete."><Table rowKey="id" columns={implementationColumns} dataSource={implementations.data} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /></Pane> },
    { key: "executions", label: `Executions (${executions.data?.length ?? 0})`, children: <Pane loading={executions.isLoading} error={executions.error} empty={!executions.data?.length} retry={() => void executions.refetch()} description="No runner executions yet. Implement the test cases, then select Execute tests."><Table rowKey="id" columns={executionColumns} dataSource={executions.data} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} /></Pane> },
    { key: "evidence", label: `Evidence (${evidence.data?.length ?? 0})`, children: <Pane loading={evidence.isLoading} error={evidence.error} empty={!evidence.data?.length} retry={() => void evidence.refetch()} description="Evidence appears here when the trusted runner collects execution metadata, logs and test reports."><Table rowKey="id" columns={evidenceColumns} dataSource={evidence.data} pagination={{ pageSize: 10 }} scroll={{ x: 800 }} /></Pane> },
    { key: "findings", label: `Findings (${findings.data?.length ?? 0})`, children: <Pane loading={findings.isLoading} error={findings.error} empty={!findings.data?.length} retry={() => void findings.refetch()} description="No findings recorded. Failed executions can produce a DIAGNOSE_FAILURE mission with evidence-backed proposals."><Table rowKey="id" columns={findingColumns} dataSource={findings.data} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /></Pane> },
    { key: "verdicts", label: `Verdicts (${verdicts.data?.length ?? 0})`, children: <Pane loading={verdicts.isLoading} error={verdicts.error} empty={!verdicts.data?.length} retry={() => void verdicts.refetch()} description="No quality decisions yet. Evaluate the quality gate to record a verdict from canonical state and verified execution evidence."><Table rowKey="id" columns={verdictColumns} dataSource={verdicts.data} pagination={{ pageSize: 10 }} scroll={{ x: 750 }} /></Pane> },
  ];

  const latestVerdict = verdicts.data?.reduce<Verdict | undefined>((latest, item) => !latest || item.sequence_no > latest.sequence_no ? item : latest, undefined);
  const activeExecutions = executions.data?.filter((item) => ["QUEUED", "PROVISIONING", "RUNNING", "COLLECTING"].includes(item.status)).length || 0;

  function openExecutionDialog(mode: "execution" | "cycle") {
    execution.reset();
    preparation.reset();
    cycle.reset();
    executionForm.setFieldsValue({ workspace, backend: capabilities.data?.runner_backends[0] || "docker", purpose: "OFFICIAL", timeout_seconds: 300 });
    setExecutionDialog(mode);
  }

  const actions = <Space wrap>
    <Button aria-label="Run test cycle" type="primary" disabled={!capabilities.data?.agent_providers.includes("codex") || !capabilities.data.runner_backends.length || missionExecution.isPending || execution.isPending || tasks.busy} loading={cycle.isPending} onClick={() => openExecutionDialog("cycle")}>Run test cycle</Button>
    <Button aria-label="Execute tests" disabled={!implementations.data?.length || !capabilities.data?.runner_backends.length || execution.isPending || tasks.busy} loading={execution.isPending} onClick={() => {
      execution.reset();
      preparation.reset();
      executionForm.setFieldsValue({ workspace, backend: capabilities.data?.runner_backends[0] || "docker", purpose: "OFFICIAL", timeout_seconds: 300 });
      setExecutionDialog("execution");
    }}>Execute tests</Button>
    <Button aria-label="Evaluate quality gate" disabled={tasks.busy} loading={gate.isPending} onClick={() => gate.mutate()}>Evaluate quality gate</Button>
  </Space>;

  const summary = <>
    {tasks.monitor}
    {capabilities.data?.worker?.available === false && <Alert type="warning" showIcon message="No worker heartbeat is available" description={`Queued tasks remain saved until a worker becomes available.${capabilities.data.worker.last_seen_at ? ` Last heartbeat: ${new Date(capabilities.data.worker.last_seen_at).toLocaleString()}.` : " Start the HyperTest worker service to process queued work."}`} style={{ marginBottom: 16 }} />}
    {!executionDialog && cycle.error && <Alert type="error" showIcon message="Unable to save test-cycle task" description={failure(cycle.error)} style={{ marginBottom: 16 }} />}
    {capabilities.error && <Alert type="warning" showIcon message="Runtime capabilities could not be checked" description={failure(capabilities.error)} action={<Button onClick={() => void capabilities.refetch()}>Retry</Button>} style={{ marginBottom: 16 }} />}
    {capabilities.data && (!capabilities.data.agent_providers.includes("codex") || !capabilities.data.runner_backends.length) && <Alert type="warning" showIcon message="Some execution services are unavailable" description={[
      !capabilities.data.agent_providers.includes("codex") ? "Install and authenticate Codex on the HyperTest host to execute missions." : "",
      !capabilities.data.runner_backends.length ? "Configure a trusted Docker runner on the HyperTest host to execute tests." : "",
    ].filter(Boolean).join(" ")} style={{ marginBottom: 16 }} />}
    {gate.error && <Alert closable type="error" showIcon message="Unable to save quality-gate task" description={failure(gate.error)} onClose={() => gate.reset()} style={{ marginBottom: 16 }} />}
    {activeExecutions > 0 && <Alert type="info" showIcon message={`${activeExecutions} runner execution${activeExecutions === 1 ? " is" : "s are"} in progress`} description="Testing state refreshes automatically. Open Executions to inspect progress." style={{ marginBottom: 16 }} />}
    {latestVerdict && <Alert type={["PASS", "RELEASE_READY"].includes(latestVerdict.decision) ? "success" : ["FAIL", "RELEASE_BLOCKED"].includes(latestVerdict.decision) ? "error" : "warning"} showIcon message={<Space>Latest quality verdict <Badge value={latestVerdict.decision} /><Tag>{latestVerdict.status}</Tag></Space>} description={latestVerdict.reason} action={<Button onClick={() => setVerdictSelection(latestVerdict)}>View decision</Button>} style={{ marginBottom: 20 }} />}
  </>;

  const dialogs = <>
    {contextHolder}
    {tasks.dialog}
    <Modal forceRender title={mission?.status === "FAILED" ? "Retry mission" : "Execute mission"} open={missionDialog} okText={mission?.status === "FAILED" ? "Retry and execute" : "Execute mission"} okButtonProps={{ "aria-label": mission?.status === "FAILED" ? "Retry and execute" : "Execute mission", disabled: tasks.busy }} confirmLoading={missionExecution.isPending} cancelText={missionExecution.isPending ? "View progress" : "Cancel"} maskClosable={!missionExecution.isPending} onCancel={() => setMissionDialog(false)} onOk={() => missionForm.submit()}>
      <Typography.Paragraph><strong>{mission?.mission_type}</strong> — {mission?.objective}</Typography.Paragraph>
      <Alert type="info" showIcon message="Codex must be installed and authenticated on the HyperTest host." description="The agent submits proposals. HyperTest verifies them before updating canonical testing state." style={{ marginBottom: 20 }} />
      <Form name="execute-mission" form={missionForm} layout="vertical" onFinish={(values) => missionExecution.mutate(values)}>
        <Form.Item name="workspace" label="Repository workspace" rules={[{ required: true, whitespace: true, message: "Enter the checkout path on the HyperTest host." }]} extra="Absolute path to a checkout matching this run's pinned source commit."><Input placeholder={`${capabilities.data?.workspace_root || "/workspaces"}/my-project`} disabled={missionExecution.isPending || preparation.isPending} /></Form.Item>
        <Button size="small" loading={preparation.isPending} disabled={missionExecution.isPending || tasks.busy} onClick={() => preparation.mutate("mission")} style={{ marginBottom: 20 }}>Prepare pinned checkout</Button>
        {preparingCheckout && <Alert type="info" showIcon message={`Checkout task ${preparingCheckout.status.toLowerCase()}`} description="You can close this dialog. The prepared path is filled in after the worker finishes." style={{ marginBottom: 16 }} />}
        {preparation.error && <Alert type="error" showIcon message="Unable to save checkout task" description={failure(preparation.error)} style={{ marginBottom: 16 }} />}
      </Form>
      {missionExecution.isPending && <Alert type="info" showIcon message="Saving mission task" description="Once accepted, the worker executes this mission independently of the browser." />}
      {missionExecution.error && <Alert type="error" showIcon message="Unable to save mission task" description={failure(missionExecution.error)} />}
    </Modal>

    <Drawer title={mission ? `${mission.key} · ${mission.mission_type}` : "Mission"} open={!!missionSelection && !missionDialog} width={850} onClose={() => setMissionSelection(null)} extra={mission && <Space><Badge value={mission.status} />{["CREATED", "READY", "RETRYING", "FAILED"].includes(mission.status) && <Button type="primary" disabled={missionExecution.isPending || tasks.busy || !capabilities.data?.agent_providers.includes("codex")} onClick={() => openMissionExecution(mission)}>{mission.status === "FAILED" ? "Retry mission" : "Execute mission"}</Button>}{!["COMPLETED", "FAILED", "CANCELLED", "EXPIRED"].includes(mission.status) && <Popconfirm title="Cancel this mission?" description="Unaccepted proposals will not change canonical testing state." onConfirm={() => missionCancellation.mutate(mission.id)}><Button danger loading={missionCancellation.isPending}>Cancel mission</Button></Popconfirm>}</Space>}>
      <Typography.Paragraph>{mission?.objective}</Typography.Paragraph>
      {missionCancellation.error && <Alert type="error" showIcon message="Unable to cancel mission" description={failure(missionCancellation.error)} />}
      <Typography.Title level={4}>Attempts</Typography.Title>
      <Pane loading={attempts.isLoading} error={attempts.error} empty={!attempts.data?.length} retry={() => void attempts.refetch()} description="This mission has not run yet.">
        <Table rowKey="id" size="small" dataSource={attempts.data} pagination={false} columns={[
          { title: "Attempt", dataIndex: "attempt_no", width: 80 },
          { title: "Provider", dataIndex: "provider" },
          { title: "Status", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
          { title: "Error", key: "error", render: (_: unknown, item: { error_code?: string | null; error_message?: string | null }) => item.error_message ? <Typography.Text type="danger">{item.error_code}: {item.error_message}</Typography.Text> : "—" },
        ]} />
      </Pane>
      <Typography.Title level={4}>Proposals</Typography.Title>
      <Pane loading={proposals.isLoading} error={proposals.error} empty={!proposals.data?.length} retry={() => void proposals.refetch()} description="No proposals submitted yet.">
        <Table rowKey="id" size="small" dataSource={proposals.data} pagination={false} columns={[
          { title: "Type", dataIndex: "proposal_type" },
          { title: "Operation", dataIndex: "operation" },
          { title: "Review", dataIndex: "status", render: (value: string) => <Badge value={value} /> },
          { title: "Canonical entity", dataIndex: "accepted_entity_type", render: (value: string) => value || "—" },
        ]} expandable={{ expandedRowRender: (proposal: MissionProposal) => <><pre className="artifact-content">{JSON.stringify(proposal.object_payload, null, 2)}</pre>{!!proposal.validation_errors?.length && <Alert type="error" message="Validation errors" description={<pre className="artifact-content">{JSON.stringify(proposal.validation_errors, null, 2)}</pre>} />}</> }} />
      </Pane>
    </Drawer>

    <Modal forceRender title={executionDialog === "cycle" ? "Run a complete test cycle" : "Run official tests"} open={!!executionDialog} width={640} okText={executionDialog === "cycle" ? "Run test cycle" : "Start execution"} okButtonProps={{ "aria-label": executionDialog === "cycle" ? "Run test cycle" : "Start execution", disabled: tasks.busy }} confirmLoading={execution.isPending || cycle.isPending} cancelText={execution.isPending || cycle.isPending ? "Return to workbench" : "Cancel"} maskClosable={!execution.isPending && !cycle.isPending} onCancel={() => setExecutionDialog(null)} onOk={() => executionForm.submit()}>
      <Typography.Paragraph>{executionDialog === "cycle" ? "HyperTest plans and verifies agent missions, implements tests, runs them through a trusted runner and evaluates the quality gate. Each cycle is limited to 12 planning steps; progress remains available in the workbench." : "HyperTest Runner executes accepted test implementations and collects verifiable evidence."}</Typography.Paragraph>
      <Form name="execute-run" form={executionForm} layout="vertical" onFinish={(values) => executionDialog === "cycle" ? cycle.mutate(values) : execution.mutate({ ...values, purpose: "OFFICIAL" })} disabled={execution.isPending || cycle.isPending}>
        <Form.Item name="workspace" label="Repository workspace" rules={[{ required: true, whitespace: true }]} extra="A checkout of this run's source with the accepted test implementations available."><Input placeholder={`${capabilities.data?.workspace_root || "/workspaces"}/my-project`} /></Form.Item>
        <Button size="small" loading={preparation.isPending} disabled={execution.isPending || cycle.isPending || tasks.busy} onClick={() => preparation.mutate("runner")} style={{ marginBottom: 20 }}>Prepare pinned checkout</Button>
        {preparingCheckout && <Alert type="info" showIcon message={`Checkout task ${preparingCheckout.status.toLowerCase()}`} description="You can close this dialog. The prepared path is filled in after the worker finishes." style={{ marginBottom: 16 }} />}
        {preparation.error && <Alert type="error" showIcon message="Unable to save checkout task" description={failure(preparation.error)} style={{ marginBottom: 16 }} />}
        <Form.Item name="backend" label="Runner" rules={[{ required: true }]}><Select options={capabilities.data?.runner_backends.map((value) => ({ value, label: value === "docker" ? "Docker · isolated execution" : "Local · trusted host process" }))} /></Form.Item>
        <Form.Item name="timeout_seconds" label="Timeout (seconds)" rules={[{ required: true }]}><InputNumber min={1} max={3600} style={{ width: "100%" }} /></Form.Item>
      </Form>
      {cycle.isPending && <Alert type="info" showIcon message="Saving test-cycle task. Once accepted, work continues independently of this browser." />}
      {cycle.error && <Alert type="error" showIcon message="Unable to save test-cycle task" description={failure(cycle.error)} />}
      {execution.isPending && <Alert type="info" showIcon message="Saving official execution task." />}
      {execution.error && <Alert type="error" showIcon message="Unable to save execution task" description={failure(execution.error)} />}
    </Modal>

    <Drawer title={executionSelection?.key || "Execution"} open={!!executionSelection} width={850} onClose={() => setExecutionSelection(null)}>
      {executionDetail.isLoading ? <Spin /> : executionDetail.error ? <Alert type="error" message="Unable to load execution" description={failure(executionDetail.error)} /> : executionDetail.data && <>
        <Descriptions bordered column={2} size="small" items={[
          { key: "status", label: "Status", children: <Badge value={executionDetail.data.execution.status} /> },
          { key: "outcome", label: "Outcome", children: <Badge value={executionDetail.data.execution.outcome} /> },
          { key: "purpose", label: "Purpose", children: executionDetail.data.execution.purpose },
          { key: "runner", label: "Runner", children: executionDetail.data.execution.runner_backend },
          { key: "commit", label: "Source commit", span: 2, children: <Typography.Text code copyable>{executionDetail.data.execution.source_commit}</Typography.Text> },
          { key: "hash", label: "Execution spec SHA-256", span: 2, children: <Typography.Text code copyable>{executionDetail.data.execution.execution_spec_sha256}</Typography.Text> },
          { key: "exit", label: "Exit code", children: executionDetail.data.execution.exit_code ?? "—" },
          { key: "started", label: "Started", children: <Timestamp value={executionDetail.data.execution.started_at} /> },
        ]} />
        {executionDetail.data.execution.error_message && <Alert type="error" showIcon style={{ marginTop: 16 }} message={executionDetail.data.execution.error_code || "Execution error"} description={executionDetail.data.execution.error_message} />}
        <Typography.Title level={4}>Per-case results</Typography.Title>
        <Table rowKey="test_case_id" dataSource={executionDetail.data.test_cases} pagination={false} columns={[
          { title: "Test case", key: "case", render: (_: unknown, item: { test_case_key?: string; test_case_id: string }) => item.test_case_key || item.test_case_id },
          { title: "Result", dataIndex: "result", render: (value: string) => <Badge value={value} /> },
          { title: "Duration", dataIndex: "duration_ms", render: (value: number | null) => value == null ? "—" : `${value} ms` },
          { title: "Failure", dataIndex: "failure_summary" },
        ]} />
        <Typography.Title level={4}>Collected evidence</Typography.Title>
        <Space wrap>{evidence.data?.filter((item) => executionDetail.data?.evidence_keys.includes(item.key)).map((item) => <Button key={item.id} onClick={() => setEvidenceSelection(item)}>{item.evidence_type}</Button>)}</Space>
      </>}
    </Drawer>

    <Drawer title={evidenceSelection ? `${evidenceSelection.evidence_type} · ${evidenceSelection.key}` : "Evidence"} open={!!evidenceSelection} width={900} onClose={() => setEvidenceSelection(null)}>
      {evidenceSelection && <>
        <Space wrap style={{ marginBottom: 16 }}><Badge value={evidenceSelection.status} /><Tag color="blue">{evidenceSelection.trust_level}</Tag><Tag>{evidenceSelection.collector}</Tag></Space>
        <Typography.Paragraph><strong>SHA-256 </strong><Typography.Text code copyable>{evidenceSelection.sha256}</Typography.Text></Typography.Paragraph>
        {evidenceSelection.inline_summary && <Typography.Paragraph>{evidenceSelection.inline_summary}</Typography.Paragraph>}
        {evidenceSelection.rejection_reason && <Alert type="error" message="Evidence rejected" description={evidenceSelection.rejection_reason} />}
        {evidenceContent.isLoading ? <Spin /> : evidenceContent.error ? <Alert type="error" message="Unable to read verified evidence content" description={failure(evidenceContent.error)} /> : <pre className="artifact-content">{evidenceContent.data || "(empty artifact)"}</pre>}
      </>}
    </Drawer>

    <Drawer title={findingSelection?.key || "Finding"} open={!!findingSelection} width={760} onClose={() => setFindingSelection(null)} extra={<Button loading={findings.isFetching} onClick={async () => { const result = await findings.refetch(); const current = result.data?.find((item) => item.id === findingSelection?.id); if (current) setFindingSelection(current); }}>Refresh finding</Button>}>
      {findingSelection && <><Space wrap><Badge value={findingSelection.status} /><Badge value={findingSelection.severity} /><Tag>{findingSelection.classification}</Tag></Space><Typography.Title level={3}>{findingSelection.title}</Typography.Title><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{findingSelection.description}</Typography.Paragraph><Typography.Title level={5}>Root cause</Typography.Title><Typography.Paragraph>{findingSelection.root_cause || "Not diagnosed yet."}</Typography.Paragraph><Typography.Title level={5}>Test cases</Typography.Title><Keys values={findingSelection.test_case_keys || findingSelection.testcase_keys} /><Typography.Title level={5}>Supporting evidence</Typography.Title><Space wrap>{findingSelection.evidence_keys?.map((key) => { const item = evidence.data?.find((entry) => entry.key === key); return item ? <Button key={key} onClick={() => setEvidenceSelection(item)}>{key}</Button> : <Tag key={key}>{key}</Tag>; })}</Space><Typography.Title level={5}>Resolution</Typography.Title><Typography.Paragraph>{findingSelection.resolution || "Unresolved"}</Typography.Paragraph><FindingLifecycle key={`${findingSelection.id}:${findingSelection.row_version}`} finding={findingSelection} onUpdated={(result) => { setFindingSelection(result); notifications.success("Finding lifecycle updated."); void refresh(); }} /></>}
    </Drawer>

    <Drawer title={verdictSelection ? `${verdictSelection.key} · Decision #${verdictSelection.sequence_no}` : "Quality verdict"} open={!!verdictSelection} width={820} onClose={() => setVerdictSelection(null)}>
      {verdictSelection && <><Space wrap><Badge value={verdictSelection.decision} /><Tag>{verdictSelection.status}</Tag><Tag>{verdictSelection.scope}</Tag></Space><Typography.Title level={4}>Decision rationale</Typography.Title><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{verdictSelection.reason}</Typography.Paragraph><Descriptions column={1} bordered size="small" items={[
        { key: "state", label: "Canonical state SHA-256", children: <Typography.Text code copyable>{verdictSelection.state_snapshot_hash}</Typography.Text> },
        { key: "manifest", label: "Evidence manifest SHA-256", children: verdictSelection.evidence_manifest_sha256 ? <Typography.Text code copyable>{verdictSelection.evidence_manifest_sha256}</Typography.Text> : "—" },
        { key: "policy", label: "Policy snapshot", children: <Typography.Text code>{verdictSelection.policy_snapshot_id}</Typography.Text> },
        { key: "issued", label: "Issued", children: <Timestamp value={verdictSelection.created_at} /> },
      ]} /><Typography.Title level={5}>Evidence</Typography.Title><Keys values={verdictSelection.evidence_keys} /><Typography.Title level={5}>Findings</Typography.Title><Keys values={verdictSelection.finding_keys} /></>}
    </Drawer>
  </>;

  return { tabs, actions, dialogs, summary, missionActions, refresh, busy: tasks.busy || cycle.isPending || missionExecution.isPending || execution.isPending };
}
