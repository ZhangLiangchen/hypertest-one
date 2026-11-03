"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Popconfirm } from "antd";
import { useRouter } from "next/navigation";
import type { CloudDocument, CloudRecoverySummary, cloudOperationalView } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";

export function CloudTaskDelete({ projectId, detail, operational, recovery, operation }: {
  projectId: string; detail: CloudDocument; operational: ReturnType<typeof cloudOperationalView>;
  recovery?: CloudRecoverySummary;
  operation: ReturnType<typeof useCloudOperation>;
}) {
  const { t } = useI18n(); const router = useRouter(); const cache = useQueryClient();
  const task = detail.task;
  const blockedResolution = operational.resolutions.some((row) => ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"].includes(String(row.status)));
  const cancelledRecovery = operational.status === "RECOVERY_REQUIRED" && operational.attempt?.status === "RECOVERY_REQUIRED"
    && operational.attempt.checkpoint.cancellation_requested === true && recovery?.old_owner_fenced === true;
  const eligible = operational.valid && !task.deleted_at && (["DRAFT", "COMPLETED", "FAILED", "CANCELLED"].includes(operational.status || "") || cancelledRecovery) && !blockedResolution;
  useEffect(() => {
    if (operation.receipt?.operation !== "DELETE_TASK" || operation.receipt.task_id !== task.id) return;
    void cache.invalidateQueries({ queryKey: ["cloud-directory", projectId] });
    router.push(`/projects/${projectId}/cloud?tab=tasks`);
  }, [operation.receipt, task.id, projectId, cache, router]);
  return <Popconfirm title={t("Delete this cloud task?", "删除此云端任务？")}
    description={cancelledRecovery
      ? t("The task will be removed from the list and remain in recovery. Keep this page link to review records and continue reconciliation. Deletion does not confirm that processes stopped or resolve unknown actions.", "任务将从列表移除并保持待恢复。可保留本页链接查看记录及继续对账；删除不代表进程已停止，也不会解决未知动作。")
      : t("The task will be removed from the list. Its history and operation receipts remain available for reconciliation.", "任务将从列表中移除；历史记录和操作回执保留以供对账。")}
    okText={t("Delete", "删除")} cancelText={t("Cancel", "取消")} okButtonProps={{ danger: true, loading: operation.busy }}
    onConfirm={() => { if (eligible && !operation.blocked) void operation.submit({ operation: "DELETE_TASK", task_id: task.id, expected_version: task.version }); }}>
    <Button danger disabled={!eligible || operation.blocked} title={!eligible ? t("Delete a draft, a finished task, or a recovery task whose cancellation is recorded and writer is fenced. Refresh after requesting cancellation.", "可删除草稿、已结束任务，或已请求取消且写入权已隔离的待恢复任务；请求取消后请刷新。") : undefined}>{t("Delete task", "删除任务")}</Button>
  </Popconfirm>;
}
