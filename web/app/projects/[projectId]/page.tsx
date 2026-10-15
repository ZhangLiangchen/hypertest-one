"use client";

import { ArrowLeftOutlined, ArrowRightOutlined, BranchesOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Empty, Row, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";

import { getProject, getProjectRuns } from "@/lib/api";

export default function ProjectPage({ params }: { params: { projectId: string } }) {
  const project = useQuery({
    queryKey: ["project", params.projectId],
    queryFn: () => getProject(params.projectId),
  });
  const runs = useQuery({
    queryKey: ["project-runs", params.projectId],
    queryFn: () => getProjectRuns(params.projectId),
  });

  if (project.isLoading || runs.isLoading) {
    return <Spin size="large" />;
  }
  if (project.isError || runs.isError || !project.data) {
    return (
      <Alert
        type="error"
        showIcon
        message="Unable to load project"
        description={String(project.error || runs.error || "Project not found")}
      />
    );
  }

  return (
    <main>
      <div className="page-heading">
        <Link href="/"><ArrowLeftOutlined /> Projects</Link>
        <div className="eyebrow" style={{ marginTop: 18 }}>{project.data.key}</div>
        <Typography.Title level={1} style={{ margin: 0 }}>{project.data.name}</Typography.Title>
        <Typography.Paragraph className="muted" style={{ marginTop: 8 }}>
          {project.data.description || "Project testing workspace"}
        </Typography.Paragraph>
        <Space wrap>
          <Tag color="blue">{project.data.status}</Tag>
          <Tag icon={<BranchesOutlined />}>{project.data.default_branch}</Tag>
          {project.data.repository_url ? <Tag>{project.data.repository_url}</Tag> : null}
        </Space>
      </div>

      <Typography.Title level={3}>Test runs</Typography.Title>
      {runs.data?.length ? (
        <Row gutter={[18, 18]}>
          {runs.data.map((run) => (
            <Col xs={24} md={12} xl={8} key={run.id}>
              <Link href={`/runs/${run.id}`} style={{ textDecoration: "none" }}>
                <Card className="run-card" hoverable>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Tag color={run.status === "COMPLETED" ? "green" : "geekblue"}>{run.status}</Tag>
                      <ArrowRightOutlined />
                    </Space>
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>{run.key}</Typography.Title>
                      <div className="entity-key">{run.source_snapshot_id}</div>
                    </div>
                    <Typography.Text className="muted">
                      Trigger: {run.trigger_type}
                    </Typography.Text>
                  </Space>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      ) : (
        <Empty description="No test runs yet." />
      )}
    </main>
  );
}
