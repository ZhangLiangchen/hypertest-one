"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Form, Input, Select, Typography, message } from "antd";
import { useEffect, useState } from "react";

import { ManagementButtons, ManagementDialog } from "@/app/record-management";
import type { ManagementMode } from "@/app/record-management";
import { deleteProject, restoreProject, updateProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { projectEditPayload } from "@/lib/record-management";
import type { ProjectEditValues } from "@/lib/record-management";
import type { Project, ProjectUpdate } from "@/lib/types";

type ProjectAction = { mode: ManagementMode; record: Project };

export function ProjectActions({ project, compact }: { project: Project; compact?: boolean }) {
  const { t, label } = useI18n();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<ProjectAction | null>(null);
  const [form] = Form.useForm<ProjectEditValues & { status: "ACTIVE" | "ARCHIVED" }>();
  useEffect(() => {
    if (!action || action.mode === "delete" || action.mode === "restore") return;
    const record = action.record;
    form.resetFields();
    form.setFieldsValue({ name: record.name, description: record.description || "", repository_url: record.repository_url || "", default_branch: record.default_branch, status: record.status as "ACTIVE" | "ARCHIVED" });
  }, [action, form]);
  const [notice, contextHolder] = message.useMessage();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["projects"] });
    void queryClient.invalidateQueries({ queryKey: ["project", project.id] });
  };
  const mutation = useMutation({
    mutationFn: ({ mode, record, payload }: ProjectAction & { payload?: ProjectUpdate }) => mode === "delete"
      ? deleteProject(record.id, record.row_version) : mode === "restore" ? restoreProject(record.id, record.row_version) : updateProject(record.id, payload!),
    onSuccess: (saved, request) => {
      queryClient.setQueryData(["project", saved.id], saved);
      refresh();
      setAction(null);
      void notice.success(request.mode === "delete" ? t("Project moved to recycle bin.", "项目已移入回收站。")
        : request.mode === "restore" ? t("Project restored.", "项目已恢复。") : t("Project updated.", "项目已更新。"));
    },
  });
  const open = (mode: ManagementMode) => {
    mutation.reset();
    setAction({ mode, record: { ...project } });
  };
  const submit = async () => {
    if (!action || mutation.isPending) return;
    if (["delete", "restore"].includes(action.mode)) { mutation.mutate(action); return; }
    try {
      const values = await form.validateFields();
      mutation.mutate({ ...action, payload: action.mode === "status" ? { expected_version: action.record.row_version, status: values.status } : projectEditPayload(values, action.record.row_version) });
    } catch { /* Keep the draft and show field validation. */ }
  };
  const title = action?.mode === "delete" ? t("Delete project", "删除项目") : action?.mode === "restore" ? t("Restore project", "恢复项目") : action?.mode === "status" ? t("Change project status", "修改项目状态") : t("Edit project", "编辑项目");
  return <>{contextHolder}<ManagementButtons compact={compact} deleted={Boolean(project.deleted_at)} subject={project.name} onAction={open} />
    <ManagementDialog open={Boolean(action)} title={title} mode={action?.mode} version={action?.record.row_version} pending={mutation.isPending} error={mutation.error} onRefresh={refresh} onCancel={() => { if (!mutation.isPending) setAction(null); }} onConfirm={() => void submit()}>
      <Typography.Paragraph className="management-subject">{action?.record.name} <Typography.Text className="entity-key">{action?.record.key}</Typography.Text></Typography.Paragraph>
      {action?.mode === "delete" ? <Alert type="warning" showIcon message={t("Move this project to the recycle bin?", "将此项目移入回收站？")}
        description={t("Project history and its key are retained. Restore it from the project recycle bin. Projects with active tasks cannot be deleted; delete those tasks first. Projects with managed or native run history must be archived instead.", "项目历史和标识会保留，可从项目回收站恢复。有未删除任务时，请先删除这些任务；有受管或原生测试运行历史的项目，请改为归档。")}/>
        : action?.mode === "restore" ? <Typography.Paragraph>{t("Restore this project with its existing key and history. Its previous status is retained; deleted tasks remain in the task recycle bin.", "恢复项目及原有标识和历史，沿用删除前的状态；已删除任务仍留在任务回收站。")}</Typography.Paragraph>
        : <Form form={form} layout="vertical" disabled={mutation.isPending} requiredMark="optional" onFinish={() => void submit()}>
          {action?.mode === "status" ? <>
            <Form.Item name="status" label={t("Project status", "项目状态")} rules={[{ required: true }]}><Select options={["ACTIVE", "ARCHIVED"].map((value) => ({ value, label: label(value) }))} /></Form.Item>
            <Typography.Paragraph className="muted">{t("Archiving organizes the project without deleting its tasks or history.", "归档用于整理项目，任务与历史会保留。")}</Typography.Paragraph>
          </> : <>
            <Typography.Paragraph className="muted">{t("The project key stays fixed. Repository changes apply to future run drafts; saved run snapshots remain intact.", "项目标识保持固定。仓库修改用于后续新建运行的预填，已保存运行的快照会保留。")}</Typography.Paragraph>
            <Form.Item name="name" label={t("Project name", "项目名称")} rules={[{ required: true, whitespace: true, message: t("Enter a project name.", "请输入项目名称。") }, { max: 255 }]}><Input maxLength={255} autoFocus /></Form.Item>
            <Form.Item name="description" label={t("Description", "项目描述")} rules={[{ max: 16000 }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item>
            <Form.Item name="repository_url" label={t("Repository origin", "仓库源地址（origin）")} extra={t("Use an origin address without embedded credentials. Leave blank to clear it.", "填写不包含凭据的 origin 地址；留空可清除。") } rules={[{ max: 2048 }]}><Input maxLength={2048} /></Form.Item>
            <Form.Item name="default_branch" label={t("Default branch", "默认分支")} rules={[{ required: true, whitespace: true, message: t("Enter the default branch.", "请输入默认分支。") }, { max: 255 }]}><Input maxLength={255} /></Form.Item>
          </>}
        </Form>}
    </ManagementDialog>
  </>;
}
