"use client";

import { Alert, Checkbox, Descriptions, Form, Input, Modal, Select, Typography } from "antd";
import type { ReactNode } from "react";
import type { CloudRecord, CloudTask } from "@/lib/cloud";
import { useI18n } from "@/lib/i18n";

type Values = {
  objective: string; test_scope: string; basic_flow: string; framework_entrypoints?: string;
  targets: string[]; permitted_actions: string[]; network_targets?: string[];
  side_effect_limits: string; expires_at: string;
  scope_confirmed: boolean; authorization_confirmed: boolean;
};

const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
const text = (value: unknown) => typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value, null, 2);

export function RetryDialog({ task, actions, invalid, stale, busy, notice, onCancel, onSubmit }: {
  task: CloudTask; actions?: CloudRecord[]; invalid: boolean; onCancel: () => void;
  stale: boolean; busy: boolean;
  notice?: ReactNode; onSubmit: (inputs: CloudRecord) => void;
}) {
  const { t } = useI18n();
  const [form] = Form.useForm<Values>();
  const scopeConfirmed = Form.useWatch("scope_confirmed", form);
  const authorizationConfirmed = Form.useWatch("authorization_confirmed", form);
  const oldAuthorization = task.inputs.authorization as CloudRecord | undefined;
  const actionNames = ["git:read", "git:write", "environment:read", "environment:write", "framework:execute", "ci:execute", "issue:write"];

  function submit(values: Values) {
    if (invalid || !values.scope_confirmed || !values.authorization_confirmed) return;
    const expiry = new Date(values.expires_at);
    if (!Number.isFinite(expiry.getTime()) || expiry.getTime() <= Date.now()) return;
    onSubmit({ objective: values.objective.trim(), test_scope: values.test_scope.trim(), basic_flow: values.basic_flow.trim(),
      framework_entrypoints: (values.framework_entrypoints || "").split("\n").map((item) => item.trim()).filter(Boolean),
      authorization: { targets: values.targets, permitted_actions: values.permitted_actions,
        network_targets: values.network_targets || [], side_effect_limits: values.side_effect_limits.trim(), expires_at: expiry.toISOString() } });
  }

  return <Modal open title={t("Review and dispatch a new attempt", "核对并下发新的执行尝试")} width={800}
    okText={t("Dispatch retry", "下发重试")} cancelText={t("Cancel", "取消")}
    okButtonProps={{ disabled: invalid || !scopeConfirmed || !authorizationConfirmed }} confirmLoading={busy}
    closable={!busy} maskClosable={!busy} keyboard={!busy} onCancel={onCancel} onOk={() => form.submit()}>
    <Typography.Paragraph>{t("The new attempt uses the original source versions and the scope and authorization below. It starts a new session; prior attempts and their records remain available.", "新尝试使用原源码版本及下方确认的范围和授权，启动新的会话；原尝试及其记录会保留。")}</Typography.Paragraph>
    {notice}
    <Alert showIcon type="warning" style={{ marginBottom: 16 }} message={t("Review earlier external actions before retrying", "重试前请核对此前的外部操作")}
      description={t("Do not resend an action with an unknown result. Reconcile it by its original key. The host worker uses the host user's access and does not provide strong isolation.", "结果不明的操作不能重发，须按原操作键对账。宿主 Worker 使用宿主用户的访问权限，不提供强隔离。 ")} />
    {actions?.length ? <Descriptions size="small" column={1} title={t("Actions recorded for this task", "本任务已记录的动作")}
      items={actions.map((action, index) => ({ key: String(action.identity_id ?? index), label: `${String(action.action_key ?? "—")} · ${String(action.attempt_id ?? "—")}`, children: String(action.state ?? "UNKNOWN") }))} /> : null}
    {actions?.length ? <Typography.Paragraph className="muted">{t("A business terminal state does not itself establish chain confirmation or an independently observed outcome.", "业务终态本身不代表链上确认或已独立观察到实际结果。")}</Typography.Paragraph> : null}
    <details style={{ margin: "12px 0 20px" }}><summary>{t("Review original task inputs", "查看原任务输入")}</summary>
      <Descriptions size="small" column={1} layout="vertical" items={[
        { key: "objective", label: t("Original objective", "原测试目标"), children: <span className="session-literal">{text(task.inputs.objective)}</span> },
        { key: "scope", label: t("Original scope", "原测试范围"), children: <span className="session-literal">{text(task.inputs.test_scope)}</span> },
        { key: "flow", label: t("Original execution steps", "原执行步骤"), children: <span className="session-literal">{text(task.inputs.basic_flow)}</span> },
        { key: "entrypoints", label: t("Original framework entrypoints", "原框架入口"), children: <pre className="session-literal">{text(task.inputs.framework_entrypoints)}</pre> },
        { key: "authorization", label: t("Original authorization", "原授权"), children: <pre className="session-literal">{text(task.inputs.authorization)}</pre> },
      ]} />
    </details>
    {stale ? <Alert showIcon type="warning" message={t("Task state changed or is unavailable. Close this dialog and review again.", "任务状态已变化或无法核验，请关闭窗口后重新核对。")} style={{ marginBottom: 16 }} /> : null}
    <Form form={form} layout="vertical" className="workspace-form cloud-task-fields" onFinish={submit}
      initialValues={{ targets: strings(oldAuthorization?.targets), permitted_actions: strings(oldAuthorization?.permitted_actions), network_targets: strings(oldAuthorization?.network_targets), scope_confirmed: false, authorization_confirmed: false }}
      onValuesChange={(changed) => { if (!Object.keys(changed).every((key) => key === "scope_confirmed" || key === "authorization_confirmed")) form.setFieldsValue({ scope_confirmed: false, authorization_confirmed: false }); }}>
      <Form.Item name="objective" label={t("Objective for this attempt", "本次测试目标")} rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={2} maxLength={16000} /></Form.Item>
      <Form.Item name="test_scope" label={t("Test scope and exclusions", "本次测试范围与排除项")} rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Form.Item name="basic_flow" label={t("Steps for this attempt", "本次执行步骤")} rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={4} maxLength={16000} placeholder={t("Enter the steps for this attempt; the previous command is not copied.", "填写本次执行步骤；不会自动复制上次命令。 ")} /></Form.Item>
      <Form.Item name="framework_entrypoints" label={t("Framework entrypoints, one per line (optional)", "框架入口，每行一项（可选）")} rules={[{ validator: (_, value) => (value || "").split("\n").filter((item: string) => item.trim()).length <= 32 ? Promise.resolve() : Promise.reject(new Error(t("At most 32 entries.", "最多 32 个入口。"))) }]}><Input.TextArea rows={2} maxLength={16000} /></Form.Item>
      <Typography.Title level={4}>{t("Authorization for this attempt", "本次执行授权")}</Typography.Title>
      <Form.Item name="targets" label={t("Authorized targets", "授权目标")} extra={t("Enter each target and press Enter.", "每个目标输入后按回车。 ")} rules={[{ required: true, type: "array", min: 1, max: 64 }]}><Select mode="tags" tokenSeparators={["\n"]} /></Form.Item>
      <Form.Item name="permitted_actions" label={t("Authorized actions", "授权操作")} rules={[{ required: true, type: "array", min: 1 }]}><Select mode="multiple" options={actionNames.map((value) => ({ value, label: value }))} /></Form.Item>
      <Form.Item name="network_targets" label={t("Authorized network targets", "授权网络目标")} extra={t("Enter each target and press Enter.", "每个目标输入后按回车。 ")} rules={[{ type: "array", max: 64 }]}><Select mode="tags" tokenSeparators={["\n"]} /></Form.Item>
      <Form.Item name="side_effect_limits" label={t("Side-effect limits", "副作用限制")} rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
      <Form.Item name="expires_at" label={t("Authorization expires at", "授权到期时间")} extra={t("Use your device's local time zone.", "按当前设备时区填写。 ")} rules={[{ required: true }, { validator: (_, value) => value && Number.isFinite(new Date(value).getTime()) && new Date(value).getTime() > Date.now() ? Promise.resolve() : Promise.reject(new Error(t("Choose a future time.", "请选择未来时间。"))) }]}><Input type="datetime-local" /></Form.Item>
      <Form.Item name="scope_confirmed" valuePropName="checked"><Checkbox>{t("I have reviewed and confirm this test scope.", "我已核对并确认本次测试范围。")}</Checkbox></Form.Item>
      <Form.Item name="authorization_confirmed" valuePropName="checked"><Checkbox>{t("I confirm the authorization above for this attempt.", "我确认本次尝试的上述授权。")}</Checkbox></Form.Item>
    </Form>
  </Modal>;
}
