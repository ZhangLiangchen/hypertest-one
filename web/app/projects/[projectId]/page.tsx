"use client";

import { ArrowLeftOutlined, ArrowRightOutlined, BranchesOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Empty, Form, Input, Row, Space, Spin, Steps, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { createRun, getProject, getProjectRuns } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";
import { compileFormPolicy, defaultPolicyValues, PolicyFields, PolicyReview } from "./policy-fields";
import type { PolicyFormValues } from "./policy-fields";

type RunFormValues = PolicyFormValues & {
  repository_url: string;
  commit_sha: string;
  branch?: string;
  prd_text: string;
  configuration_text: string;
};

const stepFields: (keyof RunFormValues)[][] = [
  ["repository_url", "commit_sha", "branch"],
  ["prd_text", "configuration_text"],
  ["coverage_default_dimensions", "coverage_by_category", "blocking_severities"],
];

export default function ProjectPage() {
  const params = useParams<{ projectId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [requestKey, setRequestKey] = useState("");
  const [draft, setDraft] = useState<RunFormValues>({
    repository_url: "", commit_sha: "", branch: "main", prd_text: "", configuration_text: "{}",
    ...defaultPolicyValues(),
  });
  const [form] = Form.useForm<RunFormValues>();
  const project = useQuery({
    queryKey: ["project", params.projectId],
    queryFn: () => getProject(params.projectId),
  });
  const runs = useQuery({
    queryKey: ["project-runs", params.projectId],
    queryFn: () => getProjectRuns(params.projectId),
  });
  const creation = useMutation({
    mutationFn: (values: RunFormValues) => createRun(params.projectId, {
      repository_url: values.repository_url.trim(),
      commit_sha: values.commit_sha.trim().toLowerCase(),
      branch: values.branch?.trim() || undefined,
      prd_text: values.prd_text,
      configuration_text: values.configuration_text || "{}",
      idempotency_key: requestKey,
      policy: compileFormPolicy(values),
    }),
    onSuccess: (run) => {
      queryClient.setQueryData(["run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["project-runs", params.projectId] });
      router.push(`/runs/${run.id}`);
    },
  });

  const openCreate = () => {
    const initialValues: RunFormValues = {
      repository_url: project.data?.repository_url || "",
      commit_sha: "",
      branch: project.data?.default_branch || "main",
      prd_text: "",
      configuration_text: "{}",
      ...defaultPolicyValues(),
    };
    form.resetFields();
    form.setFieldsValue(initialValues);
    setDraft(initialValues);
    creation.reset();
    setRequestKey(`web:${crypto.randomUUID()}`);
    setStep(0);
    setCreateOpen(true);
  };

  const nextStep = async () => {
    try {
      await form.validateFields(stepFields[step], { recursive: true });
      setDraft(form.getFieldsValue(true) as RunFormValues);
      setStep(step + 1);
    } catch {
      // Field-level messages keep the user on the step that needs attention.
    }
  };

  const previousStep = () => {
    setDraft(form.getFieldsValue(true) as RunFormValues);
    setStep(step - 1);
  };

  if (project.isLoading) {
    return <Spin size="large" />;
  }
  if (project.isError || !project.data) {
    return (
      <main>
        <Link href="/"><ArrowLeftOutlined /> Projects</Link>
        <Alert
          type="error"
          showIcon
          message="Unable to load project"
          description={String(project.error || "Project not found")}
          action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>Retry</Button>}
          style={{ marginTop: 20 }}
        />
      </main>
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
          {project.data.repository_url ? <Tag style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{project.data.repository_url}</Tag> : null}
        </Space>
      </div>

      <Space wrap style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>Test runs</Typography.Title>
          <Typography.Text className="muted">Each run fixes the source, requirements and policy for a reproducible test cycle.</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>Create test run</Button>
      </Space>
      {runs.isLoading ? (
        <Spin />
      ) : runs.isError ? (
        <Alert
          type="error"
          showIcon
          message="Unable to load test runs"
          description={String(runs.error)}
          action={<Button onClick={() => void runs.refetch()} loading={runs.isFetching}>Retry</Button>}
        />
      ) : runs.data?.length ? (
        <Row gutter={[18, 18]}>
          {runs.data.map((run) => (
            <Col xs={24} md={12} xl={8} key={run.id}>
              <Link href={`/runs/${run.id}`} style={{ textDecoration: "none" }}>
                <Card className="run-card" hoverable>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Tag color={run.status === "COMPLETED" ? "green" : run.status === "BLOCKED" ? "red" : "geekblue"}>{run.status}</Tag>
                      <ArrowRightOutlined />
                    </Space>
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>{run.key}</Typography.Title>
                      <div className="muted" style={{ marginTop: 4 }}>Source snapshot</div>
                      <div className="entity-key" style={{ overflowWrap: "anywhere" }}>{run.source_snapshot_id}</div>
                    </div>
                    <Typography.Text className="muted">Trigger: {run.trigger_type}</Typography.Text>
                  </Space>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      ) : (
        <Card className="section-card">
          <Empty description="Create a test run to analyze requirements and build test coverage.">
            <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>Create test run</Button>
          </Empty>
        </Card>
      )}

      <Modal
        title="Create test run"
        open={createOpen}
        forceRender
        onCancel={() => setCreateOpen(false)}
        footer={null}
        width={760}
        closable={!creation.isPending}
        maskClosable={!creation.isPending}
        keyboard={!creation.isPending}
      >
        <Steps
          current={step}
          size="small"
          items={[{ title: "Source" }, { title: "Requirements" }, { title: "Policy" }, { title: "Review" }]}
          style={{ margin: "24px 0" }}
        />
        {creation.isError ? (
          <Alert type="error" showIcon message="Test run could not be created" description={creation.error.message} style={{ marginBottom: 20 }} />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message="Test run created. Opening the workbench…" style={{ marginBottom: 20 }} />
        ) : null}
        <Form
          name="create-test-run"
          form={form}
          layout="vertical"
          preserve
          disabled={creation.isPending || creation.isSuccess}
          requiredMark="optional"
          onValuesChange={() => { if (creation.isError) creation.reset(); }}
        >
          {step === 0 ? (
            <>
              <Typography.Paragraph className="muted">
                Choose the exact source revision to test. The full commit SHA keeps this run tied to an immutable version.
              </Typography.Paragraph>
              <Form.Item
                name="repository_url"
                label="Repository URL"
                rules={[{ required: true, whitespace: true, message: "Enter the repository URL." }]}
              >
                <Input placeholder="https://github.com/your-team/your-repository" />
              </Form.Item>
              <Form.Item
                name="commit_sha"
                label="Commit SHA"
                extra="Use the full 40-character or 64-character hexadecimal commit SHA."
                rules={[
                  { required: true, message: "Enter the full commit SHA." },
                  { pattern: /^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/, message: "Enter a full 40-character or 64-character hexadecimal commit SHA." },
                ]}
              >
                <Input placeholder="Full commit SHA" maxLength={64} autoComplete="off" style={{ fontFamily: "monospace" }} />
              </Form.Item>
              <Form.Item name="branch" label="Branch" extra="A reference label; the commit SHA fixes the source version.">
                <Input placeholder={project.data.default_branch} />
              </Form.Item>
            </>
          ) : step === 1 ? (
            <>
              <Typography.Paragraph className="muted">
                Provide the product requirements for this run. HyperTest uses them to identify requirements, analyze risks and design tests.
              </Typography.Paragraph>
              <Form.Item
                name="prd_text"
                label="Product requirements (PRD)"
                rules={[{ required: true, whitespace: true, message: "Add the requirements to test." }]}
              >
                <Input.TextArea rows={9} placeholder="Describe the expected behavior, constraints, acceptance criteria and important edge cases…" />
              </Form.Item>
              <Form.Item
                name="configuration_text"
                label="Testing configuration"
                extra="Optional configuration text or JSON. It is saved with the immutable inputs for this run."
              >
                <Input.TextArea rows={4} placeholder="{}" style={{ fontFamily: "monospace" }} />
              </Form.Item>
            </>
          ) : step === 2 ? <PolicyFields /> : (
            <Space direction="vertical" size={18} style={{ width: "100%", marginBottom: 24 }}>
              <Alert
                type="info"
                showIcon
                message="Ready to create your test run"
                description="These inputs will be fixed in immutable source and policy snapshots. Start the testing workflow from the workbench after creation."
              />
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="Project">{project.data.name}</Descriptions.Item>
                <Descriptions.Item label="Repository"><span style={{ overflowWrap: "anywhere" }}>{draft.repository_url}</span></Descriptions.Item>
                <Descriptions.Item label="Commit"><Typography.Text code copyable style={{ overflowWrap: "anywhere", wordBreak: "break-all" }}>{draft.commit_sha}</Typography.Text></Descriptions.Item>
                <Descriptions.Item label="Branch">{draft.branch?.trim() || "Not specified"}</Descriptions.Item>
                <Descriptions.Item label="Policy">
                  <PolicyReview values={draft} />
                </Descriptions.Item>
              </Descriptions>
              <div style={{ width: "100%" }}>
                <Typography.Title level={5} style={{ marginTop: 0 }}>Product requirements</Typography.Title>
                <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 220, overflowY: "auto", padding: 12, background: "#f5f7fb", borderRadius: 6 }}>
                  {draft.prd_text}
                </div>
              </div>
              <details style={{ width: "100%" }}>
                <summary style={{ cursor: "pointer" }}>Testing configuration</summary>
                <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 180, overflowY: "auto" }}>{draft.configuration_text || "{}"}</pre>
              </details>
            </Space>
          )}
          <Space wrap style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
            <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Space>
              {step > 0 ? <Button onClick={previousStep}>Back</Button> : null}
              {step < 3 ? (
                <Button type="primary" onClick={() => void nextStep()}>Continue <ArrowRightOutlined /></Button>
              ) : (
                <Button
                  type="primary"
                  aria-label="Create test run"
                  onClick={() => creation.mutate(form.getFieldsValue(true) as RunFormValues)}
                  loading={creation.isPending || creation.isSuccess}
                >
                  Create test run
                </Button>
              )}
            </Space>
          </Space>
        </Form>
      </Modal>
    </main>
  );
}
