"use client";

import {
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Grid,
  Progress,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

import { errorText, getCoverage, getMissions, getRequirements, getRisks, getRun, getTestCases, planNext } from "@/lib/api";
import type { Mission, Requirement, Risk, TestCase } from "@/lib/types";

import { useRunOperations } from "./use-run-operations";
import { RunInputs } from "./run-inputs";
import { RunHarness } from "./run-harness";
import { CanonicalDetailsDrawer } from "./canonical-details";
import type { CanonicalSelection } from "./canonical-details";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";

function statusColor(status: string) {
  if (["COMPLETED", "ACCEPTED", "ACTIVE", "OPEN"].includes(status)) return "green";
  if (["FAILED", "REJECTED", "BLOCKED"].includes(status)) return "red";
  if (["RUNNING", "ANALYZING", "VERIFYING"].includes(status)) return "blue";
  if (status === "WAITING_INPUT") return "gold";
  return "default";
}

function severityColor(severity: string) {
  if (severity === "CRITICAL") return "red";
  if (severity === "HIGH") return "volcano";
  if (severity === "MEDIUM") return "gold";
  return "blue";
}

function coveragePercent(ratio: number | null) {
  return ratio === null ? null : Math.round(ratio * 100);
}

export default function RunPage() {
  const params = useParams<{ runId: string }>();
  const screens = Grid.useBreakpoint();
  const tabRoot = useRef<HTMLDivElement>(null);
  const { t, label, locale } = useI18n();
  const [activeTab, setActiveTab] = useState("overview");
  const [canonicalSelection, setCanonicalSelection] = useState<CanonicalSelection | null>(null);
  useEffect(() => {
    try { setActiveTab(sessionStorage.getItem(`hypertest.run-tab.${params.runId}`) || "overview"); }
    catch { /* Tab selection still survives polling and language changes without storage. */ }
  }, [params.runId]);
  function selectTab(key: string) {
    // Move focus out of the old panel before Ant Design hides it.
    if (document.activeElement instanceof HTMLElement && tabRoot.current?.contains(document.activeElement)) document.activeElement.blur();
    setActiveTab(key);
    requestAnimationFrame(() => tabRoot.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus());
    try { sessionStorage.setItem(`hypertest.run-tab.${params.runId}`, key); } catch { /* Storage is optional. */ }
  }
  const [messageApi, contextHolder] = message.useMessage();
  const run = useQuery({
    queryKey: ["run", params.runId],
    queryFn: () => getRun(params.runId),
    refetchInterval: 5_000,
  });
  const operations = useRunOperations(params.runId, selectTab, run.data?.source_snapshot_id, run.data?.project_id, setCanonicalSelection);
  const requirements = useQuery({
    queryKey: ["requirements", params.runId],
    queryFn: () => getRequirements(params.runId),
    refetchInterval: 5_000,
  });
  const risks = useQuery({
    queryKey: ["risks", params.runId],
    queryFn: () => getRisks(params.runId),
    refetchInterval: 5_000,
  });
  const testCases = useQuery({
    queryKey: ["test-cases", params.runId],
    queryFn: () => getTestCases(params.runId),
    refetchInterval: 5_000,
  });
  const coverage = useQuery({
    queryKey: ["coverage", params.runId],
    queryFn: () => getCoverage(params.runId),
    refetchInterval: 5_000,
  });
  const missions = useQuery({
    queryKey: ["missions", params.runId],
    queryFn: () => getMissions(params.runId),
    refetchInterval: 5_000,
  });
  const planner = useMutation({
    mutationFn: () => planNext(params.runId),
    onSuccess: async (result) => {
      if (result.mission) {
        messageApi.success(`${t("Planned", "已规划")} ${label(result.mission.mission_type)}: ${result.mission.key}`);
      } else {
        messageApi.info(`${t("Planner", "规划器")}: ${label(result.reason)}`);
      }
      await operations.refresh();
    },
    onError: (error) => messageApi.error(errorText(error, locale)),
  });

  const loading = run.isLoading || requirements.isLoading || risks.isLoading || testCases.isLoading || coverage.isLoading || missions.isLoading;
  const error = run.error || requirements.error || risks.error || testCases.error || coverage.error || missions.error;
  const retryState = () => { void operations.refresh(); };
  if (!run.data && loading) return <WorkspaceLoading label={t("Loading test run", "正在加载测试运行")} />;
  if (!run.data) {
    return <Alert type="error" showIcon message={t("Unable to load test run", "无法加载测试运行")} description={errorText(error, locale)} action={<Button onClick={retryState}>{t("Retry", "重试")}</Button>} />;
  }

  const requirementData = requirements.data || [];
  const riskData = risks.data || [];
  const testCaseData = testCases.data || [];
  const missionData = missions.data || [];
  const coverageData = coverage.data;
  const coverageByRisk = new Map(coverageData?.risks.map((risk) => [risk.risk_id, risk]));
  const covered = new Set(
    riskData.filter((risk) => coverageByRisk.has(risk.id)).flatMap((risk) => risk.requirement_keys),
  );
  const riskIdentification = coveragePercent(coverageData?.risk_identification_coverage ?? null);
  const riskTestCoverage = coveragePercent(coverageData?.risk_test_coverage ?? null);

  const requirementColumns = [
    {
      title: t("Requirement", "需求"),
      dataIndex: "title",
      render: (_: unknown, row: Requirement) => (
        <Space direction="vertical" size={1}>
          <Button type="link" style={{ padding: 0, height: "auto", whiteSpace: "normal", textAlign: "start" }} onClick={() => setCanonicalSelection({ kind: "requirement", id: row.id })}>{row.title}</Button>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: t("Priority", "优先级"), dataIndex: "priority", width: 90, render: (value: string) => <Tag>{label(value)}</Tag> },
    { title: t("Type", "类型"), dataIndex: "requirement_type", width: 150, render: (value: string) => label(value) },
    {
      title: t("Risk", "风险"),
      key: "risk",
      width: 110,
      render: (_: unknown, row: Requirement) =>
        covered.has(row.key) ? <Tag color="green">{t("covered", "已覆盖")}</Tag> : <Tag color="gold">{t("gap", "缺口")}</Tag>,
    },
  ];

  const riskColumns = [
    {
      title: t("Risk", "风险"),
      dataIndex: "title",
      render: (_: unknown, row: Risk) => (
        <Space direction="vertical" size={1}>
          <Button type="link" style={{ padding: 0, height: "auto", whiteSpace: "normal", textAlign: "start" }} onClick={() => setCanonicalSelection({ kind: "risk", id: row.id })}>{row.title}</Button>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: t("Category", "类别"), dataIndex: "category", width: 140, render: (value: string) => label(value) },
    {
      title: t("Severity", "严重程度"),
      dataIndex: "severity",
      width: 110,
      render: (value: string) => <Tag color={severityColor(value)}>{label(value)}</Tag>,
    },
    {
      title: t("Requirements", "需求"),
      dataIndex: "requirement_keys",
      render: (keys: string[]) => <Space wrap>{keys.map((key) => <Tag key={key}>{key}</Tag>)}</Space>,
    },
    {
      title: t("Test coverage", "测试覆盖"),
      key: "test-coverage",
      render: (_: unknown, row: Risk) => {
        const assessment = coverageByRisk.get(row.id);
        if (!assessment) return <Tag>{t("Not assessed", "尚未评估")}</Tag>;
        return (
          <Space direction="vertical" size={4}>
            <Tag color={assessment.complete ? "green" : "gold"}>
              {assessment.complete ? t("Complete", "完整") : t("Gap", "缺口")}
            </Tag>
            {assessment.required_dimensions.length > 0 && (
              <Space wrap size={[0, 4]}>
                {assessment.required_dimensions.map((dimension) => (
                  <Tag key={dimension} color={assessment.covered_dimensions.includes(dimension) ? "green" : "gold"}>
                    {label(dimension)}
                  </Tag>
                ))}
              </Space>
            )}
          </Space>
        );
      },
    },
  ];

  const testCaseColumns = [
    {
      title: t("Test case", "测试用例"),
      dataIndex: "title",
      render: (_: unknown, row: TestCase) => (
        <Space direction="vertical" size={1}>
          <Button type="link" style={{ padding: 0, height: "auto", whiteSpace: "normal", textAlign: "start" }} onClick={() => setCanonicalSelection({ kind: "testCase", id: row.id })}>{row.title}</Button>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: t("Type", "类型"), dataIndex: "test_type", render: (value: string) => <Tag color="blue">{label(value)}</Tag> },
    { title: t("Priority", "优先级"), dataIndex: "priority", width: 90, render: (value: string) => <Tag>{label(value)}</Tag> },
    {
      title: t("Lifecycle", "生命周期"),
      dataIndex: "lifecycle_status",
      render: (value: string) => <Tag color={statusColor(value)}>{label(value)}</Tag>,
    },
    {
      title: t("Risks", "风险"),
      dataIndex: "risk_keys",
      render: (keys: string[]) => <Space wrap>{keys.map((key) => <Tag key={key}>{key}</Tag>)}</Space>,
    },
  ];

  const missionColumns = [
    {
      title: t("Mission", "测试任务"),
      dataIndex: "mission_type",
      render: (_: unknown, row: Mission) => (
        <Space direction="vertical" size={1}>
          <Typography.Text strong>{label(row.mission_type)}</Typography.Text>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: t("Priority", "优先级"), dataIndex: "priority", width: 90 },
    {
      title: t("Status", "状态"),
      dataIndex: "status",
      width: 130,
      render: (value: string) => <Tag color={statusColor(value)}>{label(value)}</Tag>,
    },
    { title: t("Attempts", "尝试次数"), dataIndex: "current_attempt_no", width: 90 },
    { title: t("Objective", "目标"), dataIndex: "objective" },
    { title: t("Actions", "操作"), key: "actions", render: (_: unknown, row: Mission) => operations.missionActions(row) },
  ];

  return (
    <main className="workspace-page">
      {contextHolder}
      <WorkspaceHeading backHref={`/projects/${run.data.project_id}`} backLabel={t("Project", "项目")}
        title={t("Test run", "测试运行")}
        metadata={<><Tag color={run.data.status === "COMPLETED" ? undefined : statusColor(run.data.status)}>{label(run.data.status)}</Tag><Typography.Text code copyable>{run.data.key}</Typography.Text><span className="entity-key">{t("Snapshot", "快照")} {run.data.source_snapshot_id}</span></>}
        actions={<div className="workbench-actions">
            {operations.actions}
            <details className="secondary-actions">
              <summary>{t("More actions", "更多操作")}</summary>
              <div className="secondary-action-list">
                {operations.manualMissionControl && <Button icon={<PlayCircleOutlined aria-hidden />} loading={planner.isPending} disabled={operations.busy} onClick={() => planner.mutate()}>{t("Plan next mission", "规划下一任务")}</Button>}
                {operations.secondaryActions}
                <RunInputs sourceId={run.data.source_snapshot_id} policyId={run.data.policy_snapshot_id} />
              </div>
            </details>
          </div>} />

      <section className="coverage-strip" aria-label={t("Test design coverage", "测试设计覆盖")}>
        <dl className="asset-counts">
          <div><dt>{t("Requirements", "需求")}</dt><dd>{coverageData?.requirement_count ?? (requirements.data ? requirementData.length : "—")}</dd></div>
          <div><dt>{t("Risks", "风险")}</dt><dd>{coverageData?.risk_count ?? (risks.data ? riskData.length : "—")}</dd></div>
          <div><dt>{t("Test cases", "测试用例")}</dt><dd>{coverageData?.test_case_count ?? (testCases.data ? testCaseData.length : "—")}</dd></div>
        </dl>
        <div className="coverage-measure"><span>{t("Risk identification", "风险识别覆盖")}<strong>{riskIdentification === null ? t("Unknown", "未知") : `${riskIdentification}%`}</strong></span><Progress percent={riskIdentification ?? 0} size="small" showInfo={false} strokeColor="var(--ht-accent)" /></div>
        <div className="coverage-measure"><span>{t("Test design coverage", "测试设计覆盖")}<strong>{riskTestCoverage === null ? t("Unknown", "未知") : `${riskTestCoverage}%`}</strong></span><Progress percent={riskTestCoverage ?? 0} size="small" showInfo={false} strokeColor="var(--ht-info)" /></div>
      </section>
      {coverageData?.rule_version && <details className="coverage-rules"><summary>{t("Coverage policy & integrity", "覆盖策略与完整性")}</summary><div style={{overflowWrap: "anywhere", paddingTop: 12}}>
        <Space wrap><Typography.Text className="muted">{t("Coverage rules", "覆盖规则")}</Typography.Text><Tag>{coverageData.rule_version}</Tag></Space>
        {coverageData.effective_policy_hash && <div style={{ marginTop: 6 }}><Typography.Text className="muted">{t("Effective policy SHA-256 ", "生效策略 SHA-256 ")}</Typography.Text><Typography.Text code copyable>{coverageData.effective_policy_hash}</Typography.Text></div>}
      </div></details>}

      {error && <Alert type="warning" showIcon message={t("Some testing state could not be refreshed", "部分测试状态暂时无法刷新")} description={<>{errorText(error, locale)} {t("Previously loaded data stays visible. Retry to get the latest state.", "已加载的数据仍会保留。请重试获取最新状态。")}</>} action={<Button onClick={retryState}>{t("Refresh", "刷新")}</Button>} style={{ marginBottom: 20 }} />}

      <div className="workbench-surface" ref={tabRoot}>
        <Tabs
          tabPosition={screens.lg ? "left" : "top"}
          animated={false}
          tabBarGutter={4}
          activeKey={activeTab}
          onChange={selectTab}
          items={[
            {key: "overview", label: t("Overview", "运行概览"), children: <>{operations.overview}{operations.summary}</>},
            ...operations.tabs.filter((tab) => tab.key !== "automation"),
            { key: "harness", label: t("Session & reports", "持续会话与报告"), children: <RunHarness runId={params.runId} projectId={run.data.project_id} refreshRun={operations.refresh} selectTab={selectTab} openTask={operations.openTask} /> },
            {
              key: "requirements",
              label: `${t("Requirements", "需求")} (${requirements.data ? requirementData.length : "—"})`,
              children: <Table rowKey="id" loading={requirements.isLoading} columns={requirementColumns} dataSource={requirementData} locale={{ emptyText: t("No requirements yet. Run a test cycle or plan the requirement analysis mission.", "暂无需求。请运行完整测试周期，或规划需求分析任务。") }} pagination={false} scroll={{ x: 650 }} expandable={{ expandedRowRender: (requirement) => <div className="entity-detail"><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{requirement.description}</Typography.Paragraph><Space wrap><Tag title={requirement.lifecycle_status}>{label(requirement.lifecycle_status)}</Tag><Tag title={requirement.source_type}>{label(requirement.source_type)}</Tag>{requirement.source_ref && <Typography.Text code>{requirement.source_ref}</Typography.Text>}</Space></div> }} />,
            },
            {
              key: "risks",
              label: `${t("Risks", "风险")} (${risks.data ? riskData.length : "—"})`,
              children: (
                <Table
                  rowKey="id"
                  columns={riskColumns}
                  loading={risks.isLoading}
                  locale={{ emptyText: t("No risks yet. Analyze the requirements to identify risks.", "暂无风险。分析需求后可识别风险。") }}
                  dataSource={riskData}
                  pagination={false}
                  scroll={{ x: 850 }}
                  expandable={{
                    expandedRowRender: (risk) => {
                      const assessment = coverageByRisk.get(risk.id);
                      return (
                        <div className="entity-detail">
                          <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{risk.description}</Typography.Paragraph>{risk.rationale && <Typography.Paragraph>{risk.rationale}</Typography.Paragraph>}
                          {assessment && (
                            <Space direction="vertical">
                              <span><strong>{t("Required dimensions: ", "所需维度：")}</strong>{assessment.required_dimensions.map(label).join(", ") || t("None", "无")}</span>
                              <span><strong>{t("Covered dimensions: ", "已覆盖维度：")}</strong>{assessment.covered_dimensions.map(label).join(", ") || t("None", "无")}</span>
                              <span><strong>{t("Missing dimensions: ", "缺失维度：")}</strong>{assessment.missing_dimensions.map(label).join(", ") || t("None", "无")}</span>
                            </Space>
                          )}
                        </div>
                      );
                    },
                  }}
                />
              ),
            },
            {
              key: "test-cases",
              label: `${t("Test Cases", "测试用例")} (${testCases.data ? testCaseData.length : "—"})`,
              children: (
                <Table
                  rowKey="id"
                  columns={testCaseColumns}
                  loading={testCases.isLoading}
                  locale={{ emptyText: t("No test cases yet. Design tests for the identified risks.", "暂无测试用例。识别风险后可设计用例。") }}
                  dataSource={testCaseData}
                  pagination={false}
                  scroll={{ x: 750 }}
                  expandable={{
                    expandedRowRender: (testCase) => (
                      <div className="entity-detail">
                        <Typography.Paragraph>{testCase.description}</Typography.Paragraph>
                        <Typography.Text strong>{t("Preconditions", "前置条件")}</Typography.Text>
                        {testCase.preconditions.length ? (
                          <ul>{testCase.preconditions.map((condition, index) => <li key={index}>{condition}</li>)}</ul>
                        ) : <Typography.Paragraph className="muted">{t("None", "无")}</Typography.Paragraph>}
                        <Typography.Text strong>{t("Expected result", "预期结果")}</Typography.Text>
                        <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{testCase.expected_result}</Typography.Paragraph>
                      </div>
                    ),
                  }}
                />
              ),
            },
            {
              key: "missions",
              label: `${t("Missions", "测试任务")} (${missions.data ? missionData.length : "—"})`,
              children: <Table rowKey="id" columns={missionColumns} dataSource={missionData} loading={missions.isLoading} locale={{ emptyText: t("No missions yet. Start a test cycle or plan the next mission.", "暂无测试任务。请运行完整测试周期，或规划下一任务。") }} pagination={false} scroll={{ x: 800 }} />,
            },
            ...operations.tabs.filter((tab) => tab.key === "automation"),
          ]}
        />
      </div>
      {operations.dialogs}
      <CanonicalDetailsDrawer runId={params.runId} selection={canonicalSelection} requirements={requirementData} risks={riskData} testCases={testCaseData} implementations={operations.implementations.data || []} onSelect={setCanonicalSelection} onClose={() => setCanonicalSelection(null)} />
    </main>
  );
}
