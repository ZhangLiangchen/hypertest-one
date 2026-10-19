"use client";

import { Alert, Button } from "antd";
import { useI18n } from "@/lib/i18n";
import type { BackgroundJob, RunBinding } from "@/lib/types";

export function NewRunLink({ runId, projectId, primary = false }: { runId: string; projectId: string; primary?: boolean }) {
  const { t } = useI18n();
  return <Button type={primary ? "primary" : "default"} href={`/projects/${projectId}?fromRun=${encodeURIComponent(runId)}`} style={{ height: "auto", minHeight: 36, whiteSpace: "normal" }}>{t("New round from this run", "基于本次运行创建新轮次")}</Button>;
}

export function RunNextAction({ runId, projectId, binding, jobs, questionId, ready, startDisabled, starting, answer, reviewSession, reviewTask, start }: {
  runId: string; projectId?: string; binding: RunBinding | null | undefined; jobs: BackgroundJob[];
  questionId?: string; ready: boolean; startDisabled: boolean; starting: boolean;
  answer: (id: string) => void; reviewSession: () => void; reviewTask: (id: string) => void; start: () => void;
}) {
  const { t } = useI18n();
  const latest = [...jobs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const active = jobs.find((job) => ["QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"].includes(job.status));
  if (!ready) return <Button disabled>{t("Checking task state", "正在检查任务状态")}</Button>;
  if (binding && ["CLOSED", "FAILED", "CANCELLED"].includes(binding.status)) {
    return projectId ? <NewRunLink runId={runId} projectId={projectId} primary /> : <Button disabled>{t("Checking project", "正在检查项目")}</Button>;
  }
  if (binding?.status === "RECOVERY_REQUIRED") return <Button type="primary" onClick={reviewSession}>{t("Recover original session", "恢复原会话")}</Button>;
  if (questionId) return <Button type="primary" onClick={() => answer(questionId)}>{t("Answer question", "回答问题")}</Button>;
  if (binding?.status === "WAITING_INPUT") return <Button type="primary" onClick={reviewSession}>{t("Review waiting session", "查看等待中的会话")}</Button>;
  if (active) return <Button type="primary" onClick={() => reviewTask(active.id)}>{t("View active task", "查看进行中的任务")}</Button>;
  if (latest && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(latest.status)
    && (binding?.status === "ACTIVE" || (!binding && latest.job_type === "ADVANCE_RUN"))) {
    return <Button type="primary" onClick={() => reviewTask(latest.id)}>{t("Review & retry original task", "检查并重试原任务")}</Button>;
  }
  if (binding?.status === "RESERVED") return <Button type="primary" onClick={reviewSession}>{t("Review session", "检查会话")}</Button>;
  return <Button aria-label={t("Run test cycle", "运行完整测试周期")} type="primary" disabled={startDisabled} loading={starting} onClick={start}>{t("Run test cycle", "运行完整测试周期")}</Button>;
}

export function VerdictHistoryNotice({ runId, projectId }: { runId: string; projectId?: string }) {
  const { t } = useI18n();
  return <Alert type="info" showIcon style={{ marginTop: 16, marginBottom: 16 }} message={t("Saved verdicts and reports preserve their original state", "已保存判定和报告保留原始状态")} description={t("Updating a finding does not rewrite an earlier quality decision or report. Start a new testing round to verify a fix and obtain a new decision.", "更新发现不会改写先前的质量判定或报告。验证修复并取得新结论，请创建新的测试轮次。")} action={projectId ? <NewRunLink runId={runId} projectId={projectId} /> : undefined} />;
}
