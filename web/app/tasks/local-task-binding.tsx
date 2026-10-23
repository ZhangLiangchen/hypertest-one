"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Select, Space, Typography } from "antd";
import { useState } from "react";

import { errorText, getLocalTaskActors, updateTaskBindingAuthorization } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { taskBindingTemplate } from "@/lib/local-task-binding";
import type { SessionTask, TaskBindingAuthorization } from "@/lib/types";
import { SourceClientUpgrade } from "./source-client-upgrade";

type AuthorizationDraft = { version: number; actor: string | null };

export function LocalTaskBinding({ task }: { task: SessionTask }) {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<AuthorizationDraft | null>(null);
  const unbound = task.binding_state === "UNBOUND";
  const actors = useQuery({ queryKey: ["local-task-actors", task.project_id], queryFn: () => getLocalTaskActors(task.project_id), enabled: unbound && !task.deleted_at, retry: false });
  const mutation = useMutation({
    mutationFn: (payload: TaskBindingAuthorization) => updateTaskBindingAuthorization(task.id, payload),
    onSuccess: (detail) => {
      queryClient.setQueryData(["session-task", task.id], detail);
      void queryClient.invalidateQueries({ queryKey: ["project-tasks", task.project_id] });
      setDraft(null);
    },
  });
  if (!unbound || task.deleted_at) return null;
  const actor = actors.data?.items.find((item) => item.actor_ref === task.intended_actor_ref);
  const refresh = () => {
    void actors.refetch();
    void queryClient.invalidateQueries({ queryKey: ["session-task", task.id] });
  };
  return <section className="data-surface session-record" aria-labelledby="local-task-binding-heading">
    <Typography.Title id="local-task-binding-heading" level={2}>{t("Bind your local Agent", "绑定本地 Agent")}</Typography.Title>
    <Typography.Paragraph>{t("Task ID", "任务 ID")}: <Typography.Text code copyable>{task.id}</Typography.Text></Typography.Paragraph>
    <Typography.Paragraph>{t("Authorized client", "获准绑定的客户端")}: {task.intended_actor_ref ? <>{actor?.label || task.intended_actor_ref}</> : t("Not authorized yet", "尚未授权")}</Typography.Paragraph>
    <Typography.Paragraph className="muted">{t("The Task ID identifies this record; it grants no access. Binding also requires this Project's active Local authorization and the intended client's real native parent session. Binding does not run tests or set a test result.", "任务 ID 用于定位记录，不授予访问权限。绑定还需要本项目的有效 Local 授权，以及获准客户端的真实原生父会话。绑定不会执行测试或设置测试结果。")}</Typography.Paragraph>
    {actors.isError ? <Alert showIcon type="warning" message={t("Unable to load authorized clients", "无法读取获准客户端")} description={errorText(actors.error, locale)} action={<Button loading={actors.isFetching} onClick={() => void actors.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} /> : null}
    {draft ? <div style={{ marginBlock: 20 }}>
      <Typography.Paragraph>{t("Choose the client allowed to claim this task, or clear the authorization. This change uses version ", "选择可以绑定此任务的客户端，或清除授权。本次修改使用版本 ")}{draft.version}{t(".", "。")}</Typography.Paragraph>
      <label htmlFor={`binding-actor-${task.id}`}>{t("Authorized local client", "获准绑定的本地客户端")}</label>
      <Select id={`binding-actor-${task.id}`} aria-label={t("Authorized local client", "获准绑定的本地客户端")} style={{ width: "100%", marginBlock: 8 }} allowClear disabled={mutation.isPending} loading={actors.isLoading} value={draft.actor || undefined}
        placeholder={t("No client authorized", "暂不授权客户端")} options={actors.data?.items.map((item) => ({ value: item.actor_ref, label: item.label }))}
        onChange={(value: string | undefined) => setDraft({ ...draft, actor: value || null })} />
      <Button disabled={mutation.isPending} loading={actors.isFetching} onClick={() => void actors.refetch()} style={{ marginBottom: 12 }}>{t("Refresh clients", "刷新客户端")}</Button>
      {mutation.isError ? <Alert type="error" showIcon message={t("Authorization was not updated", "绑定授权未更新")} description={<>{errorText(mutation.error, locale)} {(mutation.error as { detail?: string } | null)?.detail === "TASK_VERSION_CONFLICT" ? <p>{t("Your selection is preserved. Refresh the record, then cancel and reopen to use its latest version.", "当前选择已保留。请刷新记录后取消并重新开始，以使用最新版本。")}</p> : null}</>} action={<Button onClick={refresh}>{t("Refresh record", "刷新记录")}</Button>} style={{ marginBlock: 12 }} /> : null}
      <Space wrap><Button type="primary" disabled={mutation.isPending} loading={mutation.isPending} onClick={() => mutation.mutate({ expected_version: draft.version, intended_actor_ref: draft.actor })}>{t("Save authorization", "保存绑定授权")}</Button><Button disabled={mutation.isPending} onClick={() => setDraft(null)}>{t("Cancel", "取消")}</Button></Space>
    </div> : <Button onClick={() => { mutation.reset(); setDraft({ version: task.version, actor: task.intended_actor_ref || null }); }} style={{ marginBottom: 20 }}>{t("Change binding authorization", "修改绑定授权")}</Button>}
    {!task.intended_actor_ref ? <Alert showIcon type="info" message={t("Authorize a Local client before binding", "绑定前请先授权本地客户端")} description={t("Ask the Project administrator to arrange an existing scoped client authorization, then refresh this list. Binding also requires the matching source client described below; installing the old published bundle alone is insufficient.", "请项目管理员按现有注册流程准备本项目的客户端授权，再刷新此列表。绑定还需要下方说明的匹配源码客户端，仅安装旧公开发行包不足以绑定。") } style={{ marginBottom: 20 }} /> : null}
    <Typography.Title level={3}>{t("Bind from the intended Agent session", "在获准的 Agent 会话中绑定")}</Typography.Title>
    <Alert showIcon type="warning" message={t("A client with Task ID binding support is required", "需要支持任务 ID 绑定的客户端")} description={t("The published local-v0.1.0 bundle does not include hypertest_bind_task or hypertest_get_task_binding. Use the source client version matched to this server. After upgrading, reload its project-specific configuration and start a new native session. Missing tools do not permit falling back to automatic task creation.", "已发布的 local-v0.1.0 安装包不包含 hypertest_bind_task 和 hypertest_get_task_binding。请使用与此服务端匹配的源码版本客户端。升级后，重载项目专用配置并开始新的原生会话；缺少工具时不能改用自动创建任务绕过绑定。") } style={{ marginBottom: 20 }} />
    <SourceClientUpgrade />
    <Typography.Paragraph>{t("Ask that Agent to call hypertest_bind_task for the Task ID below. It must obtain provider and session_id from its private trusted native SessionStart record. Do not invent a session identity or reuse another session's value. Complete the placeholders before submitting this template.", "请该 Agent 调用 hypertest_bind_task 绑定下方任务 ID。provider 和 session_id 必须取自其私有受信原生 SessionStart 记录；不能编造或冒用其他会话。下方是待补全模板，不能原样提交。")}</Typography.Paragraph>
    <Typography.Paragraph copyable={{ text: taskBindingTemplate(task) }}>{t("Copy binding request template", "复制绑定请求模板")}</Typography.Paragraph>
    <pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{taskBindingTemplate(task)}</pre>
    <Typography.Paragraph className="muted">{t("Freeze the complete request and its key before binding. If the answer is lost or UNKNOWN, use hypertest_get_task_binding with that original Project and key only; do not submit another bind. After acknowledgement, use hypertest_get_task with this Task ID to verify the accepted version before synchronizing.", "绑定前固定完整请求及其 key。失答或 UNKNOWN 时，只使用 hypertest_get_task_binding 按原 Project 和原 key 查询，不重新绑定。收到回执后，使用 hypertest_get_task 按此任务 ID 核验接受版本，再开始同步。")}</Typography.Paragraph>
  </section>;
}
