"use client";

import { QuestionCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Empty, Form, Input, Space, Spin, Tag, Typography } from "antd";
import { useRef, useState } from "react";
import { answerInputRequest, errorText, getInputRequests } from "@/lib/api";
import { canAnswerInput, MAX_INPUT_ANSWER_CHARACTERS, prepareInputAnswer, validateInputAnswer } from "@/lib/input-answers";
import { useI18n } from "@/lib/i18n";
import { createUuid } from "@/lib/uuid";
import type { BackgroundJob, InputAnswer, InputRequest, Mission } from "@/lib/types";

export function useRunInputRequests(runId: string, jobs: BackgroundJob[], jobsUnavailable: boolean, openTask: (id: string) => void, refreshRun: () => void) {
  const { t, label, locale, formatDate } = useI18n();
  const client = useQueryClient();
  const requests = useQuery({ queryKey: ["input-requests", runId], queryFn: () => getInputRequests(runId), refetchInterval: 2_000 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const submissions = useRef(new Map<string, InputAnswer>());
  const submissionInFlight = useRef(false);
  const rows = [...(requests.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const pending = rows.filter((item) => item.status === "PENDING");
  const selected = rows.find((item) => item.id === selectedId);
  const job = jobs.find((item) => item.id === selected?.durable_job_id);
  const draft = selected ? drafts[selected.id] ?? "" : "";
  const validationError = validateInputAnswer(draft);
  const validationMessage = validationError === "length" ? t("Use at most 12,000 characters.", "回答最多可输入 12,000 个字符。")
    : validationError === "nul" ? t("Remove the NUL character before submitting.", "请移除 NUL 空字符后再提交。")
    : validationError === "empty" ? t("Enter an answer containing more than whitespace.", "请输入非空白的回答。") : undefined;
  const canSubmit = !!selected && canAnswerInput(selected, job) && !jobsUnavailable && !requests.error;

  function updateRequest(result: InputRequest) {
    client.setQueryData<InputRequest[]>(["input-requests", runId], (current = []) => [result, ...current.filter((item) => item.id !== result.id)]);
  }
  function refresh() {
    void requests.refetch();
    void client.invalidateQueries({ queryKey: ["jobs", runId] });
  }
  const answering = useMutation({
    mutationFn: async ({ request, answer }: { request: InputRequest; answer: string }) => {
      const submission = prepareInputAnswer(submissions.current.get(request.id), answer, request.row_version, () => `web:answer:${createUuid()}`);
      submissions.current.set(request.id, submission);
      return answerInputRequest(request.id, submission);
    },
    onSuccess: async (result) => {
      // A read started before the answer committed must not restore PENDING UI.
      await Promise.all([
        client.cancelQueries({ queryKey: ["input-requests", runId] }),
        client.cancelQueries({ queryKey: ["jobs", runId] }),
      ]);
      updateRequest(result.input_request);
      submissions.current.delete(result.input_request.id);
      client.setQueryData<BackgroundJob[]>(["jobs", runId], (current = []) => [result.job, ...current.filter((item) => item.id !== result.job.id)]);
      client.setQueryData(["job", result.job.id], result.job);
      refreshRun();
    },
    onSettled: () => { submissionInFlight.current = false; refresh(); },
  });

  function open(id: string) {
    setSelectedId(id);
  }
  function submit() {
    if (!selected || !canSubmit || submissionInFlight.current || validateInputAnswer(draft)) return;
    submissionInFlight.current = true;
    answering.mutate({ request: selected, answer: draft });
  }
  const selectedError = selected?.status === "PENDING" && answering.variables?.request.id === selected.id ? answering.error : null;
  const recordStatus = (item: InputRequest) => <Tag color={item.status === "PENDING" ? "gold" : item.status === "CANCELLED" ? undefined : "blue"}>{label(item.status)}</Tag>;

  function list(items: InputRequest[]) {
    return <ul className="input-request-list">{items.map((item) => <li key={item.id}>
      <div><Space wrap>{recordStatus(item)}{item.scope === "run" && <Tag>{t("Run decision", "运行决策")}</Tag>}<span className="entity-key">{item.key}</span></Space><p className="input-question-preview">{item.question}</p></div>
      <Button onClick={() => open(item.id)}>{item.status === "PENDING" ? t("Answer question", "回答问题") : t("View answer", "查看回答")}</Button>
    </li>)}</ul>;
  }
  const readError = requests.error ? <Alert type="warning" showIcon message={t("Questions could not be refreshed", "问题暂时无法刷新")} description={<>{errorText(requests.error, locale)} {t("Loaded questions and your draft remain available. Refresh before submitting.", "已加载问题和回答草稿会保留。请刷新后再提交。")}</>} action={<Button onClick={refresh}>{t("Refresh", "刷新")}</Button>} /> : null;
  const monitor = <>
    {readError}
    {!!pending.length && <section className="input-request-notice" aria-label={t("Your input is needed", "需要你的回答")}>
      <div className="section-heading"><h2><QuestionCircleOutlined aria-hidden /> {t("Your input is needed", "需要你的回答")}</h2><Tag color="gold">{pending.length}</Tag></div>
      <p className="muted">{t("Testing is paused for clarification. Answer the recorded question to continue the same background task; accepted testing records remain unchanged.", "测试正在暂停等待澄清。回答已记录的问题后，将继续同一后台任务；已接受的测试记录会保留。")}</p>
      {list(pending)}
    </section>}
  </>;
  const tab = {
    key: "input-requests", label: `${t("Questions & answers", "问题与回答")} (${requests.data ? rows.length : "—"})`, children: <>
      <Typography.Paragraph className="muted">{t("Questions and answers supplement the testing context. They do not change the frozen PRD or source and do not count as accepted proposals, execution evidence or quality decisions.", "问题与回答补充测试上下文，不会修改固定的 PRD 或源码，也不等同于已接受的提议、执行证据或质量判定。")}</Typography.Paragraph>
      {readError}
      {requests.isLoading ? <div className="pane-loading"><Spin /></div> : rows.length ? list(rows) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={requests.error ? t("Questions are unavailable. Refresh to try again.", "暂无法读取问题，请刷新重试。") : t("No clarification questions have been recorded for this run.", "本次运行尚未记录澄清问题。")} />}
    </>,
  };
  const missionPanel = (missionId: string) => {
    const items = rows.filter((item) => item.mission_id === missionId);
    return (items.length || requests.error) ? <section aria-label={t("Mission questions", "任务问题")}>
      <Typography.Title level={4}>{t("Questions & answers", "问题与回答")}</Typography.Title>
      {readError}{list(items)}
    </section> : null;
  };
  const dialog = <Drawer title={selected?.scope === "run" ? t("Run decision", "运行决策") : t("Mission question", "测试任务问题")} open={!!selectedId} width={740} onClose={() => setSelectedId(null)}>
    {readError}
    {!selected ? selectedId ? <Alert type="warning" showIcon message={t("This question is unavailable", "暂无法读取此问题")} description={t("Refresh the questions without closing this page. Your draft is retained.", "请刷新问题，无需关闭此页面。回答草稿会保留。")} action={<Button onClick={refresh}>{t("Refresh", "刷新")}</Button>} /> : null : <>
      <Space wrap>{recordStatus(selected)}<span className="entity-key">{selected.key}</span></Space>
      <Typography.Title level={4}>{t("Question", "问题")}</Typography.Title>
      <Typography.Paragraph className="input-question-text">{selected.question}</Typography.Paragraph>
      <Typography.Paragraph className="muted">{t("The question is shown as written by the agent. Your answer provides context; HyperTest still verifies proposals and requires trusted Runner evidence for testing facts.", "此处保留智能体问题原文。回答用于补充上下文；提议仍须由 HyperTest 验证，正式测试事实仍须来自可信 Runner 证据。")}</Typography.Paragraph>
      {selected.status === "PENDING" ? <>
        {job?.status === "RUNNING" && <Alert type="info" showIcon message={t("Saving the paused task", "正在保存暂停状态")} description={t("Answer submission becomes available once the worker has safely paused this task.", "Worker 安全暂停此任务后，即可提交回答。")}/>} 
        {(!job || jobsUnavailable || (job.status !== "WAITING_INPUT" && job.status !== "RUNNING")) && <Alert type="warning" showIcon message={t("Check task status before answering", "回答前请检查任务状态")} description={t("The task is not currently confirmed as waiting for this answer. Refresh its state or inspect the task record.", "当前尚未确认任务正在等待此回答。请刷新状态或检查后台任务记录。此处不会自动创建新的测试周期。")} action={<Button onClick={refresh}>{t("Refresh", "刷新")}</Button>} />}
        <Form name={`answer-${selected.id}`} layout="vertical" onFinish={submit}>
          {!!selected.options.length && <Form.Item label={t("Suggested answers", "建议回答")} extra={t("Choose a suggestion to fill the draft, or write your own answer below. Choosing does not submit.", "可选择建议填入草稿，也可在下方自由回答。选择后不会自动提交。")}><div className="input-answer-options">{selected.options.map((option, index) => <Button key={index} disabled={answering.isPending} onClick={() => setDrafts((current) => ({ ...current, [selected.id]: option }))}>{option}</Button>)}</div></Form.Item>}
          <Form.Item label={t("Your answer", "你的回答")} required htmlFor={`input-answer-${selected.id}`} extra={t("Keep the answer specific to this question. The original PRD and pinned source stay unchanged.", "请针对当前问题提供明确回答。原 PRD 和固定源码版本保持不变。") } validateStatus={draft && validationError ? "error" : undefined} help={draft && validationError ? validationMessage : undefined}>
            <div className="input-answer-control"><Input.TextArea id={`input-answer-${selected.id}`} value={draft} onChange={(event) => setDrafts((current) => ({ ...current, [selected.id]: event.target.value }))} disabled={answering.isPending} autoSize={{ minRows: 5, maxRows: 14 }} count={{ show: true, max: MAX_INPUT_ANSWER_CHARACTERS, strategy: (value) => Array.from(value).length }} placeholder={t("Answer the question, or explain what remains unknown.", "请回答此问题，或说明仍不确定的信息。")} /></div>
          </Form.Item>
          {!!selectedError && <Alert role="alert" type="error" showIcon message={t("The answer could not be confirmed", "尚无法确认回答已保存")} description={<>{errorText(selectedError, locale)} {t("Your draft is retained. Refresh or submit the same answer again; an uncertain retry reuses the original request key.", "草稿已保留。可刷新状态，或再次提交相同回答；结果不确定时会复用原请求标识，避免重复恢复。")}</>} />}
          <div className="input-answer-actions"><Button type="primary" htmlType="submit" loading={answering.isPending} disabled={!canSubmit || !!validateInputAnswer(draft)}>{t("Submit answer & continue", "提交回答并继续")}</Button><Button onClick={() => setSelectedId(null)}>{t("Close; keep draft", "关闭并保留草稿")}</Button></div>
        </Form>
      </> : <>
        <Alert type={selected.status === "CANCELLED" ? "warning" : "info"} showIcon message={selected.status === "CANCELLED" ? t("This question was cancelled", "此问题已取消") : selected.status === "CONSUMED" ? t("The agent received this answer", "智能体已接收此回答") : t("Answer saved; the same task will continue", "回答已保存，同一任务将继续处理")} description={selected.status === "CANCELLED" ? t("The question and any recorded answer remain in history. This question cannot resume a cancelled task.", "问题及已记录回答会保留在历史中。此问题不能恢复已取消的任务。") : t("Follow the task for progress. Saving an answer does not mean the mission or test cycle passed.", "请查看后台任务的后续进度。回答保存不代表任务或测试周期已通过。")}/>
        {selected.answer !== null && <><Typography.Title level={4}>{t("Recorded answer", "已保存的回答")}</Typography.Title><Typography.Paragraph className="input-question-text">{selected.answer}</Typography.Paragraph></>}
        {draft && draft !== selected.answer && <details className="input-unsent-draft"><summary>{t("Your unsent draft", "你的未提交草稿")}</summary><p className="input-question-text">{draft}</p></details>}
      </>}
      <Descriptions column={1} size="small" style={{ marginTop: 24 }} items={[
        { key: "scope", label: t("Question scope", "问题范围"), children: selected.scope === "run" ? t("Run decision between stages", "阶段之间的运行决策") : t("Current mission", "当前任务阶段") },
        ...(selected.mission_id || selected.context_mission_id ? [{ key: "mission", label: selected.scope === "run" ? t("Completed stage for context", "关联的已完成阶段") : t("Mission", "测试任务"), children: <Typography.Text code copyable>{client.getQueryData<Mission[]>(["missions", runId])?.find((item) => item.id === (selected.mission_id || selected.context_mission_id))?.key || selected.mission_id || selected.context_mission_id}</Typography.Text> }] : []),
        { key: "asked", label: t("Asked", "提问时间"), children: formatDate(selected.created_at) },
        ...(selected.answered_at ? [{ key: "answered", label: t("Answered", "回答时间"), children: formatDate(selected.answered_at) }] : []),
      ]} />
      <Button onClick={() => { setSelectedId(null); openTask(selected.durable_job_id); }}>{t("View background task", "查看后台任务")}</Button>
    </>}
  </Drawer>;
  return { requests, pending, monitor, tab, dialog, missionPanel, open, busy: answering.isPending || requests.isLoading || !!requests.error };
}
