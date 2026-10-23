"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Form, Input, Select, Typography, message } from "antd";
import { useEffect, useState } from "react";

import { ManagementButtons, ManagementDialog } from "@/app/record-management";
import type { ManagementMode } from "@/app/record-management";
import { deleteSessionTask, restoreSessionTask, updateSessionTask } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { TASK_STATUSES, taskEditPayload } from "@/lib/record-management";
import type { TaskEditValues } from "@/lib/record-management";
import type { SessionTask, SessionTaskStatus, SessionTaskUpdate } from "@/lib/types";

type TaskAction = { mode: ManagementMode; record: SessionTask };

export function SessionTaskActions({ task, compact }: { task: SessionTask; compact?: boolean }) {
  const { t, label } = useI18n();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<TaskAction | null>(null);
  const [form] = Form.useForm<TaskEditValues & { status: SessionTaskStatus }>();
  useEffect(() => {
    if (!action || action.mode === "delete" || action.mode === "restore") return;
    const record = action.record;
    form.resetFields();
    form.setFieldsValue({ title: record.title, objective: record.objective, plan_markdown: record.plan_markdown, status: record.status });
  }, [action, form]);
  const [notice, contextHolder] = message.useMessage();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["project-tasks", task.project_id] });
    void queryClient.invalidateQueries({ queryKey: ["session-task", task.id] });
  };
  const mutation = useMutation({
    mutationFn: ({ mode, record, payload }: TaskAction & { payload?: SessionTaskUpdate }) => mode === "delete"
      ? deleteSessionTask(record.id, record.version) : mode === "restore" ? restoreSessionTask(record.id, record.version) : updateSessionTask(record.id, payload!),
    onSuccess: (saved, request) => {
      queryClient.setQueryData(["session-task", saved.task.id], saved);
      refresh();
      setAction(null);
      void notice.success(request.mode === "delete" ? t("Task moved to recycle bin.", "任务已移入回收站。")
        : request.mode === "restore" ? t("Task restored.", "任务已恢复。") : t("Task updated. Reported results are preserved.", "任务已更新，报告结果已保留。"));
    },
  });
  const open = (mode: ManagementMode) => {
    mutation.reset();
    setAction({ mode, record: { ...task } });
  };
  const submit = async () => {
    if (!action || mutation.isPending) return;
    if (["delete", "restore"].includes(action.mode)) { mutation.mutate(action); return; }
    try {
      const values = await form.validateFields();
      mutation.mutate({ ...action, payload: action.mode === "status" ? { expected_version: action.record.version, status: values.status } : taskEditPayload(values, action.record.version) });
    } catch { /* Keep the draft and show field validation. */ }
  };
  const title = action?.mode === "delete" ? t("Delete task", "删除任务") : action?.mode === "restore" ? t("Restore task", "恢复任务") : action?.mode === "status" ? t("Change task status", "修改任务状态") : t("Edit task", "编辑任务");
  return <>{contextHolder}<ManagementButtons compact={compact} deleted={Boolean(task.deleted_at)} subject={task.title} onAction={open} />
    <ManagementDialog open={Boolean(action)} title={title} mode={action?.mode} version={action?.record.version} pending={mutation.isPending} error={mutation.error} onRefresh={refresh} onCancel={() => { if (!mutation.isPending) setAction(null); }} onConfirm={() => void submit()}>
      <Typography.Paragraph className="management-subject">{action?.record.title}</Typography.Paragraph>
      {action?.mode === "delete" ? <Alert type="warning" showIcon message={t("Move this task to the recycle bin?", "将此任务移入回收站？")}
        description={t("Cases, original reports, reported results and all revisions are retained. The Task ID and any bound session identity stay reserved. Restore the task from its project's task recycle bin to continue using it.", "用例、原始报告、报告结果及全部修订会保留，任务 ID 及已绑定的会话标识仍被占用。需要继续使用时，可从项目的任务回收站恢复。")}/>
        : action?.mode === "restore" ? <Typography.Paragraph>{t("Restore the task with its original session identity, progress, results and history. Restore its project first if that project was also deleted.", "恢复任务及原有会话标识、进度、结果和历史。如果所属项目也已删除，请先恢复项目。")}</Typography.Paragraph>
        : <Form form={form} layout="vertical" disabled={mutation.isPending} requiredMark="optional" onFinish={() => void submit()}>
          {action?.mode === "status" ? <>
            <Form.Item name="status" label={t("Task status", "任务状态")} rules={[{ required: true }]}><Select options={TASK_STATUSES.map((value) => ({ value, label: label(value) }))} /></Form.Item>
            <Alert type="info" showIcon message={t("Status tracks task progress", "任务状态表示工作进度")}
              description={t("You can reopen a completed or cancelled task. This change does not alter Agent reported results, cases or reports, and does not execute tests. Future Agent syncs must read the new task version first.", "可以重新打开已完成或已取消的任务。修改状态不改变 Agent 报告结果、用例和报告，也不执行测试。Agent 后续同步前需先读取新的任务版本。")}/>
          </> : <>
            <Typography.Paragraph className="muted">{t("Manual edits are recorded in management history. Agent session identity, cases, reports and their results are preserved.", "手动修改记录在管理历史中。Agent 会话标识、用例、报告及其结果会保留。")}</Typography.Paragraph>
            <Form.Item name="title" label={t("Task title", "任务标题")} rules={[{ required: true, whitespace: true, message: t("Enter a task title.", "请输入任务标题。") }, { max: 512 }]}><Input maxLength={512} autoFocus /></Form.Item>
            <Form.Item name="objective" label={t("Objective", "测试目标")} rules={[{ max: 16000 }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
            <Form.Item name="plan_markdown" label={t("Test plan (Markdown)", "测试计划（Markdown）")} rules={[{ max: 262144 }]}><Input.TextArea rows={9} maxLength={262144} /></Form.Item>
          </>}
        </Form>}
    </ManagementDialog>
  </>;
}
