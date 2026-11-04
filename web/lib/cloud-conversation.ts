import { CloudApiError, cloudInputIdentity, cloudRequest } from "./cloud";
import { createOperationJournal } from "./operation-journal";
import { createUuid } from "./uuid";

export type ConversationMessage = {
  id: string; cursor: number; role: "ASSISTANT" | "USER" | "SYSTEM";
  text: string; status: "RECORDED" | "QUEUED" | "DELIVERING" | "DELIVERED" | "UNKNOWN" | "REJECTED" | "CANCELLED";
  created_at: string; observed_at?: string | null; session_id: string; generation: number; source: string; reason_code?: string | null;
  project_id: string; task_id: string; attempt_id: string; operation_key?: string | null;
};
export type ConversationSession = {
  state: string; can_send: boolean; generation: number; session_id: string | null; blocking_reasons: string[];
  can_reconnect?: boolean; mode?: string;
};
export type ConversationPage = {
  messages: ConversationMessage[]; next_cursor: number; has_more?: boolean; session: ConversationSession; observed_at: string;
};
export type ConversationTarget = { project_id: string; task_id: string; attempt_id: string };
export type PendingConversationMessage = ConversationTarget & {
  operation_key: string; text_digest: string; state: "SENT" | "UNKNOWN"; generation?: number;
};

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export const conversationJournal = createOperationJournal<PendingConversationMessage>("cloud-conversation", (value, projectId) => {
  const row = value as Partial<PendingConversationMessage> | null;
  if (!row || row.project_id !== projectId || !uuid.test(projectId) || !uuid.test(row.task_id || "") || !uuid.test(row.attempt_id || "")
      || (row.generation !== undefined && (!Number.isSafeInteger(row.generation) || row.generation < 1)) || !/^web:[a-f0-9-]{36}$/i.test(row.operation_key || "")
      || !/^[a-f0-9]{64}$/.test(row.text_digest || "") || !["SENT", "UNKNOWN"].includes(String(row.state))) {
    throw new Error("CONVERSATION_JOURNAL_INVALID");
  }
  // Persist only identity and a digest, never message content or credentials.
  return { project_id: row.project_id, task_id: row.task_id!, attempt_id: row.attempt_id!, ...(row.generation !== undefined ? { generation: row.generation } : {}),
    operation_key: row.operation_key!, text_digest: row.text_digest!, state: row.state! };
}, (row) => `${row.task_id}:${row.attempt_id}`);

const base = (taskId: string) => `tasks/${encodeURIComponent(taskId)}/conversation`;

export async function readConversation(projectId: string, taskId: string, attemptId: string, after: number): Promise<ConversationPage> {
  const query = new URLSearchParams({ project_id: projectId, attempt_id: attemptId, after: String(after) });
  const page = await cloudRequest<ConversationPage>(`${base(taskId)}?${query}`);
  if (!Array.isArray(page.messages) || !Number.isSafeInteger(page.next_cursor) || page.next_cursor < after || !page.session
      || typeof page.session.can_send !== "boolean" || !Array.isArray(page.session.blocking_reasons)
      || page.messages.some((row) => row.project_id !== projectId || row.task_id !== taskId || row.attempt_id !== attemptId
        || typeof row.id !== "string" || !Number.isSafeInteger(row.cursor) || row.cursor > page.next_cursor
        || typeof row.text !== "string" || !["ASSISTANT", "USER", "SYSTEM"].includes(row.role))) {
    throw new Error("CONVERSATION_READBACK_MISMATCH");
  }
  return page;
}

/** Delivery revisions replace the same message, without changing chronological order. */
export function mergeConversationMessages(previous: ConversationMessage[], incoming: ConversationMessage[]): ConversationMessage[] {
  const rows = new Map(previous.map((row) => [row.id, row]));
  for (const row of incoming) {
    const old = rows.get(row.id);
    if (!old || row.cursor > old.cursor) rows.set(row.id, row);
  }
  return [...rows.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id.localeCompare(b.id));
}

function matches(original: PendingConversationMessage, message: ConversationMessage): boolean {
  return message.role === "USER" && message.project_id === original.project_id && message.task_id === original.task_id
    && message.attempt_id === original.attempt_id
    && message.operation_key === original.operation_key && typeof message.text === "string"
    && cloudInputIdentity({ text: message.text }) === original.text_digest;
}

export async function reconcileConversationMessage(original: PendingConversationMessage): Promise<ConversationMessage> {
  const query = new URLSearchParams({ project_id: original.project_id, operation_key: original.operation_key });
  const message = await cloudRequest<ConversationMessage>(`${base(original.task_id)}/messages/by-key?${query}`);
  if (!matches(original, message)) throw new Error("CONVERSATION_READBACK_MISMATCH");
  await conversationJournal.settle(original);
  return message;
}

export async function sendConversationMessage(target: ConversationTarget, text: string): Promise<
  { state: "ACCEPTED"; message: ConversationMessage } | { state: "PENDING" } | { state: "REJECTED" }
> {
  const content = text.trim();
  if (!content || content.length > 16000) throw new Error("CONVERSATION_TEXT_INVALID");
  const original: PendingConversationMessage = { project_id: target.project_id, task_id: target.task_id, attempt_id: target.attempt_id, operation_key: `web:${createUuid()}`,
    text_digest: cloudInputIdentity({ text: content }), state: "SENT" };
  const reservation = await conversationJournal.reserve(original);
  if (!reservation.created) return { state: "PENDING" };
  try {
    const message = await cloudRequest<ConversationMessage>(base(target.task_id), { method: "POST",
      body: JSON.stringify({ project_id: target.project_id, attempt_id: target.attempt_id,
        operation_key: original.operation_key, text: content }) });
    if (!matches(original, message)) throw new Error("CONVERSATION_READBACK_MISMATCH");
    await conversationJournal.settle(original);
    return { state: "ACCEPTED", message };
  } catch (error) {
    if (error instanceof CloudApiError && [400, 401, 403, 404, 410, 413, 415, 422].includes(error.status)) {
      await conversationJournal.settle(original);
      return { state: "REJECTED" };
    }
    await conversationJournal.markUnknown(original);
    return { state: "PENDING" };
  }
}
