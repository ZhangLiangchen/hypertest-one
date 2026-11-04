"use client";

import { Alert, Button, Checkbox, Input, Radio, Space, Typography } from "antd";
import { useEffect, useState } from "react";

import { useI18n } from "@/lib/i18n";

export type LiveQuestionOption = { label: string; value?: string; description?: string };
export type LiveQuestion = {
  id: string;
  question: string;
  detail?: string | null;
  options?: LiveQuestionOption[];
  multiple: boolean;
  intent?: { kind?: string };
  allow_custom: boolean;
};
export type LiveQuestionAnswer = { id: string; selected: string[]; custom?: string };
export type LiveQuestionRequest = {
  id: string;
  status: "open" | "answered" | "delivering" | "delivered" | "cancelled" | "unknown";
  questions: LiveQuestion[];
  answer?: { answers?: LiveQuestionAnswer[]; cancelled?: boolean } | null;
};

type Props = {
  request: LiveQuestionRequest;
  blocked?: boolean;
  embedded?: boolean;
  onSubmit: (requestId: string, answers: LiveQuestionAnswer[]) => Promise<unknown>;
  onCancel: (requestId: string) => Promise<unknown>;
};

/** The server owns request lifecycle and delivery; this component only collects input. */
export function LiveQuestions({ request, blocked = false, embedded = false, onSubmit, onCancel }: Props) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<Record<string, string[]>>({});
  const [custom, setCustom] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => { setSelected({}); setCustom({}); setError(false); }, [request.id]);

  const open = request.status === "open";
  const disabled = blocked || submitting || !open;
  const complete = request.questions.length > 0 && request.questions.every((question) =>
    (selected[question.id]?.length || 0) > 0 || (question.allow_custom === true && !!custom[question.id]?.trim()));
  const messages: Record<LiveQuestionRequest["status"], string> = {
    open: t("The agent is waiting for your response.", "Agent 正在等待你的回答。"),
    answered: t("Answer saved; waiting for delivery to the agent.", "回答已保存，正在等待交付给 Agent。"),
    delivering: t("Delivering the saved answer to the agent.", "正在向 Agent 交付已保存的回答。"),
    delivered: t("Answer delivered to the session.", "回答已交给会话。"),
    cancelled: t("This question request was cancelled.", "此提问已取消。"),
    unknown: t("Answer delivery is unconfirmed.", "回答投递尚未确认。"),
  };

  async function perform(action: () => Promise<unknown>) {
    setSubmitting(true);
    setError(false);
    try { await action(); } catch { setError(true); } finally { setSubmitting(false); }
  }

  return <section className={embedded ? "cloud-conversation-question" : "overview-section"} aria-labelledby={`cloud-live-questions-${request.id}`}>
    <Typography.Title id={`cloud-live-questions-${request.id}`} level={embedded ? 3 : 2}>{t("Agent questions", "Agent 提问")}</Typography.Title>
    <Alert showIcon type={request.status === "unknown" ? "warning" : "info"} message={messages[request.status]} />
    {error ? <Alert showIcon type="error" style={{ marginTop: 12 }} message={t("The request could not be completed. Check its status before trying again.", "请求未能完成，请先核对状态再操作。 ")} /> : null}
    {!open ? <div className="cloud-conversation-question-history">{request.questions.map((question) => {
      const answer = request.answer?.answers?.find((item) => item.id === question.id);
      return <div key={question.id}><Typography.Paragraph strong>{question.question}</Typography.Paragraph>
        {answer ? <Typography.Paragraph className="session-literal"><strong>{t("Your saved answer", "已保存的回答")}：</strong>{[...answer.selected, answer.custom].filter(Boolean).join("\n")}</Typography.Paragraph> : null}</div>;
    })}</div> : null}
    {open ? <form className="workspace-form form-section cloud-task-fields" onSubmit={(event) => {
      event.preventDefault();
      if (disabled || !complete) return;
      const answers = request.questions.map((question) => ({ id: question.id, selected: selected[question.id] || [],
        ...(question.allow_custom === true && custom[question.id]?.trim() ? { custom: custom[question.id].trim() } : {}) }));
      void perform(() => onSubmit(request.id, answers));
    }}>
      {request.questions.map((question) => <fieldset key={question.id} disabled={disabled} style={{ border: 0, margin: "20px 0", padding: 0 }}>
        <legend><Typography.Text strong>{question.question}</Typography.Text></legend>
        {question.detail ? <Typography.Paragraph className="muted">{question.detail}</Typography.Paragraph> : null}
        {question.options?.length ? question.multiple === true
          ? <Space direction="vertical">{question.options.map((option) => {
            const value = option.label;
            return <Checkbox key={value} checked={(selected[question.id] || []).includes(value)} onChange={(event) => setSelected((current) => ({
              ...current, [question.id]: event.target.checked ? [...(current[question.id] || []), value] : (current[question.id] || []).filter((item) => item !== value),
            }))}>{option.label}{option.description ? <span className="muted"> — {option.description}</span> : null}</Checkbox>;
          })}</Space>
          : <Radio.Group value={selected[question.id]?.[0]} onChange={(event) => { if (!["plan-review", "approval"].includes(question.intent?.kind || "")) setCustom((current) => ({ ...current, [question.id]: "" })); setSelected((current) => ({ ...current, [question.id]: [String(event.target.value)] })); }}>
            <Space direction="vertical">{question.options.map((option) => <Radio key={option.label} value={option.label}>{option.label}{option.description ? <span className="muted"> — {option.description}</span> : null}</Radio>)}</Space>
          </Radio.Group> : null}
        {question.allow_custom === true ? <label style={{ display: "block", marginTop: 12 }}>
          <span>{t("Your answer", "你的回答")}</span>
          <Input.TextArea rows={3} maxLength={16000} value={custom[question.id] || ""} onChange={(event) => { if (!question.multiple && !["plan-review", "approval"].includes(question.intent?.kind || "")) setSelected((current) => ({ ...current, [question.id]: [] })); setCustom((current) => ({ ...current, [question.id]: event.target.value })); }} />
        </label> : null}
        {!question.options?.length && question.allow_custom !== true ? <Typography.Paragraph type="warning">{t("This question has no supported answer format.", "此问题没有可用的回答方式。")}</Typography.Paragraph> : null}
      </fieldset>)}
      <Space wrap>
        <Button type="primary" htmlType="submit" disabled={disabled || !complete} loading={submitting}>{t("Submit answer", "提交回答")}</Button>
        <Button disabled={disabled} onClick={() => void perform(() => onCancel(request.id))}>{t("Cancel question", "取消提问")}</Button>
      </Space>
    </form> : null}
  </section>;
}
