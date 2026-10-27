"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Radio, Select, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { errorText } from "@/lib/api";
import { getArchiveActors, type ArchiveManagement } from "@/lib/archive";
import { useArchiveOperation } from "@/lib/archive-operation";
import { cloudCapabilities, cloudConfiguration, cloudSetup } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { useLocalCreateOperation } from "@/lib/local-create-operation";
import { useI18n } from "@/lib/i18n";
import { archiveTaskHref } from "@/lib/task-url";
import { WorkspaceLoading } from "@/app/workspace-ui";
import { ArchivePrompt } from "@/app/archives/archive-prompt";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";
import { CloudCapabilitiesNotice, CloudOperationNotice } from "../../cloud/cloud-shared";
import { CloudTaskForm } from "../../cloud/task-form";

type Values = { mode: "cloud" | "local"; title: string; objective: string; owner_uploader_actor_ref?: string };
export function TaskCreateForm({ projectId }: { projectId: string }) {
  const { t, locale } = useI18n(); const router = useRouter(); const search = useSearchParams(); const cache = useQueryClient(); const [form] = Form.useForm<Values>();
  const mode = Form.useWatch("mode", { form, preserve: true }) || (search.get("mode") === "local" ? "local" : "cloud");
  const title = Form.useWatch("title", { form, preserve: true }) || "", objective = Form.useWatch("objective", { form, preserve: true }) || "";
  const actors = useQuery({ queryKey: ["archive-actors", projectId], queryFn: () => getArchiveActors(projectId), retry: false });
  const local = useArchiveOperation(projectId, "create-task");
  // Preserve recovery for requests created by earlier clients, without offering a new legacy POST.
  const legacy = useLocalCreateOperation(projectId);
  const cloudOperation = useCloudOperation(projectId);
  const cloudSetupQuery = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup, retry: false });
  const cloudConfigured = cloudSetupQuery.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: cloudConfigured, retry: false });
  const configuration = useQuery({ queryKey: ["cloud-config", projectId], queryFn: () => cloudConfiguration(projectId), enabled: cloudConfigured, retry: false });
  const latestConfig = configuration.data?.items.slice().sort((a, b) => b.revision - a.revision)[0];
  const cloudReadFailed = cloudSetupQuery.isError || capabilities.isError || configuration.isError;
  const loadingCloud = cloudSetupQuery.isPending || cloudConfigured && (capabilities.isPending || configuration.isPending);
  const showCloudForm = Boolean(latestConfig) || (cloudConfigured && !loadingCloud && !cloudReadFailed);
  const localBlocked = local.blocked || Boolean(legacy.pending), cloudBlocked = cloudOperation.busy || Boolean(cloudOperation.pending) || cloudOperation.receipt?.operation === "CREATE_TASK";
  const accepted = (value: ArchiveManagement) => { void cache.invalidateQueries({ queryKey: ["archive-tasks", projectId] }); router.push(archiveTaskHref(value.task.id, projectId)); };
  async function refreshCloud() { const setup = await cloudSetupQuery.refetch(); if (setup.data?.configured) await Promise.all([capabilities.refetch(), configuration.refetch()]); }
  async function submit(values: Values) {
    if (values.mode !== "local" || localBlocked || cloudBlocked) return;
    const result = await local.manage("tasks", { title: values.title, objective: values.objective, owner_uploader_actor_ref: values.owner_uploader_actor_ref || null });
    if (result) accepted(result);
  }
  return <><section className="workspace-panel" aria-labelledby="task-details-title"><Form form={form} layout="vertical" initialValues={{ mode: search.get("mode") === "local" ? "local" : "cloud", title: "", objective: "" }}
    disabled={local.busy || Boolean(local.pending) || cloudBlocked} requiredMark="optional" onFinish={submit}
    onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}>
    <Typography.Title id="task-details-title" level={2}>{t("Task details", "任务信息")}</Typography.Title>
    <Form.Item name="mode" label={t("Execution mode", "执行方式")}><Radio.Group options={[{ value: "cloud", label: t("Cloud execution", "云端执行") }, { value: "local", label: t("Local archive", "本地归档") }]} /></Form.Item>
    <Form.Item name="title" label={t("Task title", "任务标题")} rules={[{ required: true, whitespace: true, message: t("Enter a task title.", "请输入任务标题。") }, { max: 512 }]}><Input maxLength={512} autoFocus autoComplete="off" /></Form.Item>
    <Form.Item name="objective" label={t("Testing objective", "测试目标")} rules={[{ required: true, whitespace: true, message: t("Describe the testing objective.", "请描述测试目标。") }, { max: 16000 }]}><Input.TextArea rows={4} maxLength={16000} /></Form.Item>
    {mode === "local" ? <div className="form-section"><Typography.Title level={3}>{t("Archive destination", "归档目标")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Testing runs independently on your local Agent. Create the archive when you are ready to upload; subtasks are optional and can be added later.", "测试由本地 Agent 独立完成。准备上传时创建归档任务，子任务可在任务页按需添加。")}</Typography.Paragraph>
      <Form.Item name="owner_uploader_actor_ref" label={t("Authorized uploader", "获准上传的身份")} extra={t("A CLI grant and task ownership are both required. You may assign the uploader later, before the first archive.", "上传需要有效 CLI 授权与任务所有权。也可创建后、首次归档前指定上传身份。") }><Select allowClear loading={actors.isLoading} placeholder={t("Authorize later", "稍后授权")} options={actors.data?.items.map((actor) => ({ value: actor.actor_ref, label: actor.label }))} /></Form.Item>
      <Space wrap style={{ marginBottom: 20 }}><Button onClick={() => void actors.refetch()} loading={actors.isFetching}>{t("Refresh uploaders", "刷新上传身份")}</Button><Link href={`/cli-authorizations?projectId=${projectId}#cli-install`} target="_blank" rel="noopener noreferrer">{t("CLI installation prompt & authorization (new tab)", "CLI 安装 Prompt 与授权（新标签页）")}</Link></Space>
      {actors.isError ? <Alert type="warning" showIcon message={t("Uploaders could not be loaded", "无法读取上传身份")} description={errorText(actors.error, locale)} style={{ marginBottom: 20 }} /> : null}
      <Button htmlType="submit" type="primary" disabled={localBlocked || cloudBlocked} loading={local.busy}>{t("Create archive task", "创建归档任务")}</Button>
    </div> : null}
  </Form></section>
  {mode === "local" ? <section className="workspace-panel archive-section" style={{ marginTop: 24 }}><Typography.Title level={2}>{t("Archive prompt template", "归档 Prompt 模板")}</Typography.Title><ArchivePrompt projectId={projectId} /></section> : null}
  <ArchiveOperationNotice operation={local} onAccepted={(value) => accepted(value as ArchiveManagement)} />
  {legacy.pending ? <Alert type="warning" showIcon style={{ marginTop: 20 }} message={t("An earlier local creation is unresolved", "旧本地任务创建仍未决")} description={<Typography.Text code copyable>{legacy.pending.idempotency_key}</Typography.Text>} action={<Button loading={legacy.busy} onClick={() => void legacy.reconcile().then((detail) => { if (detail) router.push(`/tasks/${detail.task.id}`); })}>{t("Query original request", "查询原请求")}</Button>} /> : null}
  <CloudOperationNotice operation={cloudOperation} />
  <div hidden={mode !== "cloud"} style={{ marginTop: 24 }}><Space wrap style={{ marginBottom: 20 }}><Button onClick={() => void refreshCloud()} loading={cloudSetupQuery.isFetching || capabilities.isFetching || configuration.isFetching}>{t("Refresh Cloud configuration", "刷新云端配置")}</Button>{latestConfig ? <Link href={`/projects/${projectId}/cloud?tab=resources`} target="_blank" rel="noopener noreferrer">{t("Project resources (new tab)", "项目资源（新标签页）")}</Link> : null}</Space>
    {!cloudSetupQuery.isPending && !cloudSetupQuery.isError && (!cloudConfigured || capabilities.data?.enabled === false) ? <CloudCapabilitiesNotice configured={cloudConfigured} capabilities={capabilities.data} /> : null}
    {cloudReadFailed ? <Alert showIcon type="error" style={{ marginBottom: 20 }} message={t("Cloud configuration could not be refreshed", "无法刷新云端配置")} description={t("Your inputs and loaded configuration are preserved. Refresh before creating a draft.", "当前输入和已读取配置已保留，请刷新后再创建草稿。") } /> : null}
    {showCloudForm ? <CloudTaskForm config={latestConfig} operation={cloudOperation} enabled={cloudConfigured && capabilities.data?.enabled === true && !cloudReadFailed && !localBlocked} sharedFields={{ title, objective }} resourcesHref={`/projects/${projectId}/cloud?tab=resources`} onCreated={(taskId) => { void cache.invalidateQueries({ queryKey: ["cloud-directory", projectId] }); router.push(`/cloud-tasks/${taskId}?projectId=${projectId}`); }} /> : loadingCloud && !cloudReadFailed ? <WorkspaceLoading label={t("Loading Cloud configuration…", "正在读取云端配置…")} /> : null}
  </div><Button onClick={() => router.push(`/projects/${projectId}`)} style={{ marginTop: 20 }}>{t("Back to project", "返回项目")}</Button></>;
}
