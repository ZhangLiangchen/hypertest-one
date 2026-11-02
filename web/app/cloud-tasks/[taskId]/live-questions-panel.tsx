"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import { useCallback, useEffect, useState } from "react";

import { cloudInputIdentity } from "@/lib/cloud";
import { createOperationJournal } from "@/lib/operation-journal";
import { createUuid } from "@/lib/uuid";
import { useI18n } from "@/lib/i18n";
import { LiveQuestions } from "./live-questions";
import type { LiveQuestion, LiveQuestionAnswer, LiveQuestionRequest } from "./live-questions";

type PendingAnswer = {
  project_id: string;
  task_id: string;
  question_id: string;
  operation_key: string;
  digest: string;
  state: "SENT" | "UNKNOWN";
};
type LiveItem = {
  id: string;
  attempt_id: string;
  status: string;
  questions: LiveQuestion[];
  answer_operation_key?: string | null;
  answer_digest?: string | null;
};

const journal = createOperationJournal<PendingAnswer>("cloud-live-question", (value, projectId) => {
  const item = value as Partial<PendingAnswer> | null;
  if (!item || item.project_id !== projectId || typeof item.task_id !== "string" || typeof item.question_id !== "string"
      || typeof item.operation_key !== "string" || typeof item.digest !== "string" || !["SENT", "UNKNOWN"].includes(String(item.state))) {
    throw new Error("Invalid live-question journal record");
  }
  return item as PendingAnswer;
}, (item) => `${item.task_id}:${item.question_id}`);

// Match the service's recursively key-sorted JSON digest without retaining answers in browser storage.
const canonical = (value: unknown): string => JSON.stringify(value && typeof value === "object"
  ? Array.isArray(value) ? value.map((item) => JSON.parse(canonical(item)))
    : Object.fromEntries(Object.keys(value).sort().map((key) => [key, JSON.parse(canonical((value as Record<string, unknown>)[key]))]))
  : value);

export function LiveQuestionsPanel({ projectId, taskId, attemptId, running, blocked }: {
  projectId: string; taskId: string; attemptId: string; running: boolean; blocked: boolean;
}) {
  const { t } = useI18n();
  const [pending, setPending] = useState<PendingAnswer[]>([]);
  const [journalReady, setJournalReady] = useState(false);
  const [journalError, setJournalError] = useState(false);
  const loadJournal = useCallback(async () => {
    try { setPending(await journal.read(projectId)); setJournalError(false); }
    catch { setJournalError(true); }
    finally { setJournalReady(true); }
  }, [projectId]);

  useEffect(() => {
    setJournalReady(false);
    void loadJournal();
    return journal.subscribe(projectId, () => { void loadJournal(); });
  }, [projectId, loadJournal]);

  const live = useQuery({
    queryKey: ["cloud-live-questions", projectId, taskId],
    queryFn: async (): Promise<{ items: LiveItem[] }> => {
      const response = await fetch(`/api/cloud/tasks/${encodeURIComponent(taskId)}/live-questions?project_id=${encodeURIComponent(projectId)}`, { cache: "no-store" });
      if (!response.ok) throw new Error("Live questions could not be read");
      return response.json();
    },
    refetchInterval: running ? 3000 : false,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (!live.data) return;
    for (const record of pending.filter((entry) => entry.task_id === taskId)) {
      const item = live.data.items.find((row) => row.id === record.question_id);
      if (item?.answer_operation_key === record.operation_key && item.answer_digest === record.digest) {
        void journal.settle(record).then(loadJournal).catch(() => setJournalError(true));
      }
    }
  }, [live.data, pending, taskId, loadJournal]);

  const items = live.data?.items.filter((item) => item.attempt_id === attemptId) || [];
  const outstanding = pending.find((entry) => entry.task_id === taskId);

  async function submit(questionId: string, answers: LiveQuestionAnswer[], cancelled: boolean) {
    const item = items.find((entry) => entry.id === questionId);
    if (!journalReady || journalError || blocked || live.isError || !item || item.status !== "OPEN" || outstanding) {
      throw new Error("Live question is not available");
    }
    const payload = { answers, cancelled };
    const record: PendingAnswer = { project_id: projectId, task_id: taskId, question_id: questionId,
      operation_key: `web:${createUuid()}`, digest: cloudInputIdentity(JSON.parse(canonical(payload))), state: "SENT" };
    const reservation = await journal.reserve(record);
    await loadJournal();
    if (!reservation.created) throw new Error("Another answer is awaiting reconciliation");
    let rejected = false;
    try {
      const response = await fetch(`/api/cloud/tasks/${encodeURIComponent(taskId)}/live-questions/${encodeURIComponent(questionId)}/answer`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, operation_key: record.operation_key, ...payload }),
      });
      if ([400, 401, 403, 404, 410, 413, 415, 422].includes(response.status)) {
        rejected = true;
        await journal.settle(record);
        await loadJournal();
        throw new Error("Answer was rejected");
      }
      if (!response.ok) throw new Error("Answer not confirmed");
    } catch (error) {
      if (rejected) throw error;
      await journal.markUnknown(record);
      await loadJournal();
    }
    // A response alone does not establish that this exact answer is recorded.
    await live.refetch();
  }

  if (!items.length && !live.isError && !journalError && !outstanding) return null;
  const statuses: Record<string, LiveQuestionRequest["status"]> = { OPEN: "open", ANSWERED: "answered", DELIVERING: "delivering",
    DELIVERED: "delivered", CANCELLED: "cancelled", UNKNOWN: "unknown" };
  return <div>
    {live.isError ? <Alert showIcon type="warning" message={t("Agent questions could not be refreshed.", "无法刷新 Agent 提问。")} action={<Button onClick={() => void live.refetch()}>{t("Refresh", "刷新")}</Button>} /> : null}
    {journalError ? <Alert showIcon type="error" message={t("Answer recovery storage is unavailable. Submitting is disabled.", "回答恢复记录不可用，已禁止提交。")} /> : null}
    {outstanding ? <Alert showIcon type="warning"
      message={t("The original answer is awaiting confirmation", "正在核对原回答")}
      description={t("The original request key is retained. Refresh to check its receipt; an uncertain answer will not be sent again automatically.", "已保留原请求键。请刷新核对回执；结果不明时不会自动重发回答。")}
      action={<Button onClick={() => void live.refetch()}>{t("Check receipt", "核对回执")}</Button>} /> : null}
    {items.map((item) => {
      const request: LiveQuestionRequest = { id: item.id, status: statuses[item.status] || "unknown", questions: item.questions };
      return <LiveQuestions key={request.id} request={request} blocked={blocked || !running || !journalReady || journalError || live.isError || !!outstanding}
        onSubmit={(id, answers) => submit(id, answers, false)} onCancel={(id) => submit(id, [], true)} />;
    })}
  </div>;
}
