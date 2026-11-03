"use client";

import { useState } from "react";
import { CopyOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input, Space, Typography } from "antd";
import Link from "next/link";
import type { CloudRecord, CloudTask } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import type { Project } from "@/lib/types";
import { copyText } from "@/lib/clipboard";
import { cloudTestPrompt } from "@/lib/cloud-test-prompt";

type Values = { title: string; mr_url: string; prompt?: string };

export function validChangeUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash
      && !/\s/.test(value) && /\/(?:-\/merge_requests|pull)\/[1-9]\d*\/?$/.test(url.pathname);
  } catch { return false; }
}

// Keep existing context and source selections unless the change itself is replaced.
export function editedCloudInputs(original: CloudRecord, values: Values): CloudRecord {
  const inputs: CloudRecord = { ...original, mr_url: values.mr_url.trim(), prompt: values.prompt ?? "" };
  delete inputs.authorization;
  if (original.mr_url !== inputs.mr_url) delete inputs.sut_selector;
  return inputs;
}

function CloudTestPromptTemplate({ mrUrl }: { mrUrl: string }) {
  const { t, locale } = useI18n();
  const prompt = cloudTestPrompt(mrUrl, locale);
  const [copyResult, setCopyResult] = useState<{ text: string; state: "copied" | "failed" } | null>(null);
  const status = copyResult?.text === prompt ? copyResult.state : null;
  async function copy() {
    try { await copyText(prompt); setCopyResult({ text: prompt, state: "copied" }); }
    catch { setCopyResult({ text: prompt, state: "failed" }); }
  }
  return <details className="cloud-test-prompt">
    <summary>{t("E2E testing instructions template", "E2E 测试说明模板")}</summary>
    <div className="cloud-test-prompt-body">
      <Typography.Paragraph className="muted">{t("The MR / PR URL above is included automatically. Copy this template into Testing instructions, then replace the environment and test draft placeholders.", "自动带入上方 MR / PR 地址。复制模板到测试说明，替换测试环境和测试草稿占位内容即可。")}</Typography.Paragraph>
      <Space wrap size={16}><Button htmlType="button" icon={<CopyOutlined aria-hidden />} onClick={() => void copy()}>{t("Copy template", "复制模板")}</Button><span role="status" aria-live="polite" className="muted">{status === "copied" ? t("Copied. Paste into Testing instructions and edit.", "已复制，可粘贴到测试说明后编辑。") : null}</span></Space>
      {status === "failed" ? <Alert type="warning" showIcon message={t("Clipboard access failed. Select and copy the template below.", "无法写入剪贴板，请选中下方模板手动复制。")} /> : null}
      <Input.TextArea aria-label={t("E2E testing instructions template", "E2E 测试说明模板")} readOnly value={prompt} rows={16} spellCheck={false} onFocus={(event) => event.currentTarget.select()} />
    </div>
  </details>;
}

