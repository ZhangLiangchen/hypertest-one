"use client";

import { Alert } from "antd";
import { useParams, useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n";
import ArchiveTaskDetail from "../archive-task-detail";
import LegacyTaskDetail from "../legacy-task-detail";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function LocalTaskPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const search = useSearchParams();
  const { t } = useI18n();
  const mode = search.get("mode");
  if (mode === "archive") {
    const projectId = search.get("projectId") || "";
    if (!uuid.test(projectId) || !uuid.test(taskId)) return <main className="workspace-page"><Alert type="error" showIcon message={t("Valid Project and Task IDs are required", "需要有效的项目与任务 ID")} description={t("Open this task from its Project workspace.", "请从所属项目工作区打开此任务。")} /></main>;
    return <ArchiveTaskDetail key={`${projectId}:${taskId}`} projectId={projectId} taskId={taskId} />;
  }
  if (mode) return <main className="workspace-page"><Alert type="error" showIcon message={t("Unknown local task mode", "无法识别本地任务类型")} description={t("Open this task from its Project workspace.", "请从所属项目工作区打开此任务。")} /></main>;
  return <LegacyTaskDetail key={taskId} taskId={taskId} />;
}
