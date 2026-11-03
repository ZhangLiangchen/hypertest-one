"use client";

import { useState } from "react";
import { Alert, Button, Collapse, Form, Input, Select, Typography } from "antd";
import Link from "next/link";
import { cloudSelector } from "@/lib/cloud";
import type { CloudRecord, CloudTask, CloudSelector } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import type { Project } from "@/lib/types";

type Values = { title: string; mr_url: string; sut_kind: "BRANCH" | "SHA" | "MR"; sut_ref?: string; sut_strategy: "HEAD" | "MERGE"; sut_base?: string;
  framework_kind: "BRANCH" | "SHA" | "MR"; framework_ref?: string; framework_strategy: "HEAD" | "MERGE"; framework_base?: string;
  prd: string; prd_version: string; objective: string; basic_flow: string; test_scope: string };

export function validChangeUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash
      && /\/(?:-\/merge_requests|pull)\/[1-9]\d*\/?$/.test(url.pathname);
  } catch { return false; }
}

// Preserve test content; the server derives source-read scope from current repositories.
export function editedCloudInputs(original: CloudRecord, values: Values): CloudRecord {
  const inputs = { ...original };
  delete inputs.authorization;
  for (const role of ["sut", "framework"] as const) {
    const selector = original[`${role}_selector`] as CloudSelector | undefined;
    const kind = values[`${role}_kind`], ref = values[`${role}_ref`]?.trim(), strategy = values[`${role}_strategy`], base = values[`${role}_base`];
    if (!ref) { delete inputs[`${role}_selector`]; continue; }
    if (selector?.kind !== kind || selector?.value !== ref || selector?.checkout_strategy !== strategy || (kind === "MR" && selector?.base_ref !== base)) {
      inputs[`${role}_selector`] = cloudSelector(kind, ref, strategy, base);
    }
  }
  Object.assign(inputs, { mr_url: values.mr_url.trim(), prd_markdown: values.prd, prd_version: values.prd_version,
    objective: values.objective, basic_flow: values.basic_flow, test_scope: values.test_scope });
  return inputs;
}

