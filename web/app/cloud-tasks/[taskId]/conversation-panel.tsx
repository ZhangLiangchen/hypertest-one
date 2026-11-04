"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Input, Select, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { cloudInputIdentity } from "@/lib/cloud";
import type { CloudAttempt } from "@/lib/cloud";
import { conversationJournal, mergeConversationMessages, readConversation, reconcilePendingConversationMessages, sendConversationMessage } from "@/lib/cloud-conversation";
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

export function conversationSessionLabel(state: string | undefined, t: (en: string, zh: string) => string): string {
  const labels: Record<string, string> = {
    ACTIVE: t("Agent is working", "Agent 正在执行"),
    AWAITING_REPLY: t("Waiting for your reply", "等待你的回复"),
    IDLE: t("Ready for your reply", "可以继续回复"),
    QUEUED: t("Waiting for the Agent", "等待 Agent 处理"),
    PAUSED: t("Execution paused", "执行已暂停"), BLOCKED: t("Agent is blocked", "Agent 遇到阻塞"),
    COMPLETED: t("Task completed", "任务已完成"), FAILED: t("Task failed", "任务失败"), CANCELLED: t("Task cancelled", "任务已取消"),
  };
  return labels[state || ""] || t("Loading progress", "正在读取进展");
}

export function conversationPauseReason(reason: string | null | undefined, t: (en: string, zh: string) => string): string {
  const labels: Record<string, string> = {
    REPORT_CONTENT_REJECTED: t("Report content was not accepted for archiving. You can continue the conversation while the Agent corrects it.", "报告内容未通过归档检查。可继续对话，由 Agent 修正报告。"),
    HANDOFF_PAYLOAD_INVALID: t("The report format did not meet the archive requirements. You can continue the conversation while the Agent corrects it.", "报告格式不符合归档要求。可继续对话，由 Agent 修正报告。"),
    REPORT_RECONCILIATION_PENDING: t("A report submission is awaiting confirmation. Saved messages are retained while its original submission is checked.", "报告提交结果正在确认，系统核对原提交期间会保留已保存的消息。"),
    WORKER_RUNTIME_FAILED: t("Agent execution encountered an error. New messages will be saved for processing.", "Agent 执行遇到错误，新消息会保存并等待处理。"),
    RUNTIME_TIMEOUT: t("Agent execution timed out. New messages will be saved for processing.", "Agent 执行超时，新消息会保存并等待处理。"),
  };
  return labels[reason || ""] || t("Agent execution is paused. Saved messages and conversation history remain available.", "Agent 执行已暂停，已保存的消息和对话历史仍保留。");
}

function blockingMessage(reason: string, t: (en: string, zh: string) => string): string {
  const labels: Record<string, string> = {
    NO_ATTEMPT: t("The task has not started yet.", "任务尚未开始执行。"),
    TASK_DELETED: t("The task was removed; its messages remain readable.", "任务已移除，历史消息仍可查看。"),
    HISTORICAL_ATTEMPT: t("This is a previous attempt. Its conversation is read only.", "这是此前的执行尝试，对话只读。"),
    ATTEMPT_TERMINAL: t("This task has ended. Its conversation is read only.", "任务已结束，对话只读。"),
    CANCELLATION_REQUESTED: t("This task is being cancelled. Its saved messages remain readable.", "任务正在取消，已保存的消息仍可查看。"),
    AUTHORIZATION_UNAVAILABLE: t("Current authorization does not allow sending.", "当前授权不允许发送消息。"),
  };
  return labels[reason] || t("The session cannot receive messages in its current state.", "会话当前状态不允许接收消息。");
}

function messageText(message: ConversationMessage, t: (en: string, zh: string) => string): string {
  // Imported control notices retain their stored history but cannot prescribe
  // a retired takeover workflow. Agent-authored messages remain verbatim.
  if (message.role === "SYSTEM" && message.source === "IMPORTED_HISTORY" && message.reason_code === "CONVERSATION_GAP") {
    return t("Available public replies were imported from the original conversation. Some earlier output was not retained, so the history may be incomplete.", "已从原会话补录现存的公开回复，部分早期输出未留存，对话历史可能不完整。");
  }
  if (message.text) return message.text;
  if (message.reason_code === "ARTIFACT_CONTENT_REJECTED") return t("A test artifact was withheld by the content check. The Agent can correct it; existing messages remain available.", "一份测试产物未通过内容检查，Agent 可修正后重新提交；已有对话仍保留。");
  if (message.reason_code === "ARTIFACT_REJECTED") return t("A test artifact did not meet the submission contract. The Agent has received correction details; no test result was accepted.", "一份测试产物不符合提交要求，Agent 已收到修正说明；此次提交没有形成测试结果。");
  if (message.reason_code === "CONTENT_REJECTED") return t("This message was withheld by the content check.", "此消息未通过内容检查，正文未展示。");
  if (message.reason_code === "MESSAGE_TOO_LARGE") return t("The message exceeded the size limit and was not recorded.", "消息超过长度限制，正文未记录。");
  if (message.reason_code === "CONVERSATION_GAP") return t("Some agent output was not received. This conversation may be incomplete.", "部分 Agent 输出未收到，对话记录可能不完整。");
  return t("Message content is unavailable.", "消息正文不可用。");
}

