"use client";

import { ArrowLeftOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Spin, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";

import { errorText, getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { TaskCreateForm } from "./task-create-form";

export default function CreateProjectTaskPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t, locale } = useI18n();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true) });
  if (project.isLoading) return <main className="pane-loading"><Spin aria-label={t("Loading project", "正在读取项目")} /></main>;
  return <main style={{ maxWidth: 880 }}>
    <div className="page-heading">
      <Link href={`/projects/${projectId}`}><ArrowLeftOutlined aria-hidden /> {t("Project", "项目")}</Link>
      <Typography.Title level={1}>{t("Create test task", "创建测试任务")}</Typography.Title>
      {project.data ? <Typography.Paragraph className="muted">{t("Project", "所属项目")}: {project.data.name}</Typography.Paragraph> : null}
    </div>
    {project.data && project.isError ? <Alert type="warning" showIcon message={t("Project refresh failed", "项目刷新失败")} description={errorText(project.error, locale)} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}
    {!project.data ? <Alert type="error" showIcon message={t("Unable to load project", "无法读取项目")} description={errorText(project.error, locale)} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} />
      : project.data.deleted_at ? <Alert type="warning" showIcon message={t("Restore the project before creating tasks", "请先恢复项目，再创建任务")} />
        : <div className="data-surface" style={{ padding: 24 }}><TaskCreateForm projectId={project.data.id} /></div>}
  </main>;
}
