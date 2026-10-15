"use client";

import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  DeploymentUnitOutlined,
  PlayCircleOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

import { getMissions, getRequirements, getRisks, getRun, planNext } from "@/lib/api";
import type { Mission, Requirement, Risk } from "@/lib/types";

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

export default function RunPage({ params }: { params: { runId: string } }) {
  const queryClient = useQueryClient();
  const [messageApi, contextHolder] = message.useMessage();
  const run = useQuery({ queryKey: ["run", params.runId], queryFn: () => getRun(params.runId) });
  const requirements = useQuery({
    queryKey: ["requirements", params.runId],
    queryFn: () => getRequirements(params.runId),
  });
  const risks = useQuery({ queryKey: ["risks", params.runId], queryFn: () => getRisks(params.runId) });
  const missions = useQuery({
    queryKey: ["missions", params.runId],
    queryFn: () => getMissions(params.runId),
  });
  const planner = useMutation({
    mutationFn: () => planNext(params.runId),
    onSuccess: async (result) => {
      if (result.mission) {
        messageApi.success(`Planned ${result.mission.mission_type}: ${result.mission.key}`);
      } else {
        messageApi.info(`Planner: ${result.reason}`);
      }
      await queryClient.invalidateQueries({ queryKey: ["missions", params.runId] });
    },
    onError: (error) => messageApi.error(String(error)),
  });

  const loading = run.isLoading || requirements.isLoading || risks.isLoading || missions.isLoading;
  const error = run.error || requirements.error || risks.error || missions.error;
  if (loading) return <Spin size="large" />;
  if (error || !run.data) {
    return <Alert type="error" showIcon message="Unable to load test run" description={String(error)} />;
  }

  const requirementData = requirements.data || [];
  const riskData = risks.data || [];
  const missionData = missions.data || [];
  const covered = new Set(riskData.flatMap((risk) => risk.requirement_keys));
  const riskCoverage = requirementData.length
    ? Math.round((covered.size / requirementData.length) * 100)
    : 0;

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
  ];

  return (
    <main>
      {contextHolder}
      <div className="page-heading">
        <Link href={`/projects/${run.data.project_id}`}><ArrowLeftOutlined /> Project</Link>
        <Space style={{ width: "100%", justifyContent: "space-between", marginTop: 18 }} align="start">
          <div>
            <div className="eyebrow">Test Run</div>
            <Typography.Title level={1} style={{ margin: 0 }}>{run.data.key}</Typography.Title>
            <Space wrap style={{ marginTop: 10 }}>
              <Tag color={statusColor(run.data.status)}>{run.data.status}</Tag>
              <span className="entity-key">snapshot {run.data.source_snapshot_id}</span>
            </Space>
          </div>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={planner.isPending}
            onClick={() => planner.mutate()}
          >
            Plan next mission
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={12} lg={6}>
          <Card className="metric-card"><Statistic title="Requirements" value={requirementData.length} prefix={<CheckCircleOutlined />} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="metric-card"><Statistic title="Risks" value={riskData.length} prefix={<SafetyCertificateOutlined />} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="metric-card"><Statistic title="Missions" value={missionData.length} prefix={<DeploymentUnitOutlined />} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="metric-card">
            <Statistic title="Risk coverage" value={riskCoverage} suffix="%" />
            <Progress percent={riskCoverage} size="small" showInfo={false} />
          </Card>
        </Col>
      </Row>

      <Card className="section-card">
        <Tabs
          items={[
            {
              key: "requirements",
              label: `Requirements (${requirementData.length})`,
              children: <Table rowKey="id" columns={requirementColumns} dataSource={requirementData} pagination={false} />,
            },
            {
              key: "risks",
              label: `Risks (${riskData.length})`,
              children: <Table rowKey="id" columns={riskColumns} dataSource={riskData} pagination={false} />,
            },
            {
              key: "missions",
              label: `Missions (${missionData.length})`,
              children: <Table rowKey="id" columns={missionColumns} dataSource={missionData} pagination={false} />,
            },
          ]}
        />
      </Card>
    </main>
  );
}