function visibleConversationMessage(message: ConversationMessage): boolean {
  // Empty Worker status observations remain in the stored stream, not the chat.
  // Keep notices explaining withheld content, archive correction or a history gap.
  return message.role !== "SYSTEM" || !!message.text.trim()
    || ["ARTIFACT_CONTENT_REJECTED", "ARTIFACT_REJECTED", "CONTENT_REJECTED", "MESSAGE_TOO_LARGE", "CONVERSATION_GAP"].includes(message.reason_code || "");
}

function ConversationStream({ projectId, taskId, attempt, blocked, readOnly }: Props & { readOnly: boolean }) {
  const { t, formatDate } = useI18n();
  const cache = useRef<{ messages: ConversationMessage[]; cursor: number }>({ messages: [], cursor: 0 });
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingConversationMessage[]>([]);
  const [journalReady, setJournalReady] = useState(false);
  const [journalError, setJournalError] = useState(false);
  const [sending, setSending] = useState(false);
  const [issue, setIssue] = useState<"REJECTED" | null>(null);
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
  const messages = (conversation.data?.messages || []).filter(visibleConversationMessage);
  const session = conversation.data?.session;
  const draftDigest = cloudInputIdentity({ text: draft.trim() });
  const outstanding = pending.some((row) => row.text_digest === draftDigest);
  const canSend = !readOnly && !blocked && !conversation.isError && session?.can_send === true
    && journalReady && !journalError && !outstanding && !sending;
  const lastCursor = messages.at(-1)?.cursor;
  useEffect(() => {
    let active = true, checking = false;
    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        // Every poll is an original-key GET, including after a lost browser response.
        const confirmed = await reconcilePendingConversationMessages({ project_id: projectId, task_id: taskId, attempt_id: attempt.id });
        if (!active) return;
        if (confirmed.length) {
          const digests = new Set(confirmed.map((row) => cloudInputIdentity({ text: row.text })));
          setDraft((current) => digests.has(cloudInputIdentity({ text: current.trim() })) ? "" : current);
          await conversation.refetch();
        }
        await refreshJournal();
      } catch { if (active) setJournalError(true); }
      finally { checking = false; }
    };
    void check();
    const timer = window.setInterval(() => { void check(); }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId, taskId, attempt.id, conversation.refetch, refreshJournal]);
  useEffect(() => {
    if (!scroll.current) return;
    if (follow.current) { scroll.current.scrollTop = scroll.current.scrollHeight; setNewMessages(false); }
    else setNewMessages(true);
  }, [lastCursor]);

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
    <div className="cloud-conversation-state"><Tag>{readOnly ? t("Read only", "只读") : conversationSessionLabel(session?.state, t)}</Tag>
      {conversation.data?.observed_at ? <span className="muted">{t("Updated", "更新于")} {formatDate(conversation.data.observed_at)}</span> : null}
      <Button type="text" size="small" loading={conversation.isFetching} onClick={() => void conversation.refetch()}>{t("Refresh", "刷新")}</Button></div>
    {conversation.isError ? <Alert showIcon type="warning" message={t("Conversation could not be refreshed. Previously loaded messages remain visible.", "对话刷新失败，已加载的消息仍保留。")}/> : null}
    {!readOnly && session?.state === "PAUSED" ? <Alert showIcon type="warning" message={conversationPauseReason(session.reason_code, t)} /> : null}
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
      running={!readOnly && ["ACTIVE", "AWAITING_REPLY"].includes(session?.state || "")} blocked={blocked || readOnly} embedded />
    {!readOnly ? <form className="cloud-conversation-compose" onSubmit={(event) => { event.preventDefault(); void send(); }}>
      {journalError ? <Alert showIcon type="error" message={t("Message recovery storage is unavailable. Sending is disabled.", "消息恢复记录不可用，已禁止发送。")}/> : null}
      {pending.length ? <Alert showIcon type="info" message={t("Confirming a previous message automatically", "正在自动确认此前消息")}
        description={t("Your text is retained. You can write another message while confirmation continues.", "输入内容已保留，确认期间可以编辑并发送其他消息。")}/> : null}
      {session?.delivery_state === "UNCONFIRMED" ? <p className="muted">{t("An earlier message is awaiting delivery confirmation. New messages will be saved and wait in order.", "此前消息正在确认投递结果，新消息会保存并按顺序等待处理。")}</p> : null}
      {issue ? <Alert showIcon type="warning" message={t("The message was not accepted. Your text is retained.", "消息未被接受，输入内容已保留。")}/> : null}
      {session && !session.can_send ? <div className="cloud-conversation-unavailable"><span>{t("Messages cannot be sent right now.", "暂时无法发送消息。")}</span>
        {session.blocking_reasons.length ? <span className="muted">{session.blocking_reasons.map((reason) => blockingMessage(reason, t)).join(" ")}</span> : null}
        </div> : null}
      <label htmlFor={`cloud-message-${attempt.id}`}>{t("Reply to the agent", "回复 Agent")}</label>
      <Input.TextArea id={`cloud-message-${attempt.id}`} rows={3} maxLength={16000} showCount value={draft}
        disabled={sending} onChange={(event) => setDraft(event.target.value)}
        placeholder={t("Add information, answer the agent, or describe the next step.", "补充信息、回答 Agent，或说明下一步。")}/>
      <div className="cloud-conversation-compose-actions"><p className="muted">{t("Delivery does not confirm processing. Test reports appear under artifacts.", "已投递不代表已处理。测试报告见产物区。")}</p>
        <Button type="primary" htmlType="submit" loading={sending} disabled={!canSend || !draft.trim()}>{t("Send message", "发送消息")}</Button></div>
    </form> : null}
  </div>;
}
