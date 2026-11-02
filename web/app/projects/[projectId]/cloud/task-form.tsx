"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Checkbox, Form, Input, Select, Typography } from "antd";
import Link from "next/link";
import { cloudSelector, projectContainsCloudRepository } from "@/lib/cloud";
import type { CloudConfigRevision, CloudRecord, CloudTask, CloudSelector } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import type { Project } from "@/lib/types";

type Values = { config_id: string; confirm_resource_authorization: boolean; title: string; sut_kind: "BRANCH" | "SHA" | "MR"; sut_ref: string; sut_strategy: "HEAD" | "MERGE"; sut_base?: string;
  framework_kind: "BRANCH" | "SHA" | "MR"; framework_ref: string; framework_strategy: "HEAD" | "MERGE"; framework_base?: string;
  prd: string; prd_version: string; objective: string; basic_flow: string; test_scope: string };

// Preserve fields outside the editor, including unchanged authorization scope and expiry.
export function editedCloudInputs(original: CloudRecord, values: Values): CloudRecord {
  const inputs = { ...original };
  const setIfChanged = (key: string, value: unknown) => { if (JSON.stringify(original[key]) !== JSON.stringify(value)) inputs[key] = value; };
  for (const role of ["sut", "framework"] as const) {
    const selector = original[`${role}_selector`] as CloudSelector;
    const kind = values[`${role}_kind`], ref = values[`${role}_ref`], strategy = values[`${role}_strategy`], base = values[`${role}_base`];
    if (selector.kind !== kind || selector.value !== ref || selector.checkout_strategy !== strategy || (kind === "MR" && selector.base_ref !== base)) {
      inputs[`${role}_selector`] = cloudSelector(kind, ref, strategy, base);
    }
  }
  for (const [key, value] of Object.entries({ prd_markdown: values.prd, prd_version: values.prd_version, objective: values.objective, basic_flow: values.basic_flow, test_scope: values.test_scope })) setIfChanged(key, value);
  return inputs;
}

export function resourceAuthorizationInputs(inputs: CloudRecord, config: CloudConfigRevision): CloudRecord {
  const authorization = inputs.authorization as CloudRecord;
  if (!Array.isArray(authorization?.targets)) throw new Error("INVALID_AUTHORIZATION_TARGETS");
  const targets = [...authorization.targets];
  for (const url of [config.configuration.sut.url, config.configuration.framework.url]) if (!targets.includes(url)) targets.push(url);
  if (targets.length > 64) throw new Error("AUTHORIZATION_TARGET_LIMIT");
  return { ...inputs, authorization: { ...authorization, targets } };
}

