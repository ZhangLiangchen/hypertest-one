"use client";

import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Spin, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";

import { errorText, getSessionTask } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { SessionTaskRecords } from "../task-records";

export default function SessionTaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { t, locale } = useI18n();
  const query = useQuery({ queryKey: ["session-task", taskId], queryFn: () => getSessionTask(taskId) });
  if (query.isLoading) return <main className="pane-loading"><Spin aria-label={t("Loading task", "正在读取任务")} /></main>;
  if (!query.data) return <main><Link href="/"><ArrowLeftOutlined aria-hidden /> {t("Projects", "项目")}</Link><Alert style={{ marginTop: 20 }} type="error" showIcon message={t("Unable to load task", "无法读取任务")} description={errorText(query.error, locale)} action={<Button onClick={() => void query.refetch()} loading={query.isFetching}>{t("Retry", "重试")}</Button>} /></main>;
  return <main>
    <div className="page-heading">
      <Link href={`/projects/${query.data.task.project_id}`}><ArrowLeftOutlined aria-hidden /> {t("Project tasks", "项目任务")}</Link>
      <div className="session-task-title"><Typography.Title level={1}>{query.data.task.title}</Typography.Title><Button icon={<ReloadOutlined aria-hidden />} loading={query.isFetching} onClick={() => void query.refetch()}>{t("Refresh sync", "刷新同步")}</Button></div>
    </div>
    {query.isError ? <Alert showIcon type="warning" message={t("Task refresh failed", "任务刷新失败")} description={t("Previously loaded sync records remain visible. Refresh to read the latest version.", "保留此前已读取的同步记录。请刷新以读取最新版本。") + " " + errorText(query.error, locale)} style={{ marginBottom: 20 }} /> : null}
    <SessionTaskRecords detail={query.data} />
  </main>;
}
