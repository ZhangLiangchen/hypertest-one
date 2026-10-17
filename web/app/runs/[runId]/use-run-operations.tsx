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
  cancelMission, errorText, getEvidence,
  getEvidenceContent, getExecution, getExecutions, getFindings, getImplementations,
  getCapabilities, getMission, getMissionAttempts, getMissionProposals, getSourceSnapshot, getVerdicts, retryMission, transitionFinding,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useRunJobs } from "./use-run-jobs";
import { AttemptHistory } from "./attempt-history";

import type { Evidence, ExecutionCreate, Finding, Mission, MissionProposal, TestExecution, TestImplementation, Verdict } from "@/lib/types";

function color(value: string | null | undefined) {
  if (["PASS", "RELEASE_READY", "COMPLETED", "ACCEPTED", "VERIFIED", "VALIDATED", "FINAL", "RESOLVED", "CLOSED"].includes(value || "")) return "green";
  if (["FAIL", "FAILED", "ERROR", "TIMED_OUT", "RELEASE_BLOCKED", "REJECTED", "BLOCKER", "CRITICAL"].includes(value || "")) return "red";
  if (["BLOCKED", "INCONCLUSIVE", "RETEST_REQUIRED", "NEW", "REOPENED", "PARTIAL"].includes(value || "")) return "gold";
  if (["RUNNING", "DISPATCHED", "VERIFYING", "COLLECTING", "TRIAGED"].includes(value || "")) return "blue";
  return "default";
}

function Badge({ value }: { value?: string | null }) {
  const { t, label } = useI18n();
  return <Tag title={value || undefined} color={color(value)}>{value ? label(value) : t("Pending", "待处理")}</Tag>;
}

function Keys({ values }: { values?: string[] }) {
  return <Space wrap size={[0, 4]}>{values?.length ? values.map((key) => <Tag key={key}>{key}</Tag>) : <Typography.Text type="secondary">—</Typography.Text>}</Space>;
}

function Timestamp({ value }: { value?: string | null }) {
  const { formatDate } = useI18n();
  return <span>{formatDate(value)}</span>;
}

