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
    <Typography.Paragraph className="muted">{t("The Task ID identifies this record; it grants no access. Use the authorized client to bind it. Binding does not start tests or change results.", "任务 ID 用于定位记录，不授予访问权限。请使用获准客户端绑定；绑定不会启动测试或改变结果。")}</Typography.Paragraph>
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
    {!task.intended_actor_ref ? <Alert showIcon type="info" message={t("Authorize a Local client before binding", "绑定前请先授权本地客户端")} description={t("Arrange this Project's client authorization, then refresh the list and select it. Upgrade instructions are below.", "先为本项目准备客户端授权，再刷新列表并选择。客户端升级说明见下方。") } style={{ marginBottom: 20 }} /> : null}
    <Typography.Title level={3}>{t("Bind from the intended Agent session", "在获准的 Agent 会话中绑定")}</Typography.Title>
    <Alert showIcon type="warning" message={t("New binding requires Codex CLI 0.144.6 and the matching client", "新绑定需要 Codex CLI 0.144.6 及匹配客户端")} description={t("Upgrade the Project client, reload its configuration and start a new primary session, then bind through MCP in the Agent. Claude Code and DeepSeek do not currently support new Task ID binding; existing task sync remains compatible. The old local-v0.1.0 bundle lacks the new binding tools.", "先升级项目客户端、重载配置并新建主会话，再在 Agent 中调用 MCP 绑定。Claude Code 和 DeepSeek 当前不支持新任务 ID 绑定，已有任务同步仍可继续。旧版 local-v0.1.0 不含新绑定工具。") } style={{ marginBottom: 20 }} />
    <SourceClientUpgrade projectId={task.project_id} />
    <Typography.Paragraph>{t("Copy the request below to the current Agent. Ask it to fill in its real session and call hypertest_bind_task. Refresh this page after binding to check the task's status.", "复制下方请求给当前 Agent，让它补全真实会话并调用 hypertest_bind_task。绑定后刷新本页查看任务状态。")}</Typography.Paragraph>
    <Typography.Paragraph copyable={{ text: taskBindingTemplate(task) }}>{t("Copy binding request template", "复制绑定请求模板")}</Typography.Paragraph>
    <pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{taskBindingTemplate(task)}</pre>
    <Typography.Paragraph className="muted">{t("If binding is unconfirmed, ask the Agent to query the original request with hypertest_get_task_binding. Confirm it before syncing work; do not submit another bind.", "若绑定结果未确认，让 Agent 使用 hypertest_get_task_binding 查询原请求；确认后再开始同步，不要重新发起绑定。")}</Typography.Paragraph>
  </section>;
}
