"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Radio, Select, Space, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { createLocalTask, errorText, getLocalTaskActors, getLocalTaskCreation } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { localTaskCreatePayload, localTaskCreateWasRejected, pendingLocalTaskCreation, validateLocalTaskCreation } from "@/lib/local-task-binding";
import type { LocalTaskCreateValues } from "@/lib/local-task-binding";
import type { LocalTaskCreate } from "@/lib/types";
import { createUuid } from "@/lib/uuid";

type TaskCreateValues = LocalTaskCreateValues & { mode: "cloud" | "local" };

export function TaskCreateForm({ projectId }: { projectId: string }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<TaskCreateValues>();
  const mode = Form.useWatch("mode", { form, preserve: true }) || "cloud";
  const selectedActor = Form.useWatch("intended_actor_ref", { form, preserve: true });
  const actors = useQuery({ queryKey: ["local-task-actors", projectId], queryFn: () => getLocalTaskActors(projectId), retry: false });
  const initialActorResolved = useRef(false);
  const request = useRef<{ signature: string; payload: LocalTaskCreate } | null>(null);
  const storageKey = `hypertest:local-task-create:${projectId}`;
  const [unresolved, setUnresolved] = useState<LocalTaskCreate | null>(null);
  const [storageError, setStorageError] = useState(false);
  const accepted = (detail: Awaited<ReturnType<typeof createLocalTask>>) => {
    try { window.sessionStorage.removeItem(storageKey); } catch { /* The accepted task can still be opened safely. */ }
    setUnresolved(null);
    queryClient.setQueryData(["session-task", detail.task.id], detail);
    void queryClient.invalidateQueries({ queryKey: ["session-task", detail.task.id] });
    void queryClient.invalidateQueries({ queryKey: ["project-tasks", projectId] });
    router.push(`/tasks/${detail.task.id}`);
  };
  const creation = useMutation({
    mutationFn: async (payload: LocalTaskCreate) => validateLocalTaskCreation(await createLocalTask(projectId, payload), projectId, payload.idempotency_key),
    onSuccess: accepted,
    onError: (error, payload) => {
      if (localTaskCreateWasRejected(error)) {
        try { window.sessionStorage.removeItem(storageKey); } catch { /* No accepted operation exists for a rejected request. */ }
      } else setUnresolved(payload);
    },
  });
  const reconciliation = useMutation({
    mutationFn: async (payload: LocalTaskCreate) => validateLocalTaskCreation(await getLocalTaskCreation(projectId, payload.idempotency_key), projectId, payload.idempotency_key),
    onSuccess: accepted,
  });
  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      if (!raw) return;
      const payload = pendingLocalTaskCreation(raw, projectId);
      initialActorResolved.current = true;
      form.setFieldsValue({ ...payload, mode: "local" });
      setUnresolved(payload);
    } catch { setStorageError(true); }
  }, [form, projectId, storageKey]);
  useEffect(() => {
    if (!actors.isSuccess || initialActorResolved.current) return;
    initialActorResolved.current = true;
    if (actors.data.items.length === 1 && !form.isFieldTouched("intended_actor_ref")) {
      form.setFieldValue("intended_actor_ref", actors.data.items[0].actor_ref);
    }
  }, [actors.isSuccess, actors.data, form]);
  const submit = (values: TaskCreateValues) => {
    if (values.mode !== "local" || creation.isPending || creation.isSuccess || unresolved || storageError) return;
    const canonical = localTaskCreatePayload(values, "");
    const signature = JSON.stringify({ project_id: projectId, ...canonical });
    if (!request.current || request.current.signature !== signature) {
      request.current = { signature, payload: localTaskCreatePayload(values, createUuid()) };
    }
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify({ project_id: projectId, payload: request.current.payload }));
      setStorageError(false);
      creation.mutate(request.current.payload);
    } catch { setStorageError(true); }
  };
  return <><Form form={form} layout="vertical" initialValues={{ mode: "cloud", title: "", objective: "", plan_markdown: "", intended_actor_ref: null }}
    disabled={creation.isPending || creation.isSuccess || Boolean(unresolved)} requiredMark="optional" onFinish={submit}
    onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}
    onValuesChange={() => { if (creation.isError) creation.reset(); }}>
    <Form.Item name="mode" label={t("Execution mode", "执行方式")}>
      <Radio.Group aria-label={t("Execution mode", "执行方式")} options={[{ value: "cloud", label: t("Cloud execution", "云端执行") }, { value: "local", label: t("Local execution", "本地执行") }]} />
    </Form.Item>
    <Form.Item name="title" label={t("Task title", "任务标题")} rules={[{ required: true, whitespace: true, message: t("Enter a task title.", "请输入任务标题。") }, { max: 512 }]}>
      <Input maxLength={512} autoFocus autoComplete="off" />
    </Form.Item>
    <Form.Item name="objective" label={t("Testing objective", "测试目标")} rules={[{ required: true, whitespace: true, message: t("Describe what this task should test.", "请描述此任务需要测试的目标。") }, { max: 16000 }]}>
      <Input.TextArea rows={4} maxLength={16000} />
    </Form.Item>
    {mode === "local" ? <>
      <Typography.Paragraph className="muted">{t("Create a task ID first, then bind it from the authorized local Agent. The Agent performs the testing; this page does not start a model or a test.", "先创建任务 ID，再从获准的本地 Agent 中绑定。测试由 Agent 执行；此页面不会启动模型或测试。")}</Typography.Paragraph>
      <Alert showIcon type="info" style={{ marginBottom: 20 }} message={t("New binding needs Codex CLI 0.144.6", "新绑定需要 Codex CLI 0.144.6")} description={t("Use the matching client and follow the task page's upgrade and binding steps after creation. Claude Code and DeepSeek existing task sync remains compatible. You can create an unbound task first.", "创建后按任务页说明升级匹配客户端，再绑定任务。Claude Code 和 DeepSeek 的已有任务同步不受影响，也可以先创建待绑定任务。") } />
      <Form.Item name="intended_actor_ref" label={t("Authorized local client", "获准绑定的本地客户端")} extra={t("Only this client's active Project authorization may claim the task. A Task ID is not a credential. You can leave this empty and authorize a client on the task page later.", "只有所选客户端持有本项目的有效授权时才能绑定。任务 ID 不是凭据。可以暂不选择，创建后再在任务页授权。") }>
        <Select allowClear loading={actors.isLoading} placeholder={t("Authorize later", "稍后授权")} options={actors.data?.items.map((actor) => ({ value: actor.actor_ref, label: actor.label }))} />
      </Form.Item>
      <Button loading={actors.isFetching} onClick={() => void actors.refetch()} style={{ marginBottom: 20 }}>{t("Refresh clients", "刷新客户端")}</Button>
      {actors.isError ? <Alert showIcon type="warning" message={t("Local clients could not be loaded", "无法读取本地客户端")} description={<>{errorText(actors.error, locale)} {t("You can still create an unbound task and authorize its client later.", "仍可先创建待绑定任务，稍后再授权客户端。")}</>} action={<Button onClick={() => void actors.refetch()} loading={actors.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}
      {!selectedActor ? <Alert showIcon type="info" message={t("The task will wait for client authorization", "任务将等待客户端授权")} description={t("Arrange an existing Project-scoped Local connection, then select its client on the task page before binding.", "先按项目的本地接入引导准备有效授权，再在任务页选择对应客户端并绑定。") } style={{ marginBottom: 20 }} /> : null}
      <Form.Item name="plan_markdown" label={t("Initial test plan (optional, Markdown)", "初始测试计划（可选，Markdown）")} rules={[{ max: 262144 }]}><Input.TextArea rows={6} maxLength={262144} /></Form.Item>
    </> : <Alert type="info" showIcon message={t("Cloud task creation is awaiting integration", "云端任务创建能力待接入")} description={t("The CloudTask service and execution form are not available in this version yet. Your shared title and objective stay here when switching modes.", "此版本尚未接入 CloudTask 服务及其执行配置。切换执行方式会保留已填写的标题和目标。") } style={{ marginBottom: 24 }} />}
    {storageError ? <Alert type="error" showIcon message={t("The pending request cannot be saved or read", "无法保存或读取未决请求")} description={t("Check browser session storage before creating a task. Preserve any earlier request key and reconcile it before creating another task.", "请检查浏览器会话存储后再创建任务。若已有请求标识，请保留并先完成查询对账，不要另建任务。") } action={<Button onClick={() => window.location.reload()}>{t("Reload page", "重载页面")}</Button>} style={{ marginBottom: 20 }} /> : null}
    {creation.isError && !unresolved ? <Alert type="error" showIcon message={t("Task was not created", "任务未创建")} description={<>{errorText(creation.error, locale)} {t("Your input is preserved. Review it before retrying.", "当前输入已保留，请检查后重试。")}</>} style={{ marginBottom: 20 }} /> : null}
    <Space wrap>
      <Button type="primary" htmlType="submit" disabled={mode !== "local" || Boolean(unresolved) || storageError || creation.isPending || creation.isSuccess} loading={creation.isPending || creation.isSuccess}>{t("Create test task", "创建测试任务")}</Button>
      <Button onClick={() => router.push(`/projects/${projectId}`)}>{t("Back to project", "返回项目")}</Button>
    </Space>
  </Form>{unresolved ? <Alert showIcon type="warning" style={{ marginTop: 24 }} message={t("Creation is unresolved: query the original request", "创建结果未决：请查询原请求")}
    description={<><Typography.Paragraph>{t("Only a read-only lookup is allowed now. A missing receipt does not authorize resubmitting or changing the request key. Your draft and key are retained in this browser tab across reloads.", "当前仅查询原请求。尚未找到回执不代表可以重发或更换请求标识。本标签页重载后仍会保留草稿和请求标识。")}</Typography.Paragraph><Typography.Text code copyable>{unresolved.idempotency_key}</Typography.Text>{reconciliation.isError ? <Typography.Paragraph type="danger">{errorText(reconciliation.error, locale)}</Typography.Paragraph> : null}</>}
    action={<Button loading={reconciliation.isPending} onClick={() => reconciliation.mutate(unresolved)}>{t("Query original request", "查询原请求")}</Button>} /> : null}</>;
}
