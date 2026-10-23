"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Col, Form, Input, InputNumber, Row, Select, Typography } from "antd";
import Link from "next/link";
import { cloudSelector } from "@/lib/cloud";
import type { CloudConfigRevision } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";

type Values = { title: string; sut_kind: "BRANCH" | "SHA" | "MR"; sut_ref: string; sut_strategy: "HEAD" | "MERGE"; sut_base?: string;
  framework_kind: "BRANCH" | "SHA" | "MR"; framework_ref: string; framework_strategy: "HEAD" | "MERGE"; framework_base?: string;
  prd: string; prd_version: string; objective: string; basic_flow: string; test_scope: string; entrypoints: string;
  side_effect_limits: string; authorization_hours: number; total_seconds: number; accounting_unit: "REQUEST_CREDITS" | "CONSERVATIVE_MICROUNITS"; cost: number; max_attempts: number };

export function CloudTaskForm({ config: latestConfig, operation, enabled, onCreated, sharedFields, resourcesHref }: {
  config?: CloudConfigRevision; operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onCreated: (taskId: string) => void;
  sharedFields?: { title: string; objective: string }; resourcesHref?: string;
}) {
  const { t } = useI18n(); const [form] = Form.useForm<Values>(); const [issue, setIssue] = useState<string | null>(null);
  const [baselineConfig, setBaselineConfig] = useState(latestConfig);
  useEffect(() => { if (!baselineConfig && latestConfig) setBaselineConfig(latestConfig); }, [baselineConfig, latestConfig]);
  const config = baselineConfig || latestConfig;
  const sutKind = Form.useWatch("sut_kind", form) || "BRANCH";
  const frameworkKind = Form.useWatch("framework_kind", form) || "BRANCH";
  const accountingUnit = Form.useWatch("accounting_unit", form) || "REQUEST_CREDITS";
  const remote = config?.configuration.environment.connection !== "NONE";
  async function create(values: Values) {
    if (!config || !enabled || operation.blocked) return;
    const title = sharedFields?.title ?? values.title;
    const objective = sharedFields?.objective ?? values.objective;
    if (!title?.trim() || !objective?.trim()) { setIssue(t("Complete the shared task title and objective first.", "请先填写任务名称和测试目标。")); return; }
    setIssue(null);
    try {
      const receipt = await operation.submit({ operation: "CREATE_TASK", expected_version: 0, title, config_id: config.id,
        inputs: { sut_selector: cloudSelector(values.sut_kind, values.sut_ref, values.sut_strategy, values.sut_base),
          framework_selector: cloudSelector(values.framework_kind, values.framework_ref, values.framework_strategy, values.framework_base),
          prd_markdown: values.prd, prd_version: values.prd_version, objective, basic_flow: values.basic_flow,
          test_scope: values.test_scope, expected_outputs: ["ANALYSIS", "DESIGN", "CASE", "IMPLEMENTATION", "REPORT"],
          framework_entrypoints: values.entrypoints.split("\n").map((line) => line.trim()).filter(Boolean),
          authorization: { targets: [config.configuration.sut.url, config.configuration.framework.url], permitted_actions: ["git:read", "framework:execute"],
            network_targets: [], side_effect_limits: values.side_effect_limits, expires_at: new Date(Date.now() + values.authorization_hours * 3_600_000).toISOString() },
          budgets: { accounting_unit: values.accounting_unit, total_seconds: values.total_seconds, total_cost_microunits: values.cost, max_attempts: values.max_attempts, max_concurrency: 1 } } });
      if (receipt?.task_id) onCreated(receipt.task_id);
    } catch { setIssue(t("Check the version selectors. MR selection requires a numeric ID and an explicit base ref.", "请核对版本选择。MR 需要数字编号和明确的 base 引用。 ")); }
  }
  if (!config) return <Alert showIcon type="info" message={t("Save project resources first", "请先保存项目资源")} description={<>{t("A task references a specific resource revision. Add both repositories in Project resources.", "任务引用确切的资源修订，请先在项目资源中添加两个仓库。 ")}{resourcesHref ? <Typography.Paragraph style={{ marginTop: 8, marginBottom: 0 }}><Link href={resourcesHref} target="_blank" rel="noopener noreferrer">{t("Configure resources in a new tab, then refresh here", "在新标签页配置资源后返回刷新")}</Link></Typography.Paragraph> : null}</>} />;
  return <section className="overview-section" aria-labelledby="new-cloud-task-title">
    <Typography.Title id="new-cloud-task-title" level={2}>{t("Create a cloud test task", "创建云端测试任务")}</Typography.Title>
    <Typography.Paragraph className="muted">{t("Create the draft, resolve both repository versions, review their exact SHAs, then dispatch. Creating a draft does not start an Agent.", "先创建草稿，再解析双仓版本、核对确切 SHA，最后下发；创建草稿不会启动 Agent。 ")}</Typography.Paragraph>
    {latestConfig && latestConfig.id !== config.id ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("This draft retains its selected resource revision", "草稿保留原选定的资源修订")} description={t("Project defaults changed while you were editing. This task will still use the resource revision shown below; your draft has not been replaced.", "编辑期间项目默认配置已变化。本任务仍使用下方显示的资源修订，当前草稿未被替换。 ")} /> : null}
    {remote ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Selected environment is not supported by this runtime", "当前运行配置不支持所选环境")} description={t("Switch Project resources to workspace-local fixtures before dispatch. The saved remote configuration remains intact.", "请先将项目资源改为工作区内测试再下发；已保存远端配置会保留。 ")} /> : null}
    {issue ? <Alert showIcon type="error" message={issue} style={{ marginBottom: 20 }} /> : null}
    <Form form={form} layout="vertical" onFinish={(values) => void create(values)} scrollToFirstError initialValues={{ sut_kind: config.configuration.sut.default_selector.kind, sut_ref: config.configuration.sut.default_selector.value,
      framework_kind: config.configuration.framework.default_selector.kind, framework_ref: config.configuration.framework.default_selector.value,
      sut_strategy: config.configuration.sut.default_selector.checkout_strategy, sut_base: config.configuration.sut.default_selector.base_ref,
      framework_strategy: config.configuration.framework.default_selector.checkout_strategy, framework_base: config.configuration.framework.default_selector.base_ref,
      prd_version: "v1", total_seconds: 1800, accounting_unit: "REQUEST_CREDITS", cost: 1000, max_attempts: 3, authorization_hours: 24,
      side_effect_limits: "Read approved repositories; execute project tests only in the isolated workspace. No deployment, push, issue write or remote environment changes." }}>
      {!sharedFields ? <Form.Item name="title" label={t("Task title", "任务名称")} rules={[{ required: true }]}><Input maxLength={512} /></Form.Item> : null}
      <Row gutter={[24, 0]}>{(["sut", "framework"] as const).map((role) => <Col xs={24} lg={12} key={role}>
        <Typography.Title level={3}>{role === "sut" ? t("SUT version", "被测版本") : t("Framework version", "测试框架版本")}</Typography.Title>
        <Typography.Paragraph className="entity-key">{config.configuration[role].url}</Typography.Paragraph>
        <Form.Item name={`${role}_kind`} label={t("Select by", "选择方式")}><Select options={[{ value: "BRANCH", label: t("Branch / feature", "分支 / feature") }, { value: "SHA", label: t("Full commit SHA", "完整提交 SHA") }, { value: "MR", label: "MR" }]} /></Form.Item>
        <Form.Item name={`${role}_ref`} label={t("Branch, SHA or MR number", "分支、SHA 或 MR 编号")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
        {(role === "sut" ? sutKind : frameworkKind) === "MR" ? <><Form.Item name={`${role}_base`} label={t("MR base ref", "MR base 引用")} rules={[{ required: true }]}><Input placeholder="refs/heads/main" maxLength={255} /></Form.Item><Form.Item name={`${role}_strategy`} label={t("Checkout strategy", "检出方式")}><Select options={[{ value: "HEAD", label: "HEAD" }, { value: "MERGE", label: "MERGE" }]} /></Form.Item></> : null}
      </Col>)}</Row>
      <Form.Item name="prd" label={t("PRD / requirements", "PRD / 需求原文")} rules={[{ required: true }]}><Input.TextArea rows={8} maxLength={262144} showCount /></Form.Item>
      <Form.Item name="prd_version" label={t("PRD version", "PRD 版本")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
      {!sharedFields ? <Form.Item name="objective" label={t("Test objective", "测试目标")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item> : null}
      <Form.Item name="basic_flow" label={t("Basic process", "基本流程简述")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Form.Item name="test_scope" label={t("Test scope and exclusions", "测试范围与排除项")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Form.Item name="entrypoints" label={t("Approved framework commands, one per line", "允许的框架命令，每行一个")} extra={t("Use this project's existing test tools and dependencies.", "使用项目已有测试工具和依赖。 ")} rules={[{ required: true }]}><Input.TextArea rows={3} placeholder="python -m pytest tests" /></Form.Item>
      <Form.Item name="side_effect_limits" label={t("Authorized operations and side-effect limits", "授权操作与副作用限制")} rules={[{ required: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Row gutter={[24, 0]}><Col xs={24} md={12}><Form.Item name="authorization_hours" label={t("Authorization expiry in hours", "授权有效小时数")} rules={[{ required: true }]}><InputNumber min={1} max={168} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="total_seconds" label={t("Cumulative runtime limit (seconds)", "累计运行上限（秒）")} rules={[{ required: true }]}><InputNumber min={60} max={604800} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="accounting_unit" label={t("Budget accounting", "预算计量方式")} extra={t("Codex delegation requires request credits. This is a bounded request allowance, not a monetary price.", "Codex 委派需要请求额度；它表示有界请求预算，不是货币报价。")}><Select options={[{ value: "REQUEST_CREDITS", label: t("Request credits (DeepSeek + Codex)", "请求额度（DeepSeek + Codex）") }, { value: "CONSERVATIVE_MICROUNITS", label: t("Conservative micro-units (DeepSeek only)", "保守微单位（仅 DeepSeek）") }]} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="cost" label={accountingUnit === "REQUEST_CREDITS" ? t("Cumulative request-credit limit", "累计请求额度上限") : t("Cumulative cost limit (micro-units)", "累计费用上限（微单位）")} extra={t("The worker checks the configured rates and reserves the full attempt before starting a model.", "Worker 会核对已配置费率，并在启动模型前预留整次尝试的预算。")} rules={[{ required: true }]}><InputNumber min={1} max={1_000_000_000_000} style={{ width: "100%" }} /></Form.Item></Col>
        <Col xs={24} md={12}><Form.Item name="max_attempts" label={t("Maximum explicit attempts", "最多显式执行尝试")} rules={[{ required: true }]}><InputNumber min={1} max={100} style={{ width: "100%" }} /></Form.Item></Col></Row>
      <Button type="primary" htmlType="submit" disabled={!enabled || operation.blocked || operation.receipt?.operation === "CREATE_TASK" || !!sharedFields && (!sharedFields.title.trim() || !sharedFields.objective.trim())} loading={operation.busy}>{t("Create draft and review versions", "创建草稿并核对版本")}</Button>
      <Typography.Paragraph className="muted" style={{ marginTop: 16 }}>{t("Resources revision", "资源修订")}: {config.revision} · {t("Git read and workspace framework execution only. Other actions require a supported profile and new authorization.", "仅允许 Git 读取与工作区框架执行；其他动作需受支持的运行配置和新授权。 ")}</Typography.Paragraph>
    </Form>
  </section>;
}
