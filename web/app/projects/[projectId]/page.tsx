"use client";

import { ArrowLeftOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";

import { errorText, getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ProjectArchiveTasks } from "./archive-tasks";
import { ProjectWorkspaceHeading } from "../project-workspace-heading";
import { ProjectNavigation, WorkspaceLoading } from "@/app/workspace-ui";

export default function ProjectPage() {
  const { t, locale } = useI18n();
  const params = useParams<{ projectId: string }>();
  const project = useQuery({
    queryKey: ["project", params.projectId],
    queryFn: () => getProject(params.projectId, true),
  });
  if (project.isLoading) return <WorkspaceLoading label={t("Loading project", "正在读取项目")} />;
  if (!project.data) {
    return (
      <main>
        <Link href="/"><ArrowLeftOutlined aria-hidden /> {t("Projects", "项目")}</Link>
        <Alert
          type="error"
          showIcon
          message={t("Unable to load project", "无法加载项目")}
          description={project.error ? errorText(project.error, locale) : t("Project not found.", "项目不存在。")}
          action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>}
          style={{ marginTop: 20 }}
        />
      </main>
    );
  }

  return (
    <main className="workspace-page">
      <ProjectWorkspaceHeading project={project.data} projectId={params.projectId} mode="local" />
      <ProjectNavigation projectId={params.projectId} active="local" />

      {project.data.deleted_at ? <Alert type="warning" showIcon message={t("This project is in the recycle bin", "此项目已移入回收站")} description={t("Restore the project to edit it or archive task artifacts.", "请先恢复项目，再编辑或归档任务产物。") } style={{ marginBottom: 20 }} /> : null}

      {project.error ? <Alert type="warning" showIcon message={t("Project refresh failed", "项目刷新失败")} description={t("Previously loaded project details remain available. Retry to get the latest state.", "已加载的项目资料仍会保留，请重试获取最新状态。")} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}

      <ProjectArchiveTasks projectId={params.projectId} projectDeleted={Boolean(project.data.deleted_at)} />



    </main>
  );
}
