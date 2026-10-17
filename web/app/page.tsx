"use client";

import { ArrowRightOutlined, CodeOutlined, DatabaseOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Empty, Form, Input, Row, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createProject, errorText, getProjects } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";
import { useI18n } from "@/lib/i18n";
import { createUuid } from "@/lib/uuid";

type ProjectFormValues = {
  key: string;
  name: string;
  description?: string;
  repository_url?: string;
  default_branch: string;
};

export default function DashboardPage() {
  const { t, label, locale } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<ProjectFormValues>();
  useEffect(() => {
    if (!createOpen) return;
    const invalid = form.getFieldsError().filter((field) => field.errors.length).map((field) => field.name);
    if (invalid.length) void form.validateFields(invalid, { recursive: true }).catch(() => undefined);
  }, [locale, form, createOpen]);
  const enteredKey = Form.useWatch("key", form);
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const existingProject = projects.data?.find((project) => project.key === enteredKey?.trim().toUpperCase());
  const creation = useMutation({
    mutationFn: (values: ProjectFormValues) => createProject({
      key: values.key.trim().toUpperCase(),
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
    onError: () => {
      // A response can be lost after creation. Refresh the list so the existing project is reachable.
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const suggestKey = () => {
    if (form.getFieldValue("key")) return;
    const name = String(form.getFieldValue("name") || "");
    const suggested = name.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64);
    form.setFieldValue("key", suggested.length >= 2 ? suggested : `PROJECT_${createUuid().slice(0, 8).toUpperCase()}`);
  };
  const openCreate = () => setCreateOpen(true);

  return (
    <main>
      <div className="page-heading">
        <div className="eyebrow">{t("Autonomous Testing Control Plane", "自主测试控制平面")}</div>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t("Your testing workspace.", "你的测试工作台")}
        </Typography.Title>
        <Typography.Paragraph className="muted" style={{ maxWidth: 760, marginTop: 10 }}>
          {t("Bring your requirements and repository together. HyperTest tracks testing work from requirements and risks to test cases, execution and evidence.", "连接产品需求与代码仓库，从需求、风险、测试用例到执行与证据，追踪完整测试过程。")}
        </Typography.Paragraph>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>
          {t("Create project", "创建项目")}
        </Button>
      </div>

      {projects.isLoading ? (
        <div className="pane-loading" role="status" aria-label={t("Loading projects…", "正在加载项目…")}><Spin size="large" /></div>
      ) : projects.isError ? (
        <Alert
          type="error"
          showIcon
          message={t("Unable to load projects", "无法加载项目")}
          description={errorText(projects.error, locale)}
          action={<Button onClick={() => void projects.refetch()} loading={projects.isFetching}>{t("Retry", "重试")}</Button>}
        />
      ) : projects.data?.length ? (
        <Row gutter={[18, 18]}>
          {projects.data.map((project) => (
            <Col xs={24} md={12} xl={8} key={project.id}>
              <Link href={`/projects/${project.id}`} style={{ textDecoration: "none" }}>
                <Card className="project-card" hoverable>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Tag color="blue">{label(project.status)}</Tag>
                      <ArrowRightOutlined aria-hidden />
                    </Space>
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>{project.name}</Typography.Title>
                      <div className="entity-key">{project.key}</div>
                    </div>
                    <Typography.Paragraph className="muted" ellipsis={{ rows: 2 }} style={{ margin: 0 }}>
                      {project.description || t("No project description yet.", "尚未填写项目描述。")}
                    </Typography.Paragraph>
                    <Space wrap split={<span className="muted">·</span>}>
                      <span className="muted"><CodeOutlined aria-hidden /> {project.default_branch}</span>
                      <span className="muted"><DatabaseOutlined aria-hidden /> {t("Canonical state", "权威测试状态")}</span>
                    </Space>
                  </Space>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      ) : (
        <Card className="section-card">
          <Empty description={t("Create your first project to start testing.", "创建第一个项目，开始测试。")}>
            <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{t("Create project", "创建项目")}</Button>
          </Empty>
        </Card>
      )}

      <Modal
        title={t("Create project", "创建项目")}
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
          {t("A project keeps requirements, risks, test runs and evidence together. Next, create a test run with a source revision and PRD.", "项目集中管理需求、风险、测试运行和证据。创建后，选择代码版本并提交 PRD，即可开始一轮测试。")}
        </Typography.Paragraph>
        {creation.isError ? (
          <Alert
            type="error"
            showIcon
            message={t("Project could not be created", "项目创建失败")}
            description={errorText(creation.error, locale)}
            style={{ marginBottom: 20 }}
          />
        ) : null}
        {existingProject && !creation.isSuccess ? (
          <Alert
            type="info"
            showIcon
            message={t("This project key is already in use.", "此项目标识已被使用。")}
            description={<Link href={`/projects/${existingProject.id}`}>{t("Open the existing project", "打开已有项目")}: {existingProject.name}</Link>}
            style={{ marginBottom: 20 }}
          />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message={t("Project created. Opening your workspace…", "项目已创建，正在打开工作台…")} style={{ marginBottom: 20 }} />
        ) : null}
        <Form
          name="create-project"
          form={form}
          layout="vertical"
          initialValues={{ default_branch: "main" }}
          onFinish={(values) => creation.mutate(values)}
          onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}
          onValuesChange={() => { if (creation.isError) creation.reset(); }}
          disabled={creation.isPending || creation.isSuccess}
          requiredMark="optional"
        >
          <Form.Item
            name="name"
            label={t("Project name", "项目名称")}
            rules={[{ required: true, whitespace: true, message: t("Enter a project name.", "请输入项目名称。") }, { max: 255, message: t("Use at most 255 characters.", "最多输入 255 个字符。") }]}
          >
            <Input placeholder={t("Payments service", "例如：支付服务")} maxLength={255} autoFocus onBlur={() => { if (form.getFieldValue("name")?.trim()) suggestKey(); }} />
          </Form.Item>
          <Form.Item
            name="key"
            label={t("Project key", "项目标识")}
            normalize={(value: string) => value.trim().toUpperCase()}
            extra={t("A unique 2–64 character identifier. A suggestion is filled from the project name; you can edit it.", "唯一的 2–64 位标识。会根据项目名自动建议，你也可以修改；支持大写字母、数字、下划线和连字符。")}
            rules={[
              { required: true, message: t("Enter a project key.", "请输入项目标识。") },
              { min: 2, max: 64, message: t("Use 2–64 characters.", "请输入 2–64 个字符。") },
              { pattern: /^[A-Z0-9_-]+$/, message: t("Use uppercase letters, numbers, underscores or hyphens.", "仅支持大写字母、数字、下划线或连字符。") },
              { validator: async (_, value: string) => { if (projects.data?.some((project) => project.key === value?.trim().toUpperCase())) throw new Error(t("This key is taken. Choose another key or open the existing project above.", "此标识已被使用，请修改标识，或通过上方链接打开已有项目。")); } },
            ]}
          >
            <Input placeholder="PAYMENTS" maxLength={64} autoComplete="off" />
          </Form.Item>
          <Form.Item name="description" label={t("Description", "项目描述")}>
            <Input.TextArea rows={2} placeholder={t("What does this project do?", "描述项目的用途与测试范围")} />
          </Form.Item>
          <Form.Item
            name="repository_url"
            label={t("Repository origin", "仓库源地址（origin）")}
            extra={<>{t("Optional. Use the repository's origin address, not its checkout folder. In an existing checkout, run: ", "可选，用于预填新测试运行。填写仓库的 origin 地址，不是检出目录。在已有 Git 检出中执行：")}<Typography.Text code copyable>git remote get-url origin</Typography.Text>{t(". A local Git source path is valid only when it is the origin value itself. Choose the Worker checkout directory after creating a run.", "。本地 Git 源路径只有与 origin 输出本身一致时才有效；Worker 工作目录将在创建运行后选择。")}</>}
            rules={[{ max: 2048, message: t("Use at most 2,048 characters for the repository address.", "仓库地址最多 2,048 个字符。") }]}
          >
            <Input placeholder="https://github.com/your-team/your-repository" maxLength={2048} />
          </Form.Item>
          <Form.Item
            name="default_branch"
            label={t("Default branch", "默认分支")}
            rules={[{ required: true, whitespace: true, message: t("Enter the default branch.", "请输入默认分支。") }]}
          >
            <Input placeholder="main" />
          </Form.Item>
          <Typography.Paragraph className="muted">{t("Closing keeps your draft while you stay on this page.", "关闭窗口会保留当前页面内的草稿。")}</Typography.Paragraph>
          <Space style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button onClick={() => setCreateOpen(false)}>{t("Close", "关闭")}</Button>
            <Button type="primary" htmlType="submit" aria-label={t("Create project", "创建项目")} loading={creation.isPending || creation.isSuccess}>
              {t("Create project", "创建项目")}
            </Button>
          </Space>
        </Form>
      </Modal>
    </main>
  );
}
