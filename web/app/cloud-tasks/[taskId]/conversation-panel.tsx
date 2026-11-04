"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Input, Select, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { cloudInputIdentity } from "@/lib/cloud";
import type { CloudAttempt } from "@/lib/cloud";
import { conversationJournal, mergeConversationMessages, readConversation, reconcileConversationMessage, sendConversationMessage } from "@/lib/cloud-conversation";
import type { ConversationMessage, PendingConversationMessage } from "@/lib/cloud-conversation";
import { useI18n } from "@/lib/i18n";
import { LiveQuestionsPanel } from "./live-questions-panel";

type Props = {
  projectId: string; taskId: string; attempt: CloudAttempt; attempts: CloudAttempt[]; blocked: boolean;
  onArtifacts: () => void; artifactCount: number;
};

export function ConversationPanel(props: Props) {
  const { t } = useI18n();
  const [selected, setSelected] = useState(props.attempt.id);
  useEffect(() => { setSelected(props.attempt.id); }, [props.attempt.id]);
  const attempt = selected === props.attempt.id ? props.attempt : props.attempts.find((row) => row.id === selected) || props.attempt;
  return <section className="overview-section cloud-conversation" aria-labelledby="cloud-conversation-heading">
    <div className="cloud-conversation-heading">
      <div><Typography.Title id="cloud-conversation-heading" tabIndex={-1} level={2}>{t("Agent conversation", "Agent 对话")}</Typography.Title>
        <Typography.Paragraph className="muted">{t("Read the agent’s progress and reply here. Test reports are recorded separately.", "查看 Agent 的进展并在这里回复。测试报告单独归档。")}</Typography.Paragraph></div>
      <Space>
        {props.attempts.length > 1 ? <Select aria-label={t("Conversation history", "会话记录")} value={attempt.id} onChange={setSelected}
          options={props.attempts.map((row) => ({ value: row.id, label: t(`Session ${row.attempt_no}${row.id === props.attempt.id ? " · current" : " · history"}`, `会话 ${row.attempt_no}${row.id === props.attempt.id ? " · 当前" : " · 历史"}`) }))} /> : null}
        <Button onClick={props.onArtifacts}>{t(`Artifacts (${props.artifactCount})`, `产物（${props.artifactCount}）`)}</Button>
      </Space>
    </div>
    <ConversationStream key={`${props.projectId}:${props.taskId}:${attempt.id}`} {...props} attempt={attempt}
      readOnly={attempt.id !== props.attempt.id || ["COMPLETED", "FAILED", "CANCELLED"].includes(attempt.status)} />
  </section>;
}

export function conversationStatus(status: ConversationMessage["status"], t: (en: string, zh: string) => string): string {
  return ({ RECORDED: t("Recorded", "已记录"), QUEUED: t("Saved · waiting for delivery", "已保存 · 等待投递"),
    DELIVERING: t("Delivering", "正在投递"), DELIVERED: t("Delivered to the session", "已交给会话"),
    UNKNOWN: t("Delivery unconfirmed", "投递未确认"), REJECTED: t("Not accepted", "未接受"), CANCELLED: t("Cancelled", "已取消") })[status];
}

function sessionLabel(state: string | undefined, t: (en: string, zh: string) => string): string {
  const labels: Record<string, string> = {
    RUNNING: t("Agent is working", "Agent 正在执行"), ACTIVE: t("Agent is working", "Agent 正在执行"),
    AWAITING_REPLY: t("Waiting for your reply", "等待你的回复"),
    IDLE: t("Ready for your reply", "可以继续回复"), READY: t("Ready for your reply", "可以继续回复"),
    BLOCKED: t("Agent is blocked", "Agent 遇到阻塞"), OFFLINE: t("Session disconnected", "会话已断开"),
    CLOSED: t("Session ended", "会话已结束"), COMPLETED: t("Session ended", "会话已结束"),
    INTERRUPTED: t("Session interrupted", "会话已中断"), CONNECTING: t("Connecting to the session", "正在连接会话"),
    RECOVERY_REQUIRED: t("Session disconnected", "会话已断开"), UNKNOWN: t("Session status unconfirmed", "会话状态未确认"),
  };
  return labels[state || ""] || t("Checking the session", "正在核对会话");
}

