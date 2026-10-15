"use client";

import { ArrowRightOutlined, CodeOutlined, DatabaseOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Empty, Row, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";

import { getProjects } from "@/lib/api";

export default function DashboardPage() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });

  return (
    <main>
      <div className="page-heading">
        <div className="eyebrow">Autonomous Testing Control Plane</div>
        <Typography.Title level={1} style={{ margin: 0 }}>
          Testing state, not agent chat.
        </Typography.Title>
        <Typography.Paragraph className="muted" style={{ maxWidth: 760, marginTop: 10 }}>
          HyperTest One turns PRD, source code and test environments into governed testing missions,
          canonical state and verifiable evidence.
        </Typography.Paragraph>
      </div>

      {projects.isLoading ? (
        <Spin size="large" />
      ) : projects.isError ? (
        <Alert type="error" showIcon message="Unable to load projects" description={String(projects.error)} />
      ) : projects.data?.length ? (
        <Row gutter={[18, 18]}>
          {projects.data.map((project) => (
            <Col xs={24} md={12} xl={8} key={project.id}>
              <Link href={`/projects/${project.id}`} style={{ textDecoration: "none" }}>
                <Card className="project-card" hoverable>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Tag color="blue">{project.status}</Tag>
                      <ArrowRightOutlined />
                    </Space>
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>
                        {project.name}
                      </Typography.Title>
                      <div className="entity-key">{project.key}</div>
                    </div>
                    <Typography.Paragraph className="muted" ellipsis={{ rows: 2 }} style={{ margin: 0 }}>
                      {project.description || "No project description yet."}
                    </Typography.Paragraph>
                    <Space split={<span className="muted">·</span>}>
                      <span className="muted"><CodeOutlined /> {project.default_branch}</span>
                      <span className="muted"><DatabaseOutlined /> Canonical state</span>
                    </Space>
                  </Space>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      ) : (
        <Empty description="No projects yet. Create one through the HyperTest API to start." />
      )}
    </main>
  );
}