export function CloudTaskForm({ config: latestConfig, operation, enabled, onCreated, sharedFields, resourcesHref, project, editTask, onCancel, configOptions }: {
  config?: CloudConfigRevision; operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onCreated: (taskId: string) => void;
  sharedFields?: { title: string; objective: string }; resourcesHref?: string; project?: Project; editTask?: CloudTask; onCancel?: () => void; configOptions?: CloudConfigRevision[];
}) {
  const { t } = useI18n(); const [form] = Form.useForm<Values>(); const [issue, setIssue] = useState<string | null>(null);
  const [baselineConfig, setBaselineConfig] = useState(latestConfig);
  const [selectedConfigId, setSelectedConfigId] = useState(editTask?.config_id);
  useEffect(() => { if (!baselineConfig && latestConfig) setBaselineConfig(latestConfig); }, [baselineConfig, latestConfig]);
  const originalConfig = baselineConfig || latestConfig;
  const config = editTask ? (configOptions || [originalConfig].filter(Boolean) as CloudConfigRevision[]).find((item) => item.id === selectedConfigId) : originalConfig;
  const configChanged = !!editTask && config?.id !== editTask.config_id;
  const sutKind = Form.useWatch("sut_kind", form) || "BRANCH";
  const frameworkKind = Form.useWatch("framework_kind", form) || "BRANCH";
  async function create(values: Values) {
    if (!config || !enabled || operation.blocked) return;
    const title = sharedFields?.title ?? values.title;
    const objective = sharedFields?.objective ?? values.objective;
    if (!title?.trim() || !objective?.trim()) { setIssue(t("Complete the shared task title and objective first.", "请先填写任务名称和测试目标。")); return; }
    setIssue(null);
    try {
      if (editTask) {
        if (configChanged && !values.confirm_resource_authorization) { setIssue(t("Confirm the resource and authorization change first.", "请先确认资源和授权目标的变化。")); return; }
        const inputs = editedCloudInputs(editTask.inputs, values);
        const receipt = await operation.submit({ operation: "UPDATE_TASK", task_id: editTask.id, expected_version: editTask.version, title, config_id: config.id, inputs: configChanged ? resourceAuthorizationInputs(inputs, config) : inputs });
        if (receipt?.task_id) onCreated(receipt.task_id);
        return;
      }
      const receipt = await operation.submit({ operation: "CREATE_TASK", expected_version: 0, title, config_id: config.id,
        inputs: { sut_selector: cloudSelector(values.sut_kind, values.sut_ref, values.sut_strategy, values.sut_base),
          framework_selector: cloudSelector(values.framework_kind, values.framework_ref, values.framework_strategy, values.framework_base),
          prd_markdown: values.prd, prd_version: values.prd_version, objective, basic_flow: values.basic_flow,
          test_scope: values.test_scope, expected_outputs: ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"] } });
      if (receipt?.task_id) onCreated(receipt.task_id);
    } catch (error) { setIssue(error instanceof Error && error.message === "AUTHORIZATION_TARGET_LIMIT" ? t("The new repositories would exceed the authorization target limit. Existing targets were not changed.", "新仓库将超过授权目标上限，原有目标未改变。") : t("Check the version selectors. MR selection requires a numeric ID and an explicit base ref.", "请核对版本选择。MR 需要数字编号和明确的 base 引用。")); }
  }
  if (!config) return <Alert showIcon type="info" message={t("Save project resources first", "请先保存项目资源")} description={<>{t("A task references a specific resource revision. Add both repositories in Project resources.", "任务引用确切的资源修订，请先在项目资源中添加两个仓库。 ")}{resourcesHref ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}><Link href={resourcesHref} target="_blank" rel="noopener noreferrer">{t("Configure resources in a new tab, then refresh here", "在新标签页配置资源后返回刷新")}</Link></Typography.Paragraph> : null}</>} />;
  const source = editTask?.inputs;
  const sut = source?.sut_selector as CloudSelector | undefined, framework = source?.framework_selector as CloudSelector | undefined;
  return <section className="overview-section workspace-panel" aria-labelledby="new-cloud-task-title">
    <Typography.Title id="new-cloud-task-title" level={2}>{editTask ? t("Edit cloud task draft", "编辑云端任务草稿") : t("Create a cloud test task", "创建云端测试任务")}</Typography.Title>
    <Typography.Paragraph className="muted">{editTask ? t("The existing resource revision and authorization remain unchanged unless explicitly edited. Review versions again after saving.", "除显式修改外，保留原资源修订及授权；保存后需重新核对版本。") : t("Create the draft, resolve both repository versions, review their exact SHAs, then dispatch. Creating a draft does not start an Agent.", "先创建草稿，再解析双仓版本、核对确切 SHA，最后下发；创建草稿不会启动 Agent。 ")}</Typography.Paragraph>
    {!editTask && latestConfig && latestConfig.id !== config.id ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("This draft retains its selected resource revision", "草稿保留原选定的资源修订")} description={t("Project defaults changed while you were editing. This task will still use the resource revision shown below; your draft has not been replaced.", "编辑期间项目默认配置已变化。本任务仍使用下方显示的资源修订，当前草稿未被替换。 ")} /> : null}
    {project && (!projectContainsCloudRepository(project.repository_url, config.configuration.sut.url) || !projectContainsCloudRepository(project.test_framework_repository_url, config.configuration.framework.url)) ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Saved Cloud resources differ from project repositories", "已保存的云端资源与项目仓库不同")} description={t("This task uses the saved Cloud resource revision shown below. Review the project and Cloud repository addresses if this difference is unexpected.", "本任务使用下方已保存的云端资源修订；如差异不符合预期，请核对项目及云端仓库地址。 ")} /> : null}
    {issue ? <Alert showIcon type="error" message={issue} style={{ marginBottom: 20 }} /> : null}
    <Form form={form} className="workspace-form cloud-task-fields" layout="vertical" onFinish={(values) => void create(values)} scrollToFirstError initialValues={editTask ? { config_id: editTask.config_id, confirm_resource_authorization: false, title: editTask.title, sut_kind: sut?.kind, sut_ref: sut?.value, sut_strategy: sut?.checkout_strategy, sut_base: sut?.base_ref,
      framework_kind: framework?.kind, framework_ref: framework?.value, framework_strategy: framework?.checkout_strategy, framework_base: framework?.base_ref,
      prd: source?.prd_markdown, prd_version: source?.prd_version, objective: source?.objective, basic_flow: source?.basic_flow, test_scope: source?.test_scope
    } : { sut_kind: config.configuration.sut.default_selector?.kind || "BRANCH", sut_ref: config.configuration.sut.default_selector?.value,
      framework_kind: config.configuration.framework.default_selector?.kind || "BRANCH", framework_ref: config.configuration.framework.default_selector?.value,
      sut_strategy: config.configuration.sut.default_selector?.checkout_strategy || "HEAD", sut_base: config.configuration.sut.default_selector?.base_ref,
      framework_strategy: config.configuration.framework.default_selector?.checkout_strategy || "HEAD", framework_base: config.configuration.framework.default_selector?.base_ref,
      prd_version: "v1" }}>
      {editTask ? <section className="form-section"><Typography.Title level={3}>{t("Resource revision", "资源修订")}</Typography.Title>
        <Form.Item name="config_id" label={t("Selected project resources", "选择项目资源修订")} rules={[{ required: true }]}><Select onChange={(value) => { setSelectedConfigId(value); form.setFieldValue("confirm_resource_authorization", false); }} options={(configOptions || [originalConfig].filter(Boolean) as CloudConfigRevision[]).map((item) => ({ value: item.id, label: `${t("Revision", "修订")} ${item.revision} · ${item.id}` }))} /></Form.Item>
        {configChanged && originalConfig ? <><Alert showIcon type="warning" message={t("Review the resource and authorization change", "请核对资源和授权目标变化")} description={<div><p>{t("Previous SUT", "原被测仓库")}: {originalConfig.configuration.sut.url}<br />{t("New SUT", "新被测仓库")}: {config.configuration.sut.url}</p><p>{t("Previous framework", "原测试框架")}: {originalConfig.configuration.framework.url}<br />{t("New framework", "新测试框架")}: {config.configuration.framework.url}</p><p>{t("Previous environment", "原环境")}: {originalConfig.configuration.environment.connection} · {originalConfig.configuration.environment.host || "—"}<br />{t("New environment", "新环境")}: {config.configuration.environment.connection} · {config.configuration.environment.host || "—"}</p><p>{t("Missing new repository targets will be added to the existing authorization. Existing targets, network targets, actions and expiry remain unchanged unless explicitly edited. Environment access is not newly authorized.", "缺少的新仓库目标将加入现有授权；原目标、网络目标、操作及到期时间（除非显式修改）均保留，不新增环境访问授权。")}</p></div>} />
          <Form.Item name="confirm_resource_authorization" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error(t("Confirm this change", "请确认此变更"))) }]}><Checkbox>{t("I confirm the resource revision and repository authorization targets", "我确认资源修订及仓库授权目标的变化")}</Checkbox></Form.Item></> : null}
      </section> : null}
      {!sharedFields ? <Form.Item name="title" label={t("Task title", "任务名称")} rules={[{ required: true }]}><Input maxLength={512} /></Form.Item> : null}
      <div className="form-grid cloud-task-versions">{(["sut", "framework"] as const).map((role) => <section className="form-section" key={role}>
        <Typography.Title level={3}>{role === "sut" ? t("SUT version", "被测版本") : t("Framework version", "测试框架版本")}</Typography.Title>
        <Typography.Paragraph className="entity-key">{config.configuration[role].url}</Typography.Paragraph>
        <Form.Item name={`${role}_kind`} label={t("Select by", "选择方式")}><Select options={[{ value: "BRANCH", label: t("Branch / feature", "分支 / feature") }, { value: "SHA", label: t("Full commit SHA", "完整提交 SHA") }, { value: "MR", label: "MR" }]} /></Form.Item>
        <Form.Item name={`${role}_ref`} label={t("Branch, SHA or MR number", "分支、SHA 或 MR 编号")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
        {(role === "sut" ? sutKind : frameworkKind) === "MR" ? <><Form.Item name={`${role}_base`} label={t("MR base ref", "MR base 引用")} rules={[{ required: true }]}><Input placeholder="refs/heads/main" maxLength={255} /></Form.Item><Form.Item name={`${role}_strategy`} label={t("Checkout strategy", "检出方式")}><Select options={[{ value: "HEAD", label: "HEAD" }, { value: "MERGE", label: "MERGE" }]} /></Form.Item></> : null}
      </section>)}</div>
      <section className="form-section" aria-labelledby="cloud-requirements-title">
      <Typography.Title id="cloud-requirements-title" level={3}>{t("Requirements and scope", "需求与范围")}</Typography.Title>
      <Form.Item name="prd" label={t("PRD / requirements", "PRD / 需求原文")} rules={[{ required: true }]}><Input.TextArea rows={8} maxLength={262144} showCount /></Form.Item>
      <Form.Item name="prd_version" label={t("PRD version", "PRD 版本")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
      {!sharedFields ? <Form.Item name="objective" label={t("Test objective", "测试目标")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item> : null}
      <Form.Item name="basic_flow" label={t("Basic process", "基本流程简述")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Form.Item name="test_scope" label={t("Test scope and exclusions", "测试范围与排除项")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      </section>
      <div className="form-actions"><Button type="primary" htmlType="submit" disabled={!enabled || operation.blocked || operation.receipt?.operation === "CREATE_TASK" || !!sharedFields && (!sharedFields.title.trim() || !sharedFields.objective.trim())} loading={operation.busy}>{editTask ? t("Save draft changes", "保存草稿修改") : t("Create draft and review versions", "创建草稿并核对版本")}</Button>{editTask && onCancel ? <Button onClick={onCancel} disabled={operation.busy || !!operation.pending}>{t("Cancel editing", "取消编辑")}</Button> : null}<span className="cloud-task-resource-revision muted">{t("Resources revision", "资源修订")}: {config.revision}</span></div>
    </Form>
  </section>;
}
