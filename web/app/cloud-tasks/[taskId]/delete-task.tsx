"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Popconfirm } from "antd";
import { useRouter } from "next/navigation";
import type { CloudDocument, cloudOperationalView } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";

export function CloudTaskDelete({ projectId, detail, operational, operation }: {
  projectId: string; detail: CloudDocument; operational: ReturnType<typeof cloudOperationalView>;
  operation: ReturnType<typeof useCloudOperation>;
}) {
  const { t } = useI18n(); const router = useRouter(); const cache = useQueryClient();
  const task = detail.task;
  const blockedResolution = operational.resolutions.some((row) => ["PENDING", "RESOLVING", "RECOVERY_REQUIRED"].includes(String(row.status)));
  const eligible = operational.valid && !task.deleted_at && ["DRAFT", "COMPLETED", "FAILED", "CANCELLED"].includes(operational.status || "") && !blockedResolution;
  useEffect(() => {
    if (operation.receipt?.operation !== "DELETE_TASK" || operation.receipt.task_id !== task.id) return;
    void cache.invalidateQueries({ queryKey: ["cloud-directory", projectId] });
    router.push(`/projects/${projectId}/cloud?tab=tasks`);
  }, [operation.receipt, task.id, projectId, cache, router]);
  return <Popconfirm title={t("Delete this cloud task?", "删除此云端任务？")}
    description={t("The task will be removed from the list. Its history and operation receipts remain available for reconciliation.", "任务将从列表中移除；历史记录和操作回执保留以供对账。")}
    okText={t("Delete", "删除")} cancelText={t("Cancel", "取消")} okButtonProps={{ danger: true, loading: operation.busy }}
    onConfirm={() => void operation.submit({ operation: "DELETE_TASK", task_id: task.id, expected_version: task.version })}>
    <Button danger disabled={!eligible || operation.blocked} title={!eligible ? t("Only a draft or finished task without unresolved work can be deleted.", "仅可删除没有未决工作的草稿或已结束任务。") : undefined}>{t("Delete task", "删除任务")}</Button>
  </Popconfirm>;
}
