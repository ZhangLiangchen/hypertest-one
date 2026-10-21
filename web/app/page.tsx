"use client";

import { ArrowRightOutlined, BranchesOutlined, FolderOpenOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Empty, Form, Input, Select, Space, Spin, Table, Tag, Typography } from "antd";
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
  const { t, label, locale, formatDate } = useI18n();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
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
      <div className="page-heading heading-with-action">
        <div>
          <Typography.Title level={1} style={{ margin: 0 }}>{t("Projects", "项目工作台")}</Typography.Title>
          <Typography.Paragraph className="muted page-intro">{t("Manage Codex testing tasks, cases and reports by project.", "按项目管理 Codex 测试任务、用例和报告。")}</Typography.Paragraph>
        </div>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{t("Create project", "创建项目")}</Button>
      </div>
      <section className="workspace-intro" aria-label={t("Testing workflow", "测试工作流")}>
        <div className="intro-mark"><FolderOpenOutlined aria-hidden /></div>
        <div><h2>{t("Keep Codex testing work traceable.", "让 Codex 测试工作，有迹可循。")}</h2><p>{t("Codex performs the testing work. Sync each session's task, plan, cases and original reports to its project.", "Codex 完成测试工作，将每个会话的任务、计划、用例和原始报告同步到所属项目。")}</p></div>
        <div className="workflow-labels"><span>{t("Task", "任务")}</span><ArrowRightOutlined aria-hidden /><span>{t("Cases", "用例")}</span><ArrowRightOutlined aria-hidden /><span>{t("Reports & history", "报告与历史")}</span></div>
      </section>
      <section className="data-surface" aria-label={t("Project list", "项目列表")}>
        <div className="list-toolbar">
          <h2>{t("All projects", "全部项目")} <span className="count-badge">{projects.data?.length ?? "—"}</span></h2>
          <div className="list-filters"><Input prefix={<SearchOutlined aria-hidden />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search name, key or repository", "搜索名称、标识或仓库")} aria-label={t("Search projects", "搜索项目")} /><Select id="project-status" value={status} onChange={setStatus} aria-label={t("Project status", "项目状态")} options={[{value: "all", label: t("All statuses", "全部状态")}, {value: "ACTIVE", label: label("ACTIVE")}, {value: "ARCHIVED", label: label("ARCHIVED")}]} /></div>
        </div>
        {projects.isLoading ? <div className="pane-loading" role="status" aria-label={t("Loading projects…", "正在加载项目…")}><Space direction="vertical" align="center"><Spin /><span className="muted">{t("Loading projects…", "正在加载项目…")}</span></Space></div> : projects.isError ? <div className="surface-message"><Alert type="error" showIcon message={t("Unable to load projects", "无法加载项目")} description={errorText(projects.error, locale)} action={<Button onClick={() => void projects.refetch()} loading={projects.isFetching}>{t("Retry", "重试")}</Button>} /></div> : projects.data?.length ? <Table
          rowKey="id" pagination={{pageSize: 10, hideOnSinglePage: true}} scroll={{ x: 760 }}
          dataSource={projects.data.filter((project) => (status === "all" || project.status === status) && `${project.name} ${project.key} ${project.repository_url || ""}`.toLowerCase().includes(search.trim().toLowerCase()))}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("No matching projects. Try a different search or reset the filters.", "未找到匹配项目。请修改搜索内容，或重置筛选。")}><Button onClick={() => { setSearch(""); setStatus("all"); }}>{t("Reset filters", "重置筛选")}</Button></Empty> }}
          columns={[
            {title: t("Project", "项目"), key: "name", width: "38%", sorter: (a, b) => a.name.localeCompare(b.name), render: (_, project) => <div className="project-name-cell"><span className="project-avatar" aria-hidden>{project.name.slice(0, 1).toUpperCase()}</span><div><Link className="entity-title" href={`/projects/${project.id}`}>{project.name}</Link><div className="entity-key">{project.key}</div><p className="cell-description">{project.description || t("No description", "暂无描述")}</p></div></div>},
            {title: t("Repository / branch", "仓库 / 分支"), key: "repository", render: (_, project) => <div className="repository-cell"><span>{project.repository_url || t("Repository not set", "尚未设置仓库")}</span><small><BranchesOutlined aria-hidden /> {project.default_branch}</small></div>},
            {title: t("Status", "状态"), dataIndex: "status", width: 120, render: (value: string) => <Tag className="project-status-tag" color={value === "ACTIVE" ? "green" : undefined}>{label(value)}</Tag>},
            {title: t("Updated", "更新时间"), dataIndex: "updated_at", width: 160, sorter: (a, b) => a.updated_at.localeCompare(b.updated_at), render: formatDate},
            {title: t("Open", "打开"), key: "open", width: 65, render: (_, project) => <Link href={`/projects/${project.id}`} aria-label={`${t("Open project", "打开项目")} ${project.name}`}><ArrowRightOutlined /></Link>},
          ]}
        /> : <div className="empty-workspace"><FolderOpenOutlined aria-hidden /><h3>{t("Your first project starts here", "从第一个项目开始")}</h3><p>{t("Create a project, then sync testing tasks and artifacts from your Codex sessions.", "创建项目后，从 Codex 会话同步测试任务和产物。")}</p><Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{t("Create project", "创建项目")}</Button></div>}
      </section>

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
          {t("A project groups Codex testing tasks, plans, cases and reports. After creation, sync the testing work from its Codex sessions.", "项目集中管理 Codex 测试任务、计划、用例和报告。创建后，从所属 Codex 会话同步测试工作。")}
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
