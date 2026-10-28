"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { errorText, getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { TaskCreateForm } from "./task-create-form";

export default function CreateProjectTaskPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const search = useSearchParams();
  const [mode, setMode] = useState<"local" | "cloud">(search.get("mode") === "local" ? "local" : "cloud");
  const { t, locale } = useI18n();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true) });
  if (project.isLoading) return <main className="workspace-page form-page"><WorkspaceLoading label={t("Loading project", "正在读取项目")} /></main>;
  return <main className="workspace-page form-page">
    <WorkspaceHeading title={mode === "local" ? t("Create local test task", "创建本地测试任务") : t("Create cloud test task", "创建云端测试任务")}
      backHref={mode === "local" ? `/projects/${projectId}` : `/projects/${projectId}/cloud?tab=tasks`} backLabel={t("Project", "项目")}
      description={project.data ? `${t("Project", "所属项目")}: ${project.data.name}` : undefined} />
    {project.data && project.isError ? <Alert type="warning" showIcon message={t("Project refresh failed", "项目刷新失败")} description={errorText(project.error, locale)} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}
    {!project.data ? <Alert type="error" showIcon message={t("Unable to load project", "无法读取项目")} description={errorText(project.error, locale)} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} />
      : project.data.deleted_at ? <Alert type="warning" showIcon message={t("Restore the project before creating tasks", "请先恢复项目，再创建任务")} />
        : <TaskCreateForm projectId={project.data.id} project={project.data} onModeChange={setMode} />}
  </main>;
}