function blockingMessage(reason: string, t: (en: string, zh: string) => string): string {
  const labels: Record<string, string> = {
    NO_ATTEMPT: t("The task has not started yet.", "任务尚未开始执行。"),
    TASK_DELETED: t("The task was removed; its messages remain readable.", "任务已移除，历史消息仍可查看。"),
    HISTORICAL_ATTEMPT: t("This is a previous attempt. Its conversation is read only.", "这是此前的执行尝试，对话只读。"),
    SESSION_NOT_RUNNING: t("The session is not accepting messages.", "会话当前不接收消息。"),
    SESSION_OFFLINE: t("The session is offline.", "会话已离线。"),
    AUTHORIZATION_UNAVAILABLE: t("Current authorization does not allow sending.", "当前授权不允许发送消息。"),
    SESSION_CONNECTING: t("The session is connecting; wait before sending.", "会话正在连接，请稍后发送。"),
    MESSAGE_DELIVERY_UNKNOWN: t("A previous message needs delivery confirmation.", "此前消息的投递结果仍需确认。"),
  };
  return labels[reason] || t("The session cannot receive messages in its current state.", "会话当前状态不允许接收消息。");
}

function messageText(message: ConversationMessage, t: (en: string, zh: string) => string): string {
  if (message.text) return message.text;
  if (message.reason_code === "ARTIFACT_CONTENT_REJECTED") return t("A test artifact was withheld by the content check. The Agent can correct it; existing messages remain available.", "一份测试产物未通过内容检查，Agent 可修正后重新提交；已有对话仍保留。");
  if (message.reason_code === "ARTIFACT_REJECTED") return t("A test artifact did not meet the submission contract. The Agent has received correction details; no test result was accepted.", "一份测试产物不符合提交要求，Agent 已收到修正说明；此次提交没有形成测试结果。");
  if (message.reason_code === "CONTENT_REJECTED") return t("This message was withheld by the content check.", "此消息未通过内容检查，正文未展示。");
  if (message.reason_code === "MESSAGE_TOO_LARGE") return t("The message exceeded the size limit and was not recorded.", "消息超过长度限制，正文未记录。");
  if (message.reason_code === "CONVERSATION_GAP") return t("Some agent output was not received. This conversation may be incomplete.", "部分 Agent 输出未收到，对话记录可能不完整。");
  return t("Message content is unavailable.", "消息正文不可用。");
}