export function CloudTaskForm({ operation, enabled, onCreated, sharedFields, project, editTask, onCancel }: {
  operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onCreated: (taskId: string) => void;
  sharedFields?: { title: string; objective: string }; project?: Project; editTask?: CloudTask; onCancel?: () => void;
}) {
  const { t } = useI18n(); const [form] = Form.useForm<Values>(); const [issue, setIssue] = useState<string | null>(null);
  const sutKind = Form.useWatch("sut_kind", form) || "BRANCH";
  const frameworkKind = Form.useWatch("framework_kind", form) || "BRANCH";
  const missingRepositories = !project?.repository_url || !project.test_framework_repository_url;
  async function create(values: Values) {
    if (!project || missingRepositories || !enabled || operation.blocked) return;
    const title = sharedFields?.title ?? values.title;
    const objective = sharedFields?.objective ?? values.objective;
    if (!title?.trim() || !objective?.trim()) { setIssue(t("Complete the shared task title and objective first.", "请先填写任务名称和测试目标。")); return; }
    if (!validChangeUrl(values.mr_url?.trim() || "")) { setIssue(t("Enter a complete HTTPS merge request or pull request URL.", "请输入完整的 HTTPS MR 或 PR 地址。")); return; }
    setIssue(null);
    try {
      const inputs = editedCloudInputs(editTask?.inputs ?? { expected_outputs: ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"] }, { ...values, objective });
      const receipt = await operation.submit({ operation: editTask ? "UPDATE_TASK" : "CREATE_TASK", expected_version: editTask?.version ?? 0,
        ...(editTask ? { task_id: editTask.id } : {}), expected_project_version: project.row_version, title, inputs });
      if (receipt?.task_id) onCreated(receipt.task_id);
    } catch { setIssue(t("Check the source checkout references. An MR checkout requires its numeric ID and base ref.", "请核对源码检出引用。MR 检出需要数字编号及 base 引用。")); }
  }
  if (missingRepositories) return <Alert showIcon type="info" message={t("Project repository addresses are incomplete", "项目仓库地址尚未填写完整")} description={<>{t("Use Edit on the project details page to add both repositories.", "请通过项目详情页的编辑按钮填写被测对象和测试框架仓库。")}{project ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}><Link href={`/projects/${project.id}`} target="_blank" rel="noopener noreferrer">{t("Open project details in a new tab", "在新标签页打开项目详情")}</Link></Typography.Paragraph> : null}</>} />;
  const source = editTask?.inputs;
  const sut = source?.sut_selector as CloudSelector | undefined, framework = source?.framework_selector as CloudSelector | undefined;
  return <section className="overview-section workspace-panel" aria-labelledby="new-cloud-task-title">
    <Typography.Title id="new-cloud-task-title" level={2}>{editTask ? t("Edit cloud task draft", "编辑云端任务草稿") : t("Create a cloud test task", "创建云端测试任务")}</Typography.Title>
    <Typography.Paragraph className="muted">{t("Provide the change link and testing instructions. Repository addresses come from the project details. Creating a draft does not start an Agent.", "填写变更链接与测试说明，仓库地址沿用项目详情。创建草稿不会启动 Agent。")}</Typography.Paragraph>
    {issue ? <Alert showIcon type="error" message={issue} style={{ marginBottom: 20 }} /> : null}
    <Form form={form} className="workspace-form cloud-task-fields" layout="vertical" onFinish={(values) => void create(values)} scrollToFirstError initialValues={{
      title: editTask?.title, mr_url: source?.mr_url, sut_kind: sut?.kind || "BRANCH", sut_ref: sut?.value, sut_strategy: sut?.checkout_strategy || "HEAD", sut_base: sut?.base_ref,
      framework_kind: framework?.kind || "BRANCH", framework_ref: framework?.value, framework_strategy: framework?.checkout_strategy || "HEAD", framework_base: framework?.base_ref,
      prd: source?.prd_markdown, prd_version: source?.prd_version || "v1", objective: source?.objective, basic_flow: source?.basic_flow, test_scope: source?.test_scope }}>
      {!sharedFields ? <Form.Item name="title" label={t("Task title", "任务名称")} rules={[{ required: true }]}><Input maxLength={512} /></Form.Item> : null}
      <Form.Item name="mr_url" label={t("MR / PR URL", "MR / PR 地址")} extra={t("The Agent uses this link to inspect changes and identify what to test. It does not select or deploy the running SUT version.", "Agent 通过此链接检索改动，定位被测对象、目标和内容；它不代表或改变环境中的部署版本。")}
        rules={[{ required: true, whitespace: true }, { validator: (_, value) => !value || validChangeUrl(value.trim()) ? Promise.resolve() : Promise.reject(new Error(t("Enter a complete HTTPS MR or PR URL.", "请输入完整的 HTTPS MR 或 PR 地址。"))) }]}><Input maxLength={2048} placeholder="https://git.example.com/team/project/-/merge_requests/123" /></Form.Item>
      <section className="form-section" aria-labelledby="cloud-requirements-title">
        <Typography.Title id="cloud-requirements-title" level={3}>{t("Requirements and testing instructions", "需求与测试说明")}</Typography.Title>
        <Form.Item name="prd" label={t("PRD / requirements", "PRD / 需求原文")} rules={[{ required: true }]}><Input.TextArea rows={8} maxLength={262144} showCount /></Form.Item>
        <Form.Item name="prd_version" label={t("PRD version", "PRD 版本")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
        {!sharedFields ? <Form.Item name="objective" label={t("Test objective", "测试目标")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item> : null}
        <Form.Item name="basic_flow" label={t("Testing instructions / prompt", "测试说明 / Prompt")} extra={t("Describe the process and which existing test environment the Agent should use. Deployment is handled by the project's own CI.", "用 Prompt 描述测试流程及应使用的现有测试环境。被测对象由项目自己的 CI 部署。") } rules={[{ required: true }]}><Input.TextArea rows={4} maxLength={16000} /></Form.Item>
        <Form.Item name="test_scope" label={t("Test scope and exclusions", "测试范围与排除项")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      </section>
      <Collapse ghost items={[{ key: "checkout", label: t("Source checkout references (optional)", "源码检出引用（可选）"), forceRender: true, children: <>
        <Typography.Paragraph className="muted">{t("Leave blank to use each repository's default HEAD. These references prepare source context; they do not manage the deployed test environment.", "留空时使用仓库默认 HEAD。这些引用用于准备源码上下文，不管理测试环境的部署版本。")}</Typography.Paragraph>
        <div className="form-grid cloud-task-versions">{(["sut", "framework"] as const).map((role) => <section className="form-section" key={role}>
          <Typography.Title level={3}>{role === "sut" ? t("SUT repository", "被测对象仓库") : t("Test framework repository", "测试框架仓库")}</Typography.Title>
          <Typography.Paragraph className="entity-key">{role === "sut" ? project.repository_url : project.test_framework_repository_url}</Typography.Paragraph>
          <Form.Item name={`${role}_kind`} label={t("Select by", "引用方式")}><Select options={[{ value: "BRANCH", label: t("Branch", "分支") }, { value: "SHA", label: t("Full commit SHA", "完整提交 SHA") }, { value: "MR", label: "MR" }]} /></Form.Item>
          <Form.Item name={`${role}_ref`} label={t("Branch, SHA or MR number", "分支、SHA 或 MR 编号")}><Input maxLength={255} placeholder="HEAD" /></Form.Item>
          {(role === "sut" ? sutKind : frameworkKind) === "MR" ? <><Form.Item name={`${role}_base`} label={t("MR base ref", "MR base 引用")} rules={[{ required: true }]}><Input placeholder="refs/heads/main" maxLength={255} /></Form.Item><Form.Item name={`${role}_strategy`} label={t("Checkout strategy", "检出方式")}><Select options={[{ value: "HEAD", label: "HEAD" }, { value: "MERGE", label: "MERGE" }]} /></Form.Item></> : null}
        </section>)}</div>
      </> }]} />
      <div className="form-actions"><Button type="primary" htmlType="submit" disabled={!enabled || operation.blocked || operation.receipt?.operation === "CREATE_TASK" || !!sharedFields && (!sharedFields.title.trim() || !sharedFields.objective.trim())} loading={operation.busy}>{editTask ? t("Save draft changes", "保存草稿修改") : t("Create draft and review inputs", "创建草稿并核对输入")}</Button>{editTask && onCancel ? <Button onClick={onCancel} disabled={operation.busy || !!operation.pending}>{t("Cancel editing", "取消编辑")}</Button> : null}</div>
    </Form>
  </section>;
}