export function CloudTaskForm({ operation, enabled, onCreated, project, editTask, onCancel }: {
  operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onCreated: (taskId: string) => void;
  project?: Project; editTask?: CloudTask; onCancel?: () => void;
}) {
  const { t } = useI18n(); const [form] = Form.useForm<Values>(); const [issue, setIssue] = useState<string | null>(null);
  const mrUrl = Form.useWatch("mr_url", form) || "";
  const missingRepositories = !project?.repository_url || !project.test_framework_repository_url;
  async function create(values: Values) {
    if (!project || missingRepositories || !enabled || operation.blocked || operation.receipt?.operation === "CREATE_TASK") return;
    if (!values.title?.trim()) { setIssue(t("Enter a task title.", "请输入任务名称。")); return; }
    if (!validChangeUrl(values.mr_url?.trim() || "")) { setIssue(t("Enter a complete HTTPS merge request or pull request URL.", "请输入完整的 HTTPS MR 或 PR 地址。")); return; }
    setIssue(null);
    const inputs = editedCloudInputs(editTask?.inputs ?? {}, values);
    const receipt = await operation.submit({ operation: editTask ? "UPDATE_TASK" : "CREATE_TASK", expected_version: editTask?.version ?? 0,
      ...(editTask ? { task_id: editTask.id } : {}), title: values.title.trim(), expected_project_version: project.row_version, inputs });
    if (receipt?.task_id) onCreated(receipt.task_id);
  }
  if (missingRepositories) return <Alert showIcon type="info" message={t("Project repository addresses are incomplete", "项目仓库地址尚未填写完整")} description={<>{t("Use Edit on the project details page to add both repositories.", "请通过项目详情页的编辑按钮填写被测对象和测试框架仓库。")}{project ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}><Link href={`/projects/${project.id}`} target="_blank" rel="noopener noreferrer">{t("Open project details in a new tab", "在新标签页打开项目详情")}</Link></Typography.Paragraph> : null}</>} />;
  const source = editTask?.inputs;
  const legacyContext = [
    [t("Objective", "目标"), source?.objective], [t("Requirements", "需求原文"), source?.prd_markdown],
    [t("Testing instructions", "测试流程"), source?.basic_flow], [t("Scope", "范围"), source?.test_scope],
  ].filter(([, value]) => typeof value === "string" && value);
  return <section className="overview-section workspace-panel" aria-labelledby="new-cloud-task-title">
    <Typography.Title id="new-cloud-task-title" level={2}>{editTask ? t("Edit cloud task draft", "编辑云端任务草稿") : t("Test a merge request", "测试一个 MR / PR")}</Typography.Title>
    <Typography.Paragraph className="muted">{t("Paste the change link. The Agent reads the changes and plans the testing work.", "粘贴变更链接，Agent 会读取改动并规划测试工作。")}</Typography.Paragraph>
    {issue ? <Alert showIcon type="error" message={issue} style={{ marginBottom: 20 }} /> : null}
    <Form name="cloud-task" form={form} className="workspace-form cloud-task-fields" layout="vertical" onFinish={(values) => void create(values)} scrollToFirstError requiredMark="optional"
      disabled={operation.busy || !!operation.pending || operation.receipt?.operation === "CREATE_TASK"}
      initialValues={{ title: editTask?.title, mr_url: source?.mr_url, prompt: source?.prompt ?? "" }}>
      <Form.Item name="title" label={t("Task title", "任务名称")} rules={[{ required: true, whitespace: true, message: t("Enter a task title.", "请输入任务名称。") }]}><Input maxLength={512} autoFocus={!editTask} autoComplete="off" /></Form.Item>
      <Form.Item name="mr_url" label={t("MR / PR URL", "MR / PR 地址")}
        rules={[{ required: true, whitespace: true, message: t("Paste the MR or PR URL to test.", "请粘贴要测试的 MR 或 PR 地址。") }, { validator: (_, value) => !value || validChangeUrl(value.trim()) ? Promise.resolve() : Promise.reject(new Error(t("Enter a complete HTTPS MR or PR URL.", "请输入完整的 HTTPS MR 或 PR 地址。"))) }]}>
        <Input maxLength={2048} autoComplete="off" placeholder="https://git.example.com/team/project/-/merge_requests/123" />
      </Form.Item>
      <Form.Item name="prompt" label={t("Testing instructions", "测试说明")} extra={t("Add an environment, focus areas or requirements if needed. You can leave this blank.", "可补充测试环境、重点、需求或限制；没有补充时留空即可。") }>
        <Input.TextArea rows={5} maxLength={262144} placeholder={t("For example: use the staging environment, focus on asset transfers, and exclude destructive operations.", "例如：使用预发环境，重点验证资产转账，不执行破坏性操作。")}/>
      </Form.Item>
      <CloudTestPromptTemplate mrUrl={mrUrl} />
      <Typography.Paragraph className="muted">{editTask ? t("Existing source selections are retained. Changing the MR / PR link selects the new change's source.", "保留草稿已有的源码选择；更换 MR / PR 地址后使用新变更的源码。") : t("The test framework uses the latest commit on main.", "测试框架默认使用 main 最新提交。")}</Typography.Paragraph>
      {legacyContext.length ? <details className="form-section"><summary>{t("Existing requirements and context", "已有需求与上下文")}</summary>{legacyContext.map(([label, value]) => <div key={String(label)}><Typography.Text strong>{String(label)}</Typography.Text><pre className="session-literal">{String(value)}</pre></div>)}</details> : null}
      <div className="form-actions"><Button type="primary" htmlType="submit" disabled={!enabled || operation.blocked || operation.receipt?.operation === "CREATE_TASK"} loading={operation.busy}>{editTask ? t("Save draft changes", "保存草稿修改") : t("Create cloud task", "创建云端任务")}</Button>{editTask && onCancel ? <Button onClick={onCancel} disabled={operation.busy || !!operation.pending}>{t("Cancel editing", "取消编辑")}</Button> : <Typography.Text type="secondary">{t("Creates a draft; select Start test on the task page.", "创建后进入草稿，在任务页点击开始测试。")}</Typography.Text>}</div>
    </Form>
  </section>;
}