function ConversationStream({ projectId, taskId, attempt, blocked, readOnly }: Props & { readOnly: boolean }) {
  const { t, formatDate } = useI18n();
  const cache = useRef<{ messages: ConversationMessage[]; cursor: number }>({ messages: [], cursor: 0 });
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingConversationMessage[]>([]);
  const [journalReady, setJournalReady] = useState(false);
  const [journalError, setJournalError] = useState(false);
  const [sending, setSending] = useState(false);
  const [issue, setIssue] = useState<"REJECTED" | "UNCONFIRMED" | null>(null);
  const [checking, setChecking] = useState(false);
  const sendingRef = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
  const refreshJournal = useCallback(async () => {
    try {
      const rows = await conversationJournal.read(projectId);
      setPending(rows.filter((row) => row.task_id === taskId && row.attempt_id === attempt.id));
      setJournalError(false); setJournalReady(true);
    } catch { setJournalError(true); setJournalReady(false); }
  }, [projectId, taskId, attempt.id]);
  useEffect(() => {
    if (readOnly) return;
    void refreshJournal();
    return conversationJournal.subscribe(projectId, () => { void refreshJournal(); });
  }, [projectId, readOnly, refreshJournal]);

  const conversation = useQuery({
    queryKey: ["cloud-conversation", projectId, taskId, attempt.id],
    queryFn: async () => {
      const page = await readConversation(projectId, taskId, attempt.id, cache.current.cursor);
      cache.current = { messages: mergeConversationMessages(cache.current.messages, page.messages), cursor: page.next_cursor };
      return { ...page, messages: cache.current.messages };
    },
    refetchInterval: readOnly ? false : 1000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  const messages = conversation.data?.messages || [];
  const session = conversation.data?.session;
  const outstanding = pending[0];
  const canSend = !readOnly && !blocked && !conversation.isError && session?.can_send === true
    && journalReady && !journalError && !outstanding && !sending;
  const lastCursor = conversation.data?.next_cursor;
  useEffect(() => {
    if (!outstanding || !messages.some((row) => row.operation_key === outstanding.operation_key)) return;
    // A persisted feed entry is a reason to read the original receipt, never to resend.
    void reconcileConversationMessage(outstanding).then(() => {
      setDraft((current) => cloudInputIdentity({ text: current.trim() }) === outstanding.text_digest ? "" : current);
      setIssue(null); return refreshJournal();
    }).catch(() => {});
  }, [messages, outstanding, refreshJournal]);
  useEffect(() => {
    if (!scroll.current) return;
    if (follow.current) { scroll.current.scrollTop = scroll.current.scrollHeight; setNewMessages(false); }
    else setNewMessages(true);
  }, [lastCursor]);

  async function checkOriginal() {
    if (!outstanding || checking) return;
    setChecking(true); setIssue(null);
    try {
      await reconcileConversationMessage(outstanding);
      setDraft((current) => cloudInputIdentity({ text: current.trim() }) === outstanding.text_digest ? "" : current);
      await conversation.refetch();
    } catch { setIssue("UNCONFIRMED"); }
    finally { await refreshJournal(); setChecking(false); }
  }

  async function send() {
    if (!canSend || !draft.trim() || sendingRef.current || !session) return;
    sendingRef.current = true; setSending(true); setIssue(null);
    try {
      const result = await sendConversationMessage({ project_id: projectId, task_id: taskId, attempt_id: attempt.id }, draft);
      if (result.state === "ACCEPTED") { setDraft(""); follow.current = true; await conversation.refetch(); }
      if (result.state === "REJECTED") { setIssue("REJECTED"); await conversation.refetch(); }
    } catch { setJournalError(true); }
    finally { await refreshJournal(); sendingRef.current = false; setSending(false); }
  }

  return <div>
    <div className="cloud-conversation-state"><Tag>{readOnly ? t("Read only", "只读") : sessionLabel(session?.state, t)}</Tag>
      {conversation.data?.observed_at ? <span className="muted">{t("Updated", "更新于")} {formatDate(conversation.data.observed_at)}</span> : null}
      <Button type="text" size="small" loading={conversation.isFetching} onClick={() => void conversation.refetch()}>{t("Refresh", "刷新")}</Button></div>
    {conversation.isError ? <Alert showIcon type="warning" message={t("Conversation could not be refreshed. Previously loaded messages remain visible.", "对话刷新失败，已加载的消息仍保留。")}/> : null}
    <div className="cloud-conversation-log" ref={scroll} role="log" aria-live="polite" aria-relevant="additions" aria-label={t("Agent messages", "Agent 消息")}
      onScroll={() => { const node = scroll.current; if (node) { follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48; if (follow.current) setNewMessages(false); } }}>
      {!messages.length ? <p className="cloud-conversation-empty">{conversation.isLoading ? t("Loading the conversation…", "正在读取对话…")
        : t("No messages have been recorded for this attempt yet. Accepted test artifacts remain available separately.", "本次尝试尚无已记录的对话消息，已归档的测试产物仍可单独查看。")}</p> : null}
      {messages.map((message) => <article key={message.id} className={`cloud-conversation-message cloud-conversation-message-${message.role.toLowerCase()}`}>
        <div className="cloud-conversation-message-heading"><strong>{message.role === "ASSISTANT" ? "Agent" : message.role === "USER" ? t("You", "你") : t("Execution status", "运行状态")}</strong>
          {message.source === "IMPORTED_HISTORY" ? <><span>{t("Imported from the original session", "原会话补录")}</span>
            {message.observed_at ? <span>{t("Original message", "原消息时间")} <time dateTime={message.observed_at}>{formatDate(message.observed_at)}</time></span>
              : <span>{t("Original time not recorded", "原消息时间未记录")}</span>}
            <span>{t("Imported", "补录时间")} <time dateTime={message.created_at}>{formatDate(message.created_at)}</time></span></>
            : <time dateTime={message.created_at}>{formatDate(message.created_at)}</time>}
          {message.role === "USER" ? <span>{conversationStatus(message.status, t)}</span> : null}</div>
        <pre className="cloud-conversation-text">{messageText(message, t)}</pre>
      </article>)}
    </div>
    {conversation.data?.has_more ? <Button className="cloud-conversation-new" loading={conversation.isFetching} onClick={() => void conversation.refetch()}>{t("Load more messages", "加载后续消息")}</Button> : null}
    {newMessages ? <Button className="cloud-conversation-new" onClick={() => { follow.current = true; if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; setNewMessages(false); }}>{t("View new messages", "查看新消息")}</Button> : null}
    <LiveQuestionsPanel projectId={projectId} taskId={taskId} attemptId={attempt.id}
      running={!readOnly && ["RUNNING", "AWAITING_REPLY"].includes(session?.state || "")} blocked={blocked || readOnly} embedded />
    {!readOnly ? <form className="cloud-conversation-compose" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      {journalError ? <Alert showIcon type="error" message={t("Message recovery storage is unavailable. Sending is disabled.", "消息恢复记录不可用，已禁止发送。")}/> : null}
      {outstanding ? <Alert showIcon type="warning" message={t("The original message is awaiting confirmation", "原消息正在等待确认")}
        description={t("Check the original message before sending another. It will not be sent again automatically.", "请先核对原消息，再发送新的内容；不会自动重发。")}
        action={<Button loading={checking} onClick={() => void checkOriginal()}>{t("Check delivery", "核对投递")}</Button>} /> : null}
      {issue ? <Alert showIcon type="warning" message={issue === "REJECTED"
        ? t("The message was not accepted. Your text is retained; refresh the session before sending again.", "消息未被接受，输入内容已保留；请刷新会话状态后再发送。")
        : t("The original message is still unconfirmed. Keep its original request; do not resend it.", "原消息仍未确认，请保留原请求，不要重新发送。")}/> : null}
      {session && !session.can_send ? <div className="cloud-conversation-unavailable"><span>{t("Messages cannot be sent right now.", "暂时无法发送消息。")}</span>
        {session.blocking_reasons.length ? <span className="muted">{session.blocking_reasons.map((reason) => blockingMessage(reason, t)).join(" ")}</span> : null}
        </div> : null}
      {session?.can_send && (session.can_reconnect || session.mode === "CONNECT_ON_SEND") ? <p className="muted">{t("Sending a message reconnects the saved session.", "发送消息后会重新连接已保存的会话。")}</p> : null}
      <label htmlFor={`cloud-message-${attempt.id}`}>{t("Reply to the agent", "回复 Agent")}</label>
      <Input.TextArea id={`cloud-message-${attempt.id}`} rows={3} maxLength={16000} showCount value={draft}
        disabled={sending || !!outstanding} onChange={(event) => setDraft(event.target.value)}
        placeholder={t("Add information, answer the agent, or describe the next step.", "补充信息、回答 Agent，或说明下一步。")}/>
      <div className="cloud-conversation-compose-actions"><p className="muted">{t("Delivery does not confirm processing. Test reports appear under artifacts.", "已投递不代表已处理。测试报告见产物区。")}</p>
        <Button type="primary" htmlType="submit" loading={sending} disabled={!canSend || !draft.trim()}>{t("Send message", "发送消息")}</Button></div>
    </form> : null}
  </div>;
}
