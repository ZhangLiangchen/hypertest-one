"use client";

import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  FileProtectOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import Link from "next/link";

import { getCoverage, getMissions, getRequirements, getRisks, getRun, getTestCases, planNext } from "@/lib/api";
import type { Mission, Requirement, Risk, TestCase } from "@/lib/types";

import { useRunOperations } from "./use-run-operations";
import { RunInputs } from "./run-inputs";

function statusColor(status: string) {
  if (["COMPLETED", "ACCEPTED", "ACTIVE", "OPEN"].includes(status)) return "green";
  if (["FAILED", "REJECTED", "BLOCKED"].includes(status)) return "red";
  if (["RUNNING", "ANALYZING", "VERIFYING"].includes(status)) return "blue";
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

export default function RunPage({ params }: { params: { runId: string } }) {
  const operations = useRunOperations(params.runId);
  const [messageApi, contextHolder] = message.useMessage();
  const run = useQuery({
    queryKey: ["run", params.runId],
    queryFn: () => getRun(params.runId),
    refetchInterval: 5_000,
  });
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
        messageApi.success(`Planned ${result.mission.mission_type}: ${result.mission.key}`);
      } else {
        messageApi.info(`Planner: ${result.reason}`);
      }
      await operations.refresh();
    },
    onError: (error) => messageApi.error(String(error)),
  });

  const loading = run.isLoading || requirements.isLoading || risks.isLoading || testCases.isLoading || coverage.isLoading || missions.isLoading;
  const error = run.error || requirements.error || risks.error || testCases.error || coverage.error || missions.error;
  if (loading) return <Spin size="large" />;
  if (error || !run.data) {
    return <Alert type="error" showIcon message="Unable to load test run" description={String(error)} />;
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
      title: "Requirement",
      dataIndex: "title",
      render: (_: unknown, row: Requirement) => (
        <Space direction="vertical" size={1}>
          <Typography.Text strong>{row.title}</Typography.Text>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: "Priority", dataIndex: "priority", width: 90, render: (value: string) => <Tag>{value}</Tag> },
    { title: "Type", dataIndex: "requirement_type", width: 150 },
    {
      title: "Risk",
      key: "risk",
      width: 110,
      render: (_: unknown, row: Requirement) =>
        covered.has(row.key) ? <Tag color="green">covered</Tag> : <Tag color="gold">gap</Tag>,
    },
  ];

  const riskColumns = [
    {
      title: "Risk",
      dataIndex: "title",
      render: (_: unknown, row: Risk) => (
        <Space direction="vertical" size={1}>
          <Typography.Text strong>{row.title}</Typography.Text>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: "Category", dataIndex: "category", width: 140 },
    {
      title: "Severity",
      dataIndex: "severity",
      width: 110,
      render: (value: string) => <Tag color={severityColor(value)}>{value}</Tag>,
    },
    {
      title: "Requirements",
      dataIndex: "requirement_keys",
      render: (keys: string[]) => <Space wrap>{keys.map((key) => <Tag key={key}>{key}</Tag>)}</Space>,
    },
    {
      title: "Test coverage",
      key: "test-coverage",
      render: (_: unknown, row: Risk) => {
        const assessment = coverageByRisk.get(row.id);
        if (!assessment) return <Tag>Not assessed</Tag>;
        return (
          <Space direction="vertical" size={4}>
            <Tag color={assessment.complete ? "green" : "gold"}>
              {assessment.complete ? "Complete" : "Gap"}
            </Tag>
            {assessment.required_dimensions.length > 0 && (
              <Space wrap size={[0, 4]}>
                {assessment.required_dimensions.map((dimension) => (
                  <Tag key={dimension} color={assessment.covered_dimensions.includes(dimension) ? "green" : "gold"}>
                    {dimension}
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
      title: "Test case",
      dataIndex: "title",
      render: (_: unknown, row: TestCase) => (
        <Space direction="vertical" size={1}>
          <Typography.Text strong>{row.title}</Typography.Text>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: "Type", dataIndex: "test_type", render: (value: string) => <Tag color="blue">{value}</Tag> },
    { title: "Priority", dataIndex: "priority", width: 90, render: (value: string) => <Tag>{value}</Tag> },
    {
      title: "Lifecycle",
      dataIndex: "lifecycle_status",
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    {
      title: "Risks",
      dataIndex: "risk_keys",
      render: (keys: string[]) => <Space wrap>{keys.map((key) => <Tag key={key}>{key}</Tag>)}</Space>,
    },
  ];

  const missionColumns = [
    {
      title: "Mission",
      dataIndex: "mission_type",
      render: (_: unknown, row: Mission) => (
        <Space direction="vertical" size={1}>
          <Typography.Text strong>{row.mission_type}</Typography.Text>
          <span className="entity-key">{row.key}</span>
        </Space>
      ),
    },
    { title: "Priority", dataIndex: "priority", width: 90 },
    {
      title: "Status",
      dataIndex: "status",
      width: 130,
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: "Attempts", dataIndex: "current_attempt_no", width: 90 },
    { title: "Objective", dataIndex: "objective" },
    { title: "Actions", key: "actions", render: (_: unknown, row: Mission) => operations.missionActions(row) },
  ];

  return (
    <main>
      {contextHolder}
      <div className="page-heading">
        <Link href={`/projects/${run.data.project_id}`}><ArrowLeftOutlined /> Project</Link>
        <div className="workbench-heading">
          <div>
            <div className="eyebrow">Test Run</div>
            <Typography.Title level={1} style={{ margin: 0 }}>{run.data.key}</Typography.Title>
            <Space wrap style={{ marginTop: 10 }}>
              <Tag color={statusColor(run.data.status)}>{run.data.status}</Tag>
              <span className="entity-key">snapshot {run.data.source_snapshot_id}</span>
            </Space>
          </div>
          <Space wrap>
            <Button
              type="primary"
              icon={<PlayCircleOutlined aria-hidden />}
              loading={planner.isPending}
              disabled={operations.busy}
              onClick={() => planner.mutate()}
            >
              Plan next mission
            </Button>
            {operations.actions}
            <RunInputs sourceId={run.data.source_snapshot_id} policyId={run.data.policy_snapshot_id} />
          </Space>
        </div>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} lg={8}>
          <Card className="metric-card"><Statistic title="Requirement count" value={coverageData?.requirement_count ?? requirementData.length} prefix={<CheckCircleOutlined />} /></Card>
        </Col>
        <Col xs={12} lg={8}>
          <Card className="metric-card"><Statistic title="Risk count" value={coverageData?.risk_count ?? riskData.length} prefix={<SafetyCertificateOutlined />} /></Card>
        </Col>
        <Col xs={12} lg={8}>
          <Card className="metric-card"><Statistic title="TestCase count" value={coverageData?.test_case_count ?? testCaseData.length} prefix={<FileProtectOutlined />} /></Card>
        </Col>
        <Col xs={24} md={12}>
          <Card className="metric-card">
            <Statistic title="Risk identification coverage" value={riskIdentification ?? "—"} suffix={riskIdentification === null ? undefined : "%"} />
            <Progress percent={riskIdentification ?? 0} size="small" showInfo={false} />
            <Typography.Text className="muted">
              {riskIdentification === null ? "No active requirements to assess." : "Requirements linked to identified risks."}
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card className="metric-card">
            <Statistic title="Risk test coverage" value={riskTestCoverage ?? "—"} suffix={riskTestCoverage === null ? undefined : "%"} />
            <Progress percent={riskTestCoverage ?? 0} size="small" showInfo={false} />
            <Typography.Text className="muted">
              {riskTestCoverage === null ? "No active risks to assess." : "Risks meeting their required test design dimensions."}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      {coverageData?.risk_identification_coverage === 1 && coverageData.risk_test_coverage === 1 && (
        <Alert
          type="success"
          showIcon
          message="Test design coverage complete"
          description="All current risks meet the required test design dimensions."
          style={{ marginBottom: 20 }}
        />
      )}

      {operations.summary}

      <Card className="section-card">
        <Tabs
          items={[
            {
              key: "requirements",
              label: `Requirements (${requirementData.length})`,
              children: <Table rowKey="id" columns={requirementColumns} dataSource={requirementData} pagination={false} scroll={{ x: 650 }} />,
            },
            {
              key: "risks",
              label: `Risks (${riskData.length})`,
              children: (
                <Table
                  rowKey="id"
                  columns={riskColumns}
                  dataSource={riskData}
                  pagination={false}
                  scroll={{ x: 850 }}
                  expandable={{
                    expandedRowRender: (risk) => {
                      const assessment = coverageByRisk.get(risk.id);
                      return (
                        <div className="entity-detail">
                          <Typography.Paragraph>{risk.description}</Typography.Paragraph>
                          {assessment && (
                            <Space direction="vertical">
                              <span><strong>Required dimensions: </strong>{assessment.required_dimensions.join(", ") || "None"}</span>
                              <span><strong>Covered dimensions: </strong>{assessment.covered_dimensions.join(", ") || "None"}</span>
                              <span><strong>Missing dimensions: </strong>{assessment.missing_dimensions.join(", ") || "None"}</span>
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
              label: `Test Cases (${testCaseData.length})`,
              children: (
                <Table
                  rowKey="id"
                  columns={testCaseColumns}
                  dataSource={testCaseData}
                  pagination={false}
                  scroll={{ x: 750 }}
                  expandable={{
                    expandedRowRender: (testCase) => (
                      <div className="entity-detail">
                        <Typography.Paragraph>{testCase.description}</Typography.Paragraph>
                        <Typography.Text strong>Preconditions</Typography.Text>
                        {testCase.preconditions.length ? (
                          <ul>{testCase.preconditions.map((condition, index) => <li key={index}>{condition}</li>)}</ul>
                        ) : <Typography.Paragraph className="muted">None</Typography.Paragraph>}
                        <Typography.Text strong>Expected result</Typography.Text>
                        <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{testCase.expected_result}</Typography.Paragraph>
                      </div>
                    ),
                  }}
                />
              ),
            },
            {
              key: "missions",
              label: `Missions (${missionData.length})`,
              children: <Table rowKey="id" columns={missionColumns} dataSource={missionData} pagination={false} scroll={{ x: 800 }} />,
            },
            ...operations.tabs,
          ]}
        />
      </Card>
      {operations.dialogs}
    </main>
  );
}
