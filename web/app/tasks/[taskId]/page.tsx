"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Space } from "antd";
import { useParams } from "next/navigation";

import { errorText, getSessionTask } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ProjectNavigation, WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { SessionTaskRecords } from "../task-records";
import { SessionTaskActions } from "../task-actions";
import { LocalTaskBinding } from "../local-task-binding";
import { LocalTaskCollaboration } from "../local-task-collaboration";

export default function SessionTaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { t, locale } = useI18n();
  const query = useQuery({ queryKey: ["session-task", taskId], queryFn: () => getSessionTask(taskId, undefined, true) });
  if (query.isLoading) return <main className="workspace-page"><WorkspaceLoading label={t("Loading task", "正在读取任务")} /></main>;
  if (!query.data) return <main className="workspace-page"><WorkspaceHeading title={t("Local task", "本地任务")} backHref="/" backLabel={t("Projects", "项目")} /><Alert type="error" showIcon message={t("Unable to load task", "无法读取任务")} description={errorText(query.error, locale)} action={<Button onClick={() => void query.refetch()} loading={query.isFetching}>{t("Retry", "重试")}</Button>} /></main>;
  return <main className="workspace-page">
    <WorkspaceHeading title={query.data.task.title} backHref={`/projects/${query.data.task.project_id}`} backLabel={t("Project tasks", "项目任务")}
      actions={<Space wrap><SessionTaskActions task={query.data.task} /><Button icon={<ReloadOutlined aria-hidden />} loading={query.isFetching} onClick={() => void query.refetch()}>{t("Refresh", "刷新")}</Button></Space>} />
    <ProjectNavigation projectId={query.data.task.project_id} active="local" />
    {query.data.task.deleted_at ? <Alert type="warning" showIcon message={t("This task is in the recycle bin", "此任务已移入回收站")} description={t("Cases, reports and history remain readable. Restore the task to edit it, bind a session or continue Agent synchronization.", "用例、报告和历史仍可查看。请先恢复任务，再编辑、绑定会话或继续 Agent 同步。") } style={{ marginBottom: 20 }} /> : null}
    {query.isError ? <Alert showIcon type="warning" message={t("Task refresh failed", "任务刷新失败")} description={t("Previously loaded sync records remain visible. Refresh to read the latest version.", "保留此前已读取的同步记录。请刷新以读取最新版本。") + " " + errorText(query.error, locale)} style={{ marginBottom: 20 }} /> : null}
    <LocalTaskBinding task={query.data.task} />
    <LocalTaskCollaboration task={query.data.task} />
    <SessionTaskRecords detail={query.data} />
  </main>;
}