function Pane({ loading, error, empty, children, description, retry }: {
  loading: boolean; error: unknown; empty: boolean; children: React.ReactNode; description: string; retry: () => void;
}) {
  const { t, locale } = useI18n();
  if (loading) return <div className="pane-loading"><Spin /></div>;
  return <>
    {!!error && <Alert type="warning" showIcon message={t("Testing state could not be refreshed", "测试状态暂时无法刷新")} description={<>{errorText(error, locale)} {t("Previously loaded results remain visible.", "已加载的结果仍会保留。")}</>} action={<Button onClick={retry}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
    {empty ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} /> : children}
  </>;
}

function FindingLifecycle({ finding, onUpdated }: { finding: Finding; onUpdated: (finding: Finding) => void }) {
  const { t, label, locale } = useI18n();
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
    <Typography.Title level={4}>{t("Update finding", "更新发现")}</Typography.Title>
    <Form name={`finding-${finding.id}`} form={form} layout="vertical" initialValues={{ status: allowed[finding.status][0] }} disabled={transition.isPending} onFinish={(values) => transition.mutate(values)}>
      <Form.Item name="status" label={t("Next status", "下一状态")} rules={[{ required: true, message: t("Choose a next status.", "请选择下一状态。") }]}><Select options={allowed[finding.status].map((value) => ({ value, label: label(value) }))} /></Form.Item>
      {status === "RESOLVED" && <Form.Item name="resolution" label={t("Resolution", "解决方式")} rules={[{ required: true, message: t("Choose how this finding was resolved.", "请选择此发现的解决方式。") }]}><Select options={["FIXED", "DUPLICATE", "WONT_FIX", "RISK_ACCEPTED", "NOT_REPRODUCIBLE", "ENVIRONMENT_FIXED", "TEST_FIXED"].map((value) => ({ value, label: label(value) }))} /></Form.Item>}
      <Form.Item name="reason" label={t("Reason", "原因")} rules={[{ required: true, whitespace: true, message: t("Record the reason for this lifecycle change.", "请记录此次生命周期变更的原因。") }]} extra={t("Saved in the audit history. Confirmation requires verified supporting evidence.", "原因会保存在审计历史中。确认发现必须有已验证的证据支持。")}><Input.TextArea rows={3} placeholder={t("Describe the evidence and reason for this change.", "请说明支持此次变更的证据与原因。")} /></Form.Item>
      {transition.error && <Alert type="error" showIcon message={t("Finding was not updated", "发现未能更新")} description={errorText(transition.error, locale)} style={{ marginBottom: 16 }} />}
      <Button type="primary" htmlType="submit" loading={transition.isPending}>{t("Update finding", "更新发现")}</Button>
    </Form>
  </>;
}

type ExecutionFormValues = ExecutionCreate & { source_mode?: "managed" | "existing" };

function supportsManagedCheckout(repository: string | undefined): boolean {
  if (!repository || !/^https:\/\/github\.com\//i.test(repository)) return false;
  try {
    const url = new URL(repository);
    return url.protocol === "https:" && url.hostname === "github.com" && !url.port && !url.username && !url.password && !url.search && !url.hash && /^\/[\w.-]+\/[\w.-]+\/?$/.test(url.pathname);
  } catch { return false; }
}

export function useRunOperations(runId: string, onNavigate: (section: string) => void, sourceId?: string) {
  const { t, label, locale, formatDate, verdictReason } = useI18n();
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
  const [preparationJobId, setPreparationJobId] = useState<string | null>(null);
  const [missionForm] = Form.useForm<{ workspace: string }>();
  const [executionForm] = Form.useForm<ExecutionFormValues>();
  const sourceMode = Form.useWatch("source_mode", executionForm);
  const source = useQuery({ queryKey: ["source-snapshot", sourceId], queryFn: () => getSourceSnapshot(sourceId!), enabled: !!sourceId, staleTime: Infinity });
  const managedCheckout = supportsManagedCheckout(source.data?.repository_url);

  useEffect(() => {
    try { setWorkspace(localStorage.getItem(`hypertest.workspace.${runId}`) || ""); } catch { setWorkspace(""); }
  }, [runId]);

  function rememberWorkspace(value: string) {
    setWorkspace(value);
    try { localStorage.setItem(`hypertest.workspace.${runId}`, value); } catch { /* The current form works without browser storage. */ }
  }

  const applyWorkspace = useCallback((value: string) => {
    setWorkspace(value);
    try { localStorage.setItem(`hypertest.workspace.${runId}`, value); } catch { /* The current form works without browser storage. */ }
    missionForm.setFieldsValue({ workspace: value });
    executionForm.setFieldsValue({ workspace: value });
  }, [runId, missionForm, executionForm]);
  function viewResult(section: string, key?: string) {
    onNavigate(section);
    if (section === "missions" && key) {
      const item = client.getQueryData<Mission[]>(["missions", runId])?.find((entry) => entry.key === key || entry.id === key);
      if (item) setMissionSelection(item);
    }
    if (section === "executions" && key) setExecutionSelection(executions.data?.find((entry) => entry.key === key || entry.id === key) || null);
    if (section === "verdicts" && key) setVerdictSelection(verdicts.data?.find((entry) => entry.key === key || entry.id === key) || null);
  }
  const tasks = useRunJobs(runId, applyWorkspace, viewResult);
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
  const executionDetail = useQuery({ queryKey: ["execution", executionSelection?.id], queryFn: () => getExecution(executionSelection!.id), enabled: !!executionSelection, refetchInterval: (query) => !["COMPLETED", "ERROR", "TIMED_OUT", "CANCELLED"].includes(query.state.data?.execution.status || "") ? 3_000 : false });
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
      if (!mission) throw new Error(t("Select a mission first.", "请先选择测试任务。"));
      rememberWorkspace(values.workspace);
      if (mission.status === "FAILED") await retryMission(mission.id);
      return tasks.submit("EXECUTE_MISSION", { workspace: values.workspace, provider: "codex" }, mission.id);
    },
    onSuccess: () => setMissionDialog(false),
    onSettled: refresh,
  });
  const missionCancellation = useMutation({
    mutationFn: (id: string) => cancelMission(id),
    onSuccess: (result) => { setMissionSelection(result); notifications.info(t("Mission cancelled.", "测试任务已取消。")); },
    onSettled: refresh,
  });
  const execution = useMutation({
    mutationFn: (values: ExecutionCreate) => { rememberWorkspace(values.workspace); return tasks.submit("EXECUTE_TESTS", { workspace: values.workspace, backend: values.backend, timeout_seconds: values.timeout_seconds, purpose: "OFFICIAL" }); },
    onSuccess: () => setExecutionDialog(null),
    onSettled: refresh,
  });
  const gate = useMutation({
    mutationFn: () => tasks.submit("EVALUATE_GATE", { finalize: true }),
    onSettled: refresh,
  });
  const cycle = useMutation({
    mutationFn: (values: ExecutionFormValues) => {
      const automatic = values.source_mode === "managed";
      if (!automatic) rememberWorkspace(values.workspace);
      return tasks.submit("ADVANCE_RUN", { ...(automatic ? { prepare_workspace: true } : { workspace: values.workspace }), backend: values.backend, timeout_seconds: values.timeout_seconds, max_steps: 12 });
    },
    onSuccess: () => setExecutionDialog(null),
    onSettled: refresh,
  });
  const preparation = useMutation({
    mutationFn: (_target: "mission" | "runner") => tasks.submit("PREPARE_WORKSPACE", {}),
    onSuccess: (job) => setPreparationJobId(job.id),
  });
  const preparingCheckout = tasks.active.find((job) => job.job_type === "PREPARE_WORKSPACE");
  const preparationJob = tasks.rows.find((job) => job.id === preparationJobId);
  const preparationFeedback = preparationJob && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(preparationJob.status) ? <Alert type="error" showIcon message={t("Source checkout was not prepared", "源码目录未能准备完成")} description={preparationJob.error_message || t("Review the recorded checkout task before retrying.", "请检查已记录的检出任务后再重试。")} action={<Button onClick={() => { setMissionDialog(false); setExecutionDialog(null); tasks.openTask(preparationJob.id); }}>{t("View checkout task", "查看检出任务")}</Button>} style={{ marginBottom: 16 }} /> : null;


  function openMissionExecution(item: Mission) {
    setMissionSelection(item);
    missionExecution.reset();
    preparation.reset();
    setPreparationJobId(null);
    missionForm.setFieldsValue({ workspace });
    setMissionDialog(true);
  }

  const missionActions = (item: Mission) => (
    <Space wrap>
      <Button size="small" onClick={() => { setMissionSelection(item); missionCancellation.reset(); }}>{t("Details", "详情")}</Button>
      {["CREATED", "READY", "RETRYING", "FAILED"].includes(item.status) && (
        <Button size="small" type="primary" disabled={missionExecution.isPending || tasks.busy || !capabilities.data?.agent_providers.includes("codex")} onClick={() => openMissionExecution(item)}>
          {item.status === "FAILED" ? t("Retry mission", "重试任务") : t("Execute mission", "执行任务")}
        </Button>
      )}
    </Space>
  );

  const implementationColumns = [
    { title: t("Implementation", "自动化实现"), key: "implementation", render: (_: unknown, item: TestImplementation) => <Space direction="vertical" size={1}><Typography.Text strong>{item.file_path}</Typography.Text><span className="entity-key">{item.symbol}</span></Space> },
    { title: t("Framework", "框架"), dataIndex: "framework" },
    { title: t("Validation", "验证状态"), dataIndex: "validation_status", render: (value: string) => <Badge value={value} /> },
    { title: t("Test cases", "测试用例"), key: "test-cases", render: (_: unknown, item: TestImplementation) => <Keys values={item.test_case_keys || item.testcase_keys} /> },
    { title: t("Commit", "提交"), dataIndex: "commit_sha", render: (value: string) => <Typography.Text code title={value}>{value.slice(0, 12)}</Typography.Text> },
  ];
  const executionColumns = [
    { title: t("Execution", "执行"), dataIndex: "key", render: (_: unknown, item: TestExecution) => <Button type="link" style={{ padding: 0 }} onClick={() => setExecutionSelection(item)}>{item.key}</Button> },
    { title: t("Purpose", "用途"), dataIndex: "purpose", render: (value: string) => <Tag color={value === "OFFICIAL" ? "blue" : "default"}>{label(value)}</Tag> },
    { title: t("Runner", "Runner"), dataIndex: "runner_backend" },
    { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: t("Outcome", "执行结果"), dataIndex: "outcome", render: (value: string) => <Badge value={value} /> },
    { title: t("Exit code", "退出码"), dataIndex: "exit_code", render: (value: number | null) => value ?? "—" },
    { title: t("Started", "开始时间"), dataIndex: "started_at", render: (value: string) => <Timestamp value={value} /> },
  ];
  const evidenceColumns = [
    { title: t("Artifact", "产物"), dataIndex: "evidence_type", render: (_: unknown, item: Evidence) => <Space direction="vertical" size={1}><Button type="link" style={{ padding: 0 }} onClick={() => setEvidenceSelection(item)}>{label(item.evidence_type)}</Button><span className="entity-key">{item.key}</span></Space> },
    { title: t("Trust", "信任来源"), dataIndex: "trust_level", render: (value: string) => <Tag color={value === "RUNNER" ? "blue" : "default"}>{label(value)}</Tag> },
    { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: t("Size", "大小"), dataIndex: "size_bytes", render: (value?: number | null) => value == null ? "—" : `${value.toLocaleString(locale === "zh" ? "zh-CN" : "en-US")} B` },
    { title: "SHA-256", dataIndex: "sha256", render: (value: string) => <Typography.Text code title={value}>{value.slice(0, 16)}…</Typography.Text> },
  ];
  const findingColumns = [
    { title: t("Finding", "发现"), key: "finding", render: (_: unknown, item: Finding) => <Space direction="vertical" size={1}><Button type="link" style={{ padding: 0 }} onClick={() => setFindingSelection(item)}>{item.title}</Button><span className="entity-key">{item.key}</span></Space> },
    { title: t("Classification", "分类"), dataIndex: "classification", render: (value: string) => label(value) },
    { title: t("Severity", "严重程度"), dataIndex: "severity", render: (value: string) => <Badge value={value} /> },
    { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: t("Evidence", "证据"), dataIndex: "evidence_keys", render: (values: string[]) => <Keys values={values} /> },
  ];
  const verdictColumns = [
    { title: t("Decision", "质量判定"), dataIndex: "decision", render: (_: unknown, item: Verdict) => <Button type="link" style={{ padding: 0 }} onClick={() => setVerdictSelection(item)}><Badge value={item.decision} /></Button> },
    { title: t("Sequence", "序号"), dataIndex: "sequence_no" },
    { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Badge value={value} /> },
    { title: t("Reason", "原因"), dataIndex: "reason", ellipsis: true, render: (value: string) => verdictReason(value) },
    { title: t("Issued", "签发时间"), dataIndex: "created_at", render: (value: string) => <Timestamp value={value} /> },
  ];

  const tabs: NonNullable<TabsProps["items"]> = [
    tasks.taskTab,
    { key: "automation", label: `${t("Automation", "自动化实现")} (${implementations.data?.length ?? 0})`, children: <Pane loading={implementations.isLoading} error={implementations.error} empty={!implementations.data?.length} retry={() => void implementations.refetch()} description={t("No accepted implementations yet. Plan an IMPLEMENT_TESTS mission after test design coverage is complete.", "暂无已接受的自动化实现。测试设计覆盖完成后，可规划实现测试任务（IMPLEMENT_TESTS）。")}><Table rowKey="id" columns={implementationColumns} dataSource={implementations.data} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /></Pane> },
    { key: "executions", label: `${t("Executions", "执行")} (${executions.data?.length ?? 0})`, children: <Pane loading={executions.isLoading} error={executions.error} empty={!executions.data?.length} retry={() => void executions.refetch()} description={t("No runner executions yet. Implement the test cases, then select Execute tests.", "暂无 Runner 执行。完成用例实现后，选择“执行测试”。")}><Table rowKey="id" columns={executionColumns} dataSource={executions.data} pagination={{ pageSize: 10 }} scroll={{ x: 900 }} /></Pane> },
    { key: "evidence", label: `${t("Evidence", "证据")} (${evidence.data?.length ?? 0})`, children: <Pane loading={evidence.isLoading} error={evidence.error} empty={!evidence.data?.length} retry={() => void evidence.refetch()} description={t("Evidence appears here when the trusted runner collects execution metadata, logs and test reports.", "可信 Runner 收集执行元数据、日志与测试报告后，证据将显示在这里。")}><Table rowKey="id" columns={evidenceColumns} dataSource={evidence.data} pagination={{ pageSize: 10 }} scroll={{ x: 800 }} /></Pane> },
    { key: "findings", label: `${t("Findings", "发现")} (${findings.data?.length ?? 0})`, children: <Pane loading={findings.isLoading} error={findings.error} empty={!findings.data?.length} retry={() => void findings.refetch()} description={t("No findings recorded. Failed executions can produce a DIAGNOSE_FAILURE mission with evidence-backed proposals.", "暂无发现。失败执行可触发失败诊断任务（DIAGNOSE_FAILURE），生成有证据支持的提议。")}><Table rowKey="id" columns={findingColumns} dataSource={findings.data} pagination={{ pageSize: 10 }} scroll={{ x: 850 }} /></Pane> },
    { key: "verdicts", label: `${t("Verdicts", "质量判定")} (${verdicts.data?.length ?? 0})`, children: <Pane loading={verdicts.isLoading} error={verdicts.error} empty={!verdicts.data?.length} retry={() => void verdicts.refetch()} description={t("No quality decisions yet. Evaluate the quality gate to record a verdict from canonical state and verified execution evidence.", "暂无质量判定。评估质量门禁后，平台会依据正式状态和已验证的执行证据记录判定。")}><Table rowKey="id" columns={verdictColumns} dataSource={verdicts.data} pagination={{ pageSize: 10 }} scroll={{ x: 750 }} /></Pane> },
  ];

  const latestVerdict = verdicts.data?.reduce<Verdict | undefined>((latest, item) => !latest || item.sequence_no > latest.sequence_no ? item : latest, undefined);
  const activeExecutions = executions.data?.filter((item) => ["QUEUED", "PROVISIONING", "RUNNING", "COLLECTING"].includes(item.status)).length || 0;

  function openExecutionDialog(mode: "execution" | "cycle") {
    execution.reset();
    preparation.reset();
    cycle.reset();
    setPreparationJobId(null);
    executionForm.setFieldsValue({ workspace, source_mode: mode === "cycle" && managedCheckout && !workspace ? "managed" : "existing", backend: capabilities.data?.runner_backends[0] || "docker", purpose: "OFFICIAL", timeout_seconds: 300 });
    setExecutionDialog(mode);
  }

  const actions = <Space wrap>
    <Button aria-label={t("Run test cycle", "运行完整测试周期")} type="primary" disabled={source.isLoading || !!source.error || !capabilities.data?.agent_providers.includes("codex") || !capabilities.data.runner_backends.length || missionExecution.isPending || execution.isPending || tasks.busy} loading={cycle.isPending} onClick={() => openExecutionDialog("cycle")}>{t("Run test cycle", "运行完整测试周期")}</Button>
    <Button aria-label={t("Execute tests", "执行测试")} disabled={!implementations.data?.length || !capabilities.data?.runner_backends.length || execution.isPending || tasks.busy} loading={execution.isPending} onClick={() => {
      openExecutionDialog("execution");
    }}>{t("Execute tests", "执行测试")}</Button>
    <Button aria-label={t("Evaluate quality gate", "评估质量门禁")} disabled={tasks.busy} loading={gate.isPending} onClick={() => gate.mutate()}>{t("Evaluate quality gate", "评估质量门禁")}</Button>
  </Space>;

  const summary = <>
    {tasks.monitor}
    {source.error && <Alert type="error" showIcon message={t("Unable to read pinned source", "无法读取固定源码输入")} description={errorText(source.error, locale)} action={<Button onClick={() => void source.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
    {!tasks.rows.length && !executions.data?.length && !latestVerdict && <Alert type="info" showIcon message={t("Inputs saved. Start a complete test cycle.", "输入已保存，下一步运行完整测试周期。")} description={t("HyperTest will analyze requirements, identify risks, design and implement tests, run Docker and produce an evidence-backed verdict. GitHub sources can be prepared automatically; other sources use a checkout on the Worker host.", "HyperTest 会分析需求、识别风险、设计和实现测试，再通过 Docker 执行并形成有证据支持的质量判定。GitHub 来源可自动准备源码；其他来源使用 Worker 主机上的检出目录。")} style={{ marginBottom: 16 }} />}
    {capabilities.data?.worker?.available === false && <Alert type="warning" showIcon message={t("No worker heartbeat is available", "未检测到 Worker 心跳")} description={<>{t("Queued tasks stay saved until a worker becomes available.", "排队任务会持久保存，等待 Worker 恢复。")}{capabilities.data.worker.last_seen_at ? ` ${t("Last heartbeat", "最近心跳")}: ${formatDate(capabilities.data.worker.last_seen_at)}` : t(" Start the HyperTest worker service to process queued work.", " 请启动 HyperTest Worker 服务以处理任务。")}</>} style={{ marginBottom: 16 }} />}
    {!executionDialog && cycle.error && <Alert type="error" showIcon message={t("Unable to save test-cycle task", "无法保存测试周期任务")} description={errorText(cycle.error, locale)} style={{ marginBottom: 16 }} />}
    {capabilities.error && <Alert type="warning" showIcon message={t("Runtime capabilities could not be checked", "无法检查运行能力")} description={errorText(capabilities.error, locale)} action={<Button onClick={() => void capabilities.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
    {capabilities.data && (!capabilities.data.agent_providers.includes("codex") || !capabilities.data.runner_backends.length) && <Alert type="warning" showIcon message={t("Some execution services are unavailable", "部分执行服务暂不可用")} description={[
      !capabilities.data.agent_providers.includes("codex") ? t("Install and authenticate Codex on the HyperTest host to execute missions.", "请在 HyperTest 主机上安装并认证 Codex，以执行智能体任务。") : "",
      !capabilities.data.runner_backends.length ? t("Configure a trusted Docker runner on the HyperTest host to execute tests.", "请在 HyperTest 主机上配置可信 Docker Runner，以执行测试。") : "",
    ].filter(Boolean).join(" ")} style={{ marginBottom: 16 }} />}
    {gate.error && <Alert closable type="error" showIcon message={t("Unable to save quality-gate task", "无法保存质量门禁任务")} description={errorText(gate.error, locale)} onClose={() => gate.reset()} style={{ marginBottom: 16 }} />}
    {activeExecutions > 0 && <Alert type="info" showIcon message={t(`${activeExecutions} runner execution(s) in progress`, `${activeExecutions} 个 Runner 正在执行`)} description={t("Testing state refreshes automatically. Open Executions to inspect progress.", "测试状态会自动刷新。打开“执行”页签查看进度。")} style={{ marginBottom: 16 }} />}
    {latestVerdict && <Alert type={["PASS", "RELEASE_READY"].includes(latestVerdict.decision) ? "success" : ["FAIL", "RELEASE_BLOCKED"].includes(latestVerdict.decision) ? "error" : "warning"} showIcon message={<Space>{t("Latest quality verdict", "最新质量判定")} <Badge value={latestVerdict.decision} /><Tag>{label(latestVerdict.status)}</Tag></Space>} description={<span style={{ whiteSpace: "pre-wrap" }}>{verdictReason(latestVerdict.reason)}</span>} action={<Button onClick={() => setVerdictSelection(latestVerdict)}>{t("View decision", "查看判定")}</Button>} style={{ marginBottom: 20 }} />}
  </>;

  const dialogs = <>
    {contextHolder}
    {tasks.dialog}
    <Modal forceRender title={mission?.status === "FAILED" ? t("Retry mission", "重试任务") : t("Execute mission", "执行任务")} open={missionDialog} okText={mission?.status === "FAILED" ? t("Retry and execute", "重试并执行") : t("Execute mission", "执行任务")} okButtonProps={{ "aria-label": mission?.status === "FAILED" ? t("Retry and execute", "重试并执行") : t("Execute mission", "执行任务"), disabled: tasks.busy }} confirmLoading={missionExecution.isPending} cancelText={missionExecution.isPending ? t("View progress", "查看进度") : t("Cancel", "取消")} maskClosable={!missionExecution.isPending} onCancel={() => setMissionDialog(false)} onOk={() => missionForm.submit()}>
      <Typography.Paragraph><strong>{mission ? label(mission.mission_type) : ""}</strong> — {mission?.objective}</Typography.Paragraph>
      <Alert type="info" showIcon message={t("Codex must be installed and authenticated on the HyperTest host.", "HyperTest 主机必须已安装并认证 Codex。")} description={t("The agent submits proposals. HyperTest verifies them before updating canonical testing state.", "智能体提交提议，由 HyperTest 验证后更新正式测试状态。")} style={{ marginBottom: 20 }} />
      <Form name="execute-mission" form={missionForm} layout="vertical" onFinish={(values) => missionExecution.mutate(values)}>
        <Form.Item name="workspace" label={t("Repository workspace", "仓库工作目录")} rules={[{ required: true, whitespace: true, message: t("Enter the checkout path on the HyperTest host.", "请输入 HyperTest 主机上的检出目录绝对路径。") }]} extra={t("Absolute path to a checkout matching this run's pinned source commit.", "目录必须匹配本次运行固定的源码提交，填写主机上的绝对路径。")}><Input placeholder={`${capabilities.data?.workspace_root || "/workspaces"}/my-project`} disabled={missionExecution.isPending || preparation.isPending} /></Form.Item>
        <Button size="small" loading={preparation.isPending} disabled={!managedCheckout || missionExecution.isPending || tasks.busy} onClick={() => preparation.mutate("mission")} style={{ marginBottom: 20 }}>{t("Prepare pinned checkout", "准备固定版本目录")}</Button>
        {preparingCheckout && <Alert type="info" showIcon message={`${t("Checkout task", "检出任务")} · ${label(preparingCheckout.status)}`} description={t("You can close this dialog. The prepared path is filled in after the worker finishes.", "可关闭此对话框。Worker 完成准备后会自动填入目录路径。")} style={{ marginBottom: 16 }} />}
        {preparation.error && <Alert type="error" showIcon message={t("Unable to save checkout task", "无法保存检出任务")} description={errorText(preparation.error, locale)} style={{ marginBottom: 16 }} />}
        {preparationFeedback}
      </Form>
      {missionExecution.isPending && <Alert type="info" showIcon message={t("Saving mission task", "正在保存智能体任务")} description={t("Once accepted, the worker executes this mission independently of the browser.", "任务保存后，由 Worker 独立执行，关闭浏览器不会中止。")} />}
      {missionExecution.error && <Alert type="error" showIcon message={t("Unable to save mission task", "无法保存智能体任务")} description={errorText(missionExecution.error, locale)} />}
    </Modal>

    <Drawer title={mission ? `${mission.key} · ${label(mission.mission_type)}` : t("Mission", "测试任务")} open={!!missionSelection && !missionDialog} width={850} onClose={() => setMissionSelection(null)} extra={mission && <Space><Badge value={mission.status} />{["CREATED", "READY", "RETRYING", "FAILED"].includes(mission.status) && <Button type="primary" disabled={missionExecution.isPending || tasks.busy || !capabilities.data?.agent_providers.includes("codex")} onClick={() => openMissionExecution(mission)}>{mission.status === "FAILED" ? t("Retry mission", "重试任务") : t("Execute mission", "执行任务")}</Button>}{!["COMPLETED", "FAILED", "CANCELLED", "EXPIRED"].includes(mission.status) && <Popconfirm title={t("Cancel this mission?", "确认取消此测试任务？")} description={t("Unaccepted proposals will not change canonical testing state.", "尚未接受的提议不会改变正式测试状态。")} onConfirm={() => missionCancellation.mutate(mission.id)}><Button danger loading={missionCancellation.isPending}>{t("Cancel mission", "取消测试任务")}</Button></Popconfirm>}</Space>}>
      <Typography.Paragraph>{mission?.objective}</Typography.Paragraph>
      {missionCancellation.error && <Alert type="error" showIcon message={t("Unable to cancel mission", "无法取消测试任务")} description={errorText(missionCancellation.error, locale)} />}
      <Typography.Title level={4}>{t("Attempts", "尝试历史")}</Typography.Title>
      <Pane loading={attempts.isLoading} error={attempts.error} empty={!attempts.data?.length} retry={() => void attempts.refetch()} description={t("This mission has not run yet.", "此测试任务尚未执行。")}>
        <AttemptHistory attempts={attempts.data || []} />
      </Pane>
      <Typography.Title level={4}>{t("Proposals", "提议")}</Typography.Title><Typography.Paragraph className="muted">{t("Expand a proposal to inspect the original agent output and validation errors. Only accepted proposals enter canonical testing state.", "展开提议可查看智能体原始产出与验证错误。只有被接受的提议才会进入正式测试状态。")}</Typography.Paragraph>
      <Pane loading={proposals.isLoading} error={proposals.error} empty={!proposals.data?.length} retry={() => void proposals.refetch()} description={t("No proposals submitted yet.", "尚未提交提议。")}>
        <Table rowKey="id" size="small" dataSource={proposals.data} pagination={false} columns={[
          { title: t("Type", "类型"), dataIndex: "proposal_type", render: (value: string) => label(value) },
          { title: t("Operation", "操作"), dataIndex: "operation", render: (value: string) => label(value) },
          { title: t("Review", "审核状态"), dataIndex: "status", render: (value: string) => <Badge value={value} /> },
          { title: t("Canonical entity", "正式实体"), key: "accepted-entity", render: (_: unknown, proposal: MissionProposal) => proposal.accepted_entity_id ? <Space direction="vertical" size={1}><span>{label(proposal.accepted_entity_type)}</span><Typography.Text code copyable>{proposal.accepted_entity_id}</Typography.Text></Space> : "—" },
        ]} expandable={{ expandedRowRender: (proposal: MissionProposal) => <><pre className="artifact-content">{JSON.stringify(proposal.object_payload, null, 2)}</pre>{!!proposal.validation_errors?.length && <Alert type="error" message={t("Validation errors", "验证错误")} description={<pre className="artifact-content">{JSON.stringify(proposal.validation_errors, null, 2)}</pre>} />}</> }} />
      </Pane>
    </Drawer>

    <Modal forceRender title={executionDialog === "cycle" ? t("Run a complete test cycle", "运行完整测试周期") : t("Run official tests", "运行正式测试")} open={!!executionDialog} width={640} okText={executionDialog === "cycle" ? t("Run test cycle", "运行完整测试周期") : t("Start execution", "开始执行")} okButtonProps={{ "aria-label": executionDialog === "cycle" ? t("Run test cycle", "运行完整测试周期") : t("Start execution", "开始执行"), disabled: tasks.busy }} confirmLoading={execution.isPending || cycle.isPending} cancelText={execution.isPending || cycle.isPending ? t("Return to workbench", "返回工作台") : t("Cancel", "取消")} maskClosable={!execution.isPending && !cycle.isPending} onCancel={() => setExecutionDialog(null)} onOk={() => executionForm.submit()}>
      <Typography.Paragraph>{executionDialog === "cycle" ? t("HyperTest plans and verifies agent missions, implements tests, runs them through a trusted runner and evaluates the quality gate. Each cycle is limited to 12 planning steps; progress remains available in the workbench.", "HyperTest 规划并验证智能体任务、生成测试实现、通过可信 Runner 执行测试，最后评估质量门禁。每次最多推进 12 个步骤，进度持续保存在工作台。") : t("HyperTest Runner executes accepted test implementations and collects verifiable evidence.", "HyperTest Runner 执行已接受的测试实现，并收集可验证的证据。")}</Typography.Paragraph>
      <Alert type="info" showIcon message={t("Current Runner support: Python / pytest", "当前 Runner 支持 Python / pytest")} description={t("The default image includes the standard library and pytest. Application dependencies require an operator-prepared trusted image; execution has no network access.", "默认镜像包含标准库和 pytest。应用依赖需要运维预置在可信镜像中；正式执行时没有网络访问。")} style={{ marginBottom: 16 }} />
      <Form name="execute-run" form={executionForm} layout="vertical" onFinish={(values) => executionDialog === "cycle" ? cycle.mutate(values) : execution.mutate({ ...values, purpose: "OFFICIAL" })} disabled={execution.isPending || cycle.isPending}>
        {executionDialog === "cycle" && <Form.Item name="source_mode" label={t("Source preparation", "源码准备方式")}><Select options={[
          ...(managedCheckout ? [{ value: "managed", label: t("Prepare pinned source and run automatically", "自动准备固定源码并运行") }] : []),
          { value: "existing", label: t("Use a checkout on the Worker host", "使用 Worker 主机已有检出目录") },
        ]} /></Form.Item>}
        {executionDialog === "cycle" && sourceMode === "managed" ? <Alert type="info" showIcon message={t("One durable task prepares source and runs the cycle", "同一后台任务会准备源码并继续完整周期")} description={<>{t("The Worker checks out the immutable commit first, then runs agent missions, Docker execution and the quality gate. Closing this page does not stop the saved task.", "Worker 会先检出不可变提交，再推进智能体任务、Docker 执行和质量判定。关闭页面不会停止已保存任务。")}<br /><Typography.Text code>{source.data?.commit_sha}</Typography.Text></>} style={{ marginBottom: 20 }} /> : <>
        <Form.Item name="workspace" label={t("Repository workspace", "仓库工作目录")} rules={[{ required: true, whitespace: true, message: t("Enter the checkout path on the HyperTest host.", "请输入 HyperTest 主机上的检出目录绝对路径。") }]} extra={t("Absolute path on the Worker host. Its HEAD and git remote get-url origin must match this run's pinned source. A browser-local directory is not uploaded.", "填写 Worker 主机上的绝对路径；其 HEAD 和 git remote get-url origin 必须匹配本次固定源码。浏览器本机目录不会自动上传。")}><Input placeholder={`${capabilities.data?.workspace_root || "/workspaces"}/my-project`} /></Form.Item>
        <Button size="small" loading={preparation.isPending} disabled={!managedCheckout || execution.isPending || cycle.isPending || tasks.busy} onClick={() => preparation.mutate("runner")} style={{ marginBottom: 20 }}>{t("Prepare pinned checkout", "准备固定版本目录")}</Button>
        {!managedCheckout && <Typography.Paragraph type="secondary">{t("Automatic preparation supports GitHub HTTPS origins. Other sources need an existing checkout matching this run's commit and origin.", "自动准备支持 GitHub HTTPS 来源。其他来源需使用与本次固定提交和 origin 匹配的已有检出目录。")}</Typography.Paragraph>}
        {preparingCheckout && <Alert type="info" showIcon message={`${t("Checkout task", "检出任务")} · ${label(preparingCheckout.status)}`} description={t("You can close this dialog. The prepared path is filled in after the worker finishes.", "可关闭此对话框。Worker 完成准备后会自动填入目录路径。")} style={{ marginBottom: 16 }} />}
        {preparation.error && <Alert type="error" showIcon message={t("Unable to save checkout task", "无法保存检出任务")} description={errorText(preparation.error, locale)} style={{ marginBottom: 16 }} />}
        {preparationFeedback}
        </>}
        <Form.Item name="backend" label={t("Runner", "Runner")} rules={[{ required: true, message: t("Choose an available runner.", "请选择可用的 Runner。") }]}><Select options={capabilities.data?.runner_backends.map((value) => ({ value, label: value === "docker" ? t("Docker · isolated execution", "Docker · 隔离执行") : t("Local · trusted host process", "本机 · 可信主机进程") }))} /></Form.Item>
        <Form.Item name="timeout_seconds" label={t("Runner timeout (seconds)", "Runner 超时（秒）")} extra={t("Applies to each Runner execution. Agent mission time limits are configured by the operator.", "此限制适用于每次 Runner 执行。智能体任务的超时由运维配置。 ")} rules={[{ required: true, type: "number", min: 1, max: 3600, message: t("Enter a timeout between 1 and 3600 seconds.", "请输入 1 至 3600 秒的超时限制。") }]}><InputNumber min={1} max={3600} style={{ width: "100%" }} /></Form.Item>
      </Form>
      {cycle.isPending && <Alert type="info" showIcon message={t("Saving test-cycle task. Once accepted, work continues independently of this browser.", "正在保存测试周期任务。任务保存后会独立于浏览器继续执行。")} />}
      {cycle.error && <Alert type="error" showIcon message={t("Unable to save test-cycle task", "无法保存测试周期任务")} description={errorText(cycle.error, locale)} />}
      {execution.isPending && <Alert type="info" showIcon message={t("Saving official execution task.", "正在保存正式执行任务。")} />}
      {execution.error && <Alert type="error" showIcon message={t("Unable to save execution task", "无法保存执行任务")} description={errorText(execution.error, locale)} />}
    </Modal>

    <Drawer title={executionSelection?.key || t("Execution", "执行")} open={!!executionSelection} width={850} onClose={() => setExecutionSelection(null)}>
      {executionDetail.isLoading ? <Spin /> : executionDetail.error && !executionDetail.data ? <Alert type="error" message={t("Unable to load execution", "无法加载执行详情")} description={errorText(executionDetail.error, locale)} action={<Button onClick={() => void executionDetail.refetch()}>{t("Retry", "重试")}</Button>} /> : executionDetail.data && <>
        {executionDetail.error && <Alert type="warning" showIcon message={t("Execution refresh failed; showing recorded results", "执行刷新失败，正在显示已加载结果")} description={errorText(executionDetail.error, locale)} action={<Button onClick={() => void executionDetail.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
        <Descriptions bordered column={2} size="small" items={[
          { key: "status", label: t("Status", "状态"), children: <Badge value={executionDetail.data.execution.status} /> },
          { key: "outcome", label: t("Outcome", "执行结果"), children: <Badge value={executionDetail.data.execution.outcome} /> },
          { key: "purpose", label: t("Purpose", "用途"), children: label(executionDetail.data.execution.purpose) },
          { key: "runner", label: t("Runner", "Runner"), children: executionDetail.data.execution.runner_backend },
          { key: "commit", label: t("Source commit", "源码提交"), span: 2, children: <Typography.Text code copyable>{executionDetail.data.execution.source_commit}</Typography.Text> },
          { key: "hash", label: t("Execution spec SHA-256", "执行规格 SHA-256"), span: 2, children: <Typography.Text code copyable>{executionDetail.data.execution.execution_spec_sha256}</Typography.Text> },
          { key: "exit", label: t("Exit code", "退出码"), children: executionDetail.data.execution.exit_code ?? "—" },
          { key: "started", label: t("Started", "开始时间"), children: <Timestamp value={executionDetail.data.execution.started_at} /> },
        ]} />
        {executionDetail.data.execution.error_message && <Alert type="error" showIcon style={{ marginTop: 16 }} message={executionDetail.data.execution.error_code || t("Execution error", "执行错误")} description={executionDetail.data.execution.error_message} />}
        <Typography.Title level={4}>{t("Per-case results", "各正式用例结果")}</Typography.Title>
        <Typography.Paragraph className="muted">{t("These are canonical test-case results aggregated from accepted implementations. A parameterized test can produce a different number of JUnit instances; inspect the verified report below for individual assertions.", "此处按已接受的测试实现汇总正式用例结果。参数化测试的 JUnit 实例数可能与正式用例数不同，具体断言请查看下方已验证的测试报告。")}</Typography.Paragraph>
        <Table rowKey="test_case_id" dataSource={executionDetail.data.test_cases} pagination={false} columns={[
          { title: t("Test case", "测试用例"), key: "case", render: (_: unknown, item: { test_case_key?: string; test_case_id: string }) => item.test_case_key || item.test_case_id },
          { title: t("Result", "结果"), dataIndex: "result", render: (value: string) => <Badge value={value} /> },
          { title: t("Duration", "耗时"), dataIndex: "duration_ms", render: (value: number | null) => value == null ? "—" : `${value} ms` },
          { title: t("Failure", "失败摘要"), dataIndex: "failure_summary" },
        ]} />
        <Typography.Title level={4}>{t("Collected evidence", "已收集证据")}</Typography.Title>
        <Space wrap>{evidence.data?.filter((item) => executionDetail.data?.evidence_keys.includes(item.key)).map((item) => <Button key={item.id} onClick={() => setEvidenceSelection(item)}>{label(item.evidence_type)}</Button>)}</Space>
      </>}
    </Drawer>

    <Drawer title={evidenceSelection ? `${label(evidenceSelection.evidence_type)} · ${evidenceSelection.key}` : t("Evidence", "证据")} open={!!evidenceSelection} width={900} onClose={() => setEvidenceSelection(null)}>
      {evidenceSelection && <>
        <Space wrap style={{ marginBottom: 16 }}><Badge value={evidenceSelection.status} /><Tag color="blue">{label(evidenceSelection.trust_level)}</Tag><Tag>{evidenceSelection.collector}</Tag></Space>
        <Typography.Paragraph><strong>SHA-256 </strong><Typography.Text code copyable>{evidenceSelection.sha256}</Typography.Text></Typography.Paragraph>
        <Descriptions size="small" column={2} items={[{ key: "size", label: t("Size", "大小"), children: evidenceSelection.size_bytes == null ? "—" : `${evidenceSelection.size_bytes.toLocaleString(locale === "zh" ? "zh-CN" : "en-US")} B` }, { key: "content", label: t("Content type", "内容类型"), children: evidenceSelection.content_type || "—" }]} />
        {evidenceSelection.inline_summary && <Typography.Paragraph>{evidenceSelection.inline_summary}</Typography.Paragraph>}
        {evidenceSelection.rejection_reason && <Alert type="error" message={t("Evidence rejected", "证据已被拒绝")} description={evidenceSelection.rejection_reason} />}
        {evidenceContent.isLoading ? <Spin /> : evidenceContent.error ? <Alert type="error" message={t("Unable to read verified evidence content", "无法读取已验证的证据内容")} description={errorText(evidenceContent.error, locale)} action={<Button onClick={() => void evidenceContent.refetch()}>{t("Retry", "重试")}</Button>} /> : <pre className="artifact-content">{evidenceContent.data || t("(empty artifact)", "（空产物）")}</pre>}
      </>}
    </Drawer>

    <Drawer title={findingSelection?.key || t("Finding", "发现")} open={!!findingSelection} width={760} onClose={() => setFindingSelection(null)} extra={<Button loading={findings.isFetching} onClick={async () => { const result = await findings.refetch(); const current = result.data?.find((item) => item.id === findingSelection?.id); if (current) setFindingSelection(current); }}>{t("Refresh finding", "刷新发现")}</Button>}>
      {findingSelection && <><Space wrap><Badge value={findingSelection.status} /><Badge value={findingSelection.severity} /><Tag>{label(findingSelection.classification)}</Tag></Space><Typography.Title level={3}>{findingSelection.title}</Typography.Title><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{findingSelection.description}</Typography.Paragraph><Typography.Title level={5}>{t("Root cause", "根因")}</Typography.Title><Typography.Paragraph>{findingSelection.root_cause || t("Not diagnosed yet.", "尚未诊断。")}</Typography.Paragraph><Typography.Title level={5}>{t("Test cases", "测试用例")}</Typography.Title><Keys values={findingSelection.test_case_keys || findingSelection.testcase_keys} /><Typography.Title level={5}>{t("Supporting evidence", "支持证据")}</Typography.Title><Space wrap>{findingSelection.evidence_keys?.map((key) => { const item = evidence.data?.find((entry) => entry.key === key); return item ? <Button key={key} onClick={() => setEvidenceSelection(item)}>{key}</Button> : <Tag key={key}>{key}</Tag>; })}</Space><Typography.Title level={5}>{t("Resolution", "解决方式")}</Typography.Title><Typography.Paragraph>{findingSelection.resolution ? label(findingSelection.resolution) : t("Unresolved", "尚未解决")}</Typography.Paragraph><FindingLifecycle key={`${findingSelection.id}:${findingSelection.row_version}`} finding={findingSelection} onUpdated={(result) => { setFindingSelection(result); notifications.success(t("Finding lifecycle updated.", "发现生命周期已更新。")); void refresh(); }} /></>}
    </Drawer>

    <Drawer title={verdictSelection ? `${verdictSelection.key} · ${t("Decision", "质量判定")} #${verdictSelection.sequence_no}` : t("Quality verdict", "质量判定")} open={!!verdictSelection} width={820} onClose={() => setVerdictSelection(null)}>
      {verdictSelection && <><Space wrap><Badge value={verdictSelection.decision} /><Tag>{label(verdictSelection.status)}</Tag><Tag>{label(verdictSelection.scope)}</Tag></Space><Typography.Title level={4}>{t("Decision rationale", "判定依据")}</Typography.Title><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{verdictReason(verdictSelection.reason)}</Typography.Paragraph>{locale === "zh" && verdictReason(verdictSelection.reason) !== verdictSelection.reason && <details style={{ marginBottom: 16 }}><summary style={{ cursor: "pointer" }}>查看判定记录原文</summary><pre className="artifact-content">{verdictSelection.reason}</pre></details>}<Descriptions column={1} bordered size="small" items={[
        { key: "state", label: t("Canonical state SHA-256", "正式状态 SHA-256"), children: <Typography.Text code copyable>{verdictSelection.state_snapshot_hash}</Typography.Text> },
        { key: "manifest", label: t("Evidence manifest SHA-256", "证据清单 SHA-256"), children: verdictSelection.evidence_manifest_sha256 ? <Typography.Text code copyable>{verdictSelection.evidence_manifest_sha256}</Typography.Text> : "—" },
        { key: "policy", label: t("Policy snapshot", "策略快照"), children: <Typography.Text code>{verdictSelection.policy_snapshot_id}</Typography.Text> },
        { key: "issued", label: t("Issued", "签发时间"), children: <Timestamp value={verdictSelection.created_at} /> },
      ]} /><Typography.Title level={5}>{t("Evidence", "证据")}</Typography.Title><Space wrap>{verdictSelection.evidence_keys?.map((key) => { const item = evidence.data?.find((entry) => entry.key === key); return item ? <Button key={key} onClick={() => setEvidenceSelection(item)}>{key}</Button> : <Tag key={key}>{key}</Tag>; })}</Space><Typography.Title level={5}>{t("Findings", "发现")}</Typography.Title><Space wrap>{verdictSelection.finding_keys?.map((key) => { const item = findings.data?.find((entry) => entry.key === key); return item ? <Button key={key} onClick={() => setFindingSelection(item)}>{key}</Button> : <Tag key={key}>{key}</Tag>; })}</Space></>}
    </Drawer>
  </>;

  return { tabs, actions, dialogs, summary, missionActions, refresh, busy: tasks.busy || cycle.isPending || missionExecution.isPending || execution.isPending };
}
