"use client";

import { Button } from "antd";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { WorkspaceLoading } from "@/app/workspace-ui";
import { useI18n } from "@/lib/i18n";
import { archiveTaskHref } from "@/lib/task-url";

/** Keep links emitted by released CLIs and saved receipts readable. */
export default function ArchiveTaskRedirect() {
  const { taskId } = useParams<{ taskId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();
  const href = archiveTaskHref(taskId, search.get("projectId") || "");
  useEffect(() => { router.replace(href + window.location.hash); }, [href, router]);
  return <main className="workspace-page"><WorkspaceLoading label={t("Opening local task", "正在打开本地任务")} /><Button href={href}>{t("Open local task", "打开本地任务")}</Button></main>;
}
