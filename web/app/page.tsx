"use client";

import { ArrowRightOutlined, CodeOutlined, DatabaseOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Empty, Form, Input, Row, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProject, getProjects } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";

type ProjectFormValues = {
  key: string;
  name: string;
  description?: string;
  repository_url?: string;
  default_branch: string;
};

export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const creation = useMutation({
    mutationFn: (values: ProjectFormValues) => createProject({
      key: values.key.trim(),
      name: values.name.trim(),
      description: values.description?.trim() || undefined,
      repository_url: values.repository_url?.trim() || undefined,
      default_branch: values.default_branch.trim(),
    }),
    onSuccess: (project) => {
      queryClient.setQueryData(["project", project.id], project);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${project.id}`);
    },
  });

  const openCreate = () => {
    form.resetFields();
    creation.reset();
    setCreateOpen(true);
  };

  return (
    <main>
      <div className="page-heading">
        <div className="eyebrow">Autonomous Testing Control Plane</div>
        <Typography.Title level={1} style={{ margin: 0 }}>
          Your testing workspace.
        </Typography.Title>
        <Typography.Paragraph className="muted" style={{ maxWidth: 760, marginTop: 10 }}>
          Bring your requirements and repository together. HyperTest tracks testing work from
          requirements and risks to test cases, execution and evidence.
        </Typography.Paragraph>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>
          Create project
        </Button>
      </div>

      {projects.isLoading ? (
        <Spin size="large" />
      ) : projects.isError ? (
        <Alert
          type="error"
          showIcon
          message="Unable to load projects"
          description={String(projects.error)}
          action={<Button onClick={() => void projects.refetch()} loading={projects.isFetching}>Retry</Button>}
        />
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
                    <Space wrap split={<span className="muted">·</span>}>
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
        <Card className="section-card">
          <Empty description="Create your first project to start testing.">
            <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>Create project</Button>
          </Empty>
        </Card>
      )}

      <Modal
        title="Create project"
        open={createOpen}
        forceRender
        onCancel={() => setCreateOpen(false)}
        footer={null}
        closable={!creation.isPending}
        maskClosable={!creation.isPending}
        keyboard={!creation.isPending}
        width={600}
      >
        <Typography.Paragraph className="muted">
          A project keeps your requirements, risks, test runs and evidence in one workspace.
        </Typography.Paragraph>
        {creation.isError ? (
          <Alert
            type="error"
            showIcon
            message="Project could not be created"
            description={creation.error.message}
            style={{ marginBottom: 20 }}
          />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message="Project created. Opening your workspace…" style={{ marginBottom: 20 }} />
        ) : null}
        <Form
          name="create-project"
          form={form}
          layout="vertical"
          initialValues={{ default_branch: "main" }}
          onFinish={(values) => creation.mutate(values)}
          onValuesChange={() => { if (creation.isError) creation.reset(); }}
          disabled={creation.isPending || creation.isSuccess}
          requiredMark="optional"
        >
          <Form.Item
            name="name"
            label="Project name"
            rules={[{ required: true, whitespace: true, message: "Enter a project name." }, { max: 255 }]}
          >
            <Input placeholder="Payments service" maxLength={255} autoFocus />
          </Form.Item>
          <Form.Item
            name="key"
            label="Project key"
            normalize={(value: string) => value.toUpperCase()}
            extra="A short identifier using uppercase letters, numbers, underscores or hyphens."
            rules={[
              { required: true, message: "Enter a project key." },
              { min: 2, max: 64, message: "Use 2–64 characters." },
              { pattern: /^[A-Z0-9_-]+$/, message: "Use uppercase letters, numbers, underscores or hyphens." },
            ]}
          >
            <Input placeholder="PAYMENTS" maxLength={64} />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea rows={2} placeholder="What does this project do?" />
          </Form.Item>
          <Form.Item name="repository_url" label="Repository URL" extra="Used to prefill new test runs.">
            <Input placeholder="https://github.com/your-team/your-repository" />
          </Form.Item>
          <Form.Item
            name="default_branch"
            label="Default branch"
            rules={[{ required: true, whitespace: true, message: "Enter the default branch." }]}
          >
            <Input placeholder="main" />
          </Form.Item>
          <Space style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="primary" htmlType="submit" aria-label="Create project" loading={creation.isPending || creation.isSuccess}>
              Create project
            </Button>
          </Space>
        </Form>
      </Modal>
    </main>
  );
}
