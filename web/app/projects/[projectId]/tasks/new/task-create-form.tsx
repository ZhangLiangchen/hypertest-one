"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Radio, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { type ArchiveManagement } from "@/lib/archive";
import { useArchiveOperation } from "@/lib/archive-operation";
import { cloudCapabilities, cloudConfiguration, cloudSetup } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import { archiveTaskHref } from "@/lib/task-url";
import { WorkspaceLoading } from "@/app/workspace-ui";
import { ArchivePrompt } from "@/app/archives/archive-prompt";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";
import { CloudCapabilitiesNotice, CloudOperationNotice } from "../../cloud/cloud-shared";
import { CloudTaskForm } from "../../cloud/task-form";
import type { Project } from "@/lib/types";

type Values = { mode: "cloud" | "local"; title: string; objective: string; sut_branch?: string; framework_branch?: string };
export function TaskCreateForm({ projectId, project, onModeChange }: { projectId: string; project?: Project; onModeChange?: (mode: "local" | "cloud") => void }) {
  const { t } = useI18n(); const router = useRouter(); const search = useSearchParams(); const cache = useQueryClient(); const [form] = Form.useForm<Values>();
  const mode = Form.useWatch("mode", { form, preserve: true }) || (search.get("mode") === "local" ? "local" : "cloud");
  const title = Form.useWatch("title", { form, preserve: true }) || "", objective = Form.useWatch("objective", { form, preserve: true }) || "";
  const local = useArchiveOperation(projectId, "create-task");
  const cloudOperation = useCloudOperation(projectId);
  const cloudSetupQuery = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup, retry: false });
  const cloudConfigured = cloudSetupQuery.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: cloudConfigured, retry: false });
  const configuration = useQuery({ queryKey: ["cloud-config", projectId], queryFn: () => cloudConfiguration(projectId), enabled: cloudConfigured, retry: false });
  const latestConfig = configuration.data?.items.slice().sort((a, b) => b.revision - a.revision)[0];
  const cloudReadFailed = cloudSetupQuery.isError || capabilities.isError || configuration.isError;
  const loadingCloud = cloudSetupQuery.isPending || cloudConfigured && (capabilities.isPending || configuration.isPending);
  const showCloudForm = Boolean(latestConfig) || (cloudConfigured && !loadingCloud && !cloudReadFailed);
  const missingRepositories = Boolean(project && (!project.repository_url || !project.test_framework_repository_url));
  const localStreamBlocked = local.blocked;
  const localBlocked = localStreamBlocked || missingRepositories, cloudBlocked = cloudOperation.busy || Boolean(cloudOperation.pending) || cloudOperation.receipt?.operation === "CREATE_TASK";
  const accepted = (value: ArchiveManagement) => { void cache.invalidateQueries({ queryKey: ["archive-tasks", projectId] }); router.push(archiveTaskHref(value.task.id, projectId)); };
  async function refreshCloud() { const setup = await cloudSetupQuery.refetch(); if (setup.data?.configured) await Promise.all([capabilities.refetch(), configuration.refetch()]); }
  async function submit(values: Values) {
    if (values.mode !== "local" || localBlocked || cloudBlocked) return;
    const result = await local.manage("tasks", { title: values.title, objective: values.objective,
      sut_branch: values.sut_branch?.trim() || null, framework_branch: values.framework_branch?.trim() || null,
      ...(project ? { expected_project_version: project.row_version } : {}) });
    if (result) accepted(result);
  }
  return <><section className="workspace-panel" aria-labelledby="task-details-title"><Form form={form} layout="vertical" initialValues={{ mode: search.get("mode") === "local" ? "local" : "cloud", title: "", objective: "" }}
    disabled={local.busy || Boolean(local.pending) || cloudBlocked} requiredMark="optional" onFinish={submit}
    onValuesChange={(changed) => { if (changed.mode === "local" || changed.mode === "cloud") onModeChange?.(changed.mode); }}
    onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}>
    <Typography.Title id="task-details-title" level={2}>{t("Task details", "任务信息")}</Typography.Title>
    <Form.Item name="mode" label={t("Execution mode", "执行方式")} rules={[{ required: true }]}><Radio.Group options={[{ value: "cloud", label: t("Cloud testing", "云端测试") }, { value: "local", label: t("Local testing", "本地测试") }]} /></Form.Item>
    <Form.Item name="title" label={t("Task title", "任务标题")} rules={[{ required: true, whitespace: true, message: t("Enter a task title.", "请输入任务标题。") }, { max: 512 }]}><Input maxLength={512} autoFocus autoComplete="off" /></Form.Item>
    <Form.Item name="objective" label={t("Testing objective", "测试目标")} rules={[{ required: true, whitespace: true, message: t("Describe the testing objective.", "请描述测试目标。") }, { max: 16000 }]}><Input.TextArea rows={4} maxLength={16000} /></Form.Item>
    {mode === "local" ? <div className="form-section"><Typography.Title level={3}>{t("Local test setup", "本地测试配置")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("The local Agent performs testing independently. After testing, explicitly archive selected artifacts to this task; optional subtasks can be added later.", "本地 Agent 独立完成测试。测试后将选定产物显式归档到此任务；子任务可在任务页按需添加。")}</Typography.Paragraph>
      {project && (!project.repository_url || !project.test_framework_repository_url) ? <Alert type="warning" showIcon style={{ marginBottom: 20 }} message={t("Project repository addresses are incomplete", "项目仓库地址尚未填写完整")} description={t("Edit the project to add the SUT and test framework repositories. Existing tasks and their recorded inputs remain unchanged.", "请编辑项目，补充被测对象和测试框架仓库地址；已有任务及其记录的输入保持不变。") } /> : null}
      <Typography.Title level={3}>{t("Repository branches", "仓库分支")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Enter a Git branch name for each repository. Local Agents perform the checkout; this does not verify the selected revision.", "分别输入两个仓库的 Git 分支名称。本地 Agent 负责检出；填写分支不代表版本已核验。")}</Typography.Paragraph>
      <div className="form-grid">
        <Form.Item name="sut_branch" label={t("SUT branch", "被测对象分支")} extra={project?.repository_url || t("SUT repository not configured", "尚未配置被测对象仓库")} rules={[{ required: true, whitespace: true, message: t("Enter the SUT branch name.", "请输入被测对象分支名称。") }, { max: 255 }]}><Input maxLength={255} placeholder="main" autoComplete="off" /></Form.Item>
        <Form.Item name="framework_branch" label={t("Test framework branch", "测试框架分支")} extra={project?.test_framework_repository_url || t("Test framework repository not configured", "尚未配置测试框架仓库")} rules={[{ required: true, whitespace: true, message: t("Enter the test framework branch name.", "请输入测试框架分支名称。") }, { max: 255 }]}><Input maxLength={255} placeholder="main" autoComplete="off" /></Form.Item>
      </div>
      <div style={{ marginBottom: 20 }}><Link href={`/cli-authorizations?projectId=${projectId}#cli-install`} target="_blank" rel="noopener noreferrer">{t("CLI installation prompt & authorization (new tab)", "CLI 安装 Prompt 与授权（新标签页）")}</Link></div>
      <Button htmlType="submit" type="primary" disabled={localBlocked || cloudBlocked} loading={local.busy}>{t("Create local test task", "创建本地测试任务")}</Button>
    </div> : null}
  </Form></section>
  {mode === "local" ? <section className="workspace-panel archive-section" style={{ marginTop: 24 }}><Typography.Title level={2}>{t("Archive prompt template", "归档 Prompt 模板")}</Typography.Title><ArchivePrompt projectId={projectId} /></section> : null}
  <ArchiveOperationNotice operation={local} onAccepted={(value) => accepted(value as ArchiveManagement)} />
  {local.error && local.error instanceof ApiError && local.error.detail === "ARCHIVE_PROJECT_VERSION_CONFLICT" ? <Button onClick={() => void cache.invalidateQueries({ queryKey: ["project", projectId] })} style={{ marginTop: 12 }}>{t("Refresh project repositories", "刷新项目仓库")}</Button> : null}
  <CloudOperationNotice operation={cloudOperation} />
  <div hidden={mode !== "cloud"} style={{ marginTop: 24 }}><Space wrap style={{ marginBottom: 20 }}><Button onClick={() => void refreshCloud()} loading={cloudSetupQuery.isFetching || capabilities.isFetching || configuration.isFetching}>{t("Refresh Cloud configuration", "刷新云端配置")}</Button>{latestConfig ? <Link href={`/projects/${projectId}/cloud?tab=resources`} target="_blank" rel="noopener noreferrer">{t("Project resources (new tab)", "项目资源（新标签页）")}</Link> : null}</Space>
    {!cloudSetupQuery.isPending && !cloudSetupQuery.isError && (!cloudConfigured || capabilities.data?.enabled === false) ? <CloudCapabilitiesNotice configured={cloudConfigured} capabilities={capabilities.data} /> : null}
    {cloudReadFailed ? <Alert showIcon type="error" style={{ marginBottom: 20 }} message={t("Cloud configuration could not be refreshed", "无法刷新云端配置")} description={t("Your inputs and loaded configuration are preserved. Refresh before creating a draft.", "当前输入和已读取配置已保留，请刷新后再创建草稿。") } /> : null}
    {showCloudForm ? <CloudTaskForm config={latestConfig} project={project} operation={cloudOperation} enabled={cloudConfigured && capabilities.data?.enabled === true && !cloudReadFailed && !localStreamBlocked} sharedFields={{ title, objective }} resourcesHref={`/projects/${projectId}/cloud?tab=resources`} onCreated={(taskId) => { void cache.invalidateQueries({ queryKey: ["cloud-directory", projectId] }); router.push(`/cloud-tasks/${taskId}?projectId=${projectId}`); }} /> : loadingCloud && !cloudReadFailed ? <WorkspaceLoading label={t("Loading Cloud configuration…", "正在读取云端配置…")} /> : null}
  </div><Button onClick={() => router.push(`/projects/${projectId}`)} style={{ marginTop: 20 }}>{t("Back to project", "返回项目")}</Button></>;
}
