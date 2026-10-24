"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Empty, Skeleton, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { errorText, getJobs, getRunHarness, getRunReportContent, getVerdicts, recoverRunBinding } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { RunBinding } from "@/lib/types";
import { NewRunLink } from "./run-next-action";
import { latestRunVerdict } from "@/lib/run-summary";

export function RunHarness({ runId, projectId, refreshRun, selectTab, openTask }: { runId: string; projectId?: string; refreshRun: () => Promise<unknown>; selectTab: (key: string) => void; openTask?: (id: string) => void }) {
  const { t, label, locale, formatDate } = useI18n();
  const client = useQueryClient();
  const harness = useQuery({ queryKey: ["harness", runId], queryFn: () => getRunHarness(runId) });
  const jobs = useQuery({ queryKey: ["jobs", runId], queryFn: () => getJobs(runId) });
  const verdicts = useQuery({ queryKey: ["verdicts", runId], queryFn: () => getVerdicts(runId) });
  const latestVerdict = latestRunVerdict(verdicts.data);
  const [reportId, setReportId] = useState<string | null>(null);
  const report = harness.data?.reports.find((item) => item.id === reportId);
  const content = useQuery({ queryKey: ["run-report", reportId], queryFn: () => getRunReportContent(reportId!), enabled: !!reportId, retry: false });
  const binding = harness.data?.binding;
  const latestJob = [...(jobs.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const activeJob = jobs.data?.find((job) => ["QUEUED", "RUNNING", "WAITING_INPUT", "CANCEL_REQUESTED"].includes(job.status));
  const retryJob = binding?.status === "ACTIVE" && !activeJob && latestJob && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(latestJob.status) ? latestJob : null;
  const failedGate = binding?.status === "CLOSED" && !activeJob && latestJob?.job_type === "EVALUATE_GATE" && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(latestJob.status) ? latestJob : null;
  const terminal = binding && ["CLOSED", "FAILED", "CANCELLED"].includes(binding.status);
  const recovery = useMutation({
    mutationFn: (current: RunBinding) => recoverRunBinding(current),
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: ["harness", runId] });
      await refreshRun();
    },
  });
  const color = binding?.status === "RECOVERY_REQUIRED" || binding?.status === "WAITING_INPUT" ? "gold"
    : binding?.status === "FAILED" ? "red" : binding?.status === "ACTIVE" ? "blue" : undefined;

  return <section className="harness-records" aria-label={t("Session & reports", "持续会话与报告")}>
    <div className="section-heading"><h2>{t("Persistent testing session", "持续测试会话")}</h2><Button onClick={() => void harness.refetch()} loading={harness.isFetching}>{t("Refresh", "刷新")}</Button></div>
    <Typography.Paragraph className="muted">{t("A bound session retains the same testing context across stages and questions. Formal execution evidence and the quality verdict remain in their own records.", "已绑定会话会在阶段切换和人工问答之间保留同一测试上下文。正式执行证据与质量判定仍以各自记录为准。")}</Typography.Paragraph>
    {harness.error && <Alert type="warning" showIcon message={t("Session details could not be refreshed", "会话详情暂时无法刷新")} description={errorText(harness.error, locale)} />}
    {jobs.error && <Alert type="warning" showIcon style={{ marginTop: 16 }} message={t("Task status could not be checked", "暂无法核对任务状态")} description={t("Refresh the recorded tasks before recovering or retrying this session.", "恢复或重试此会话前，请先刷新已记录任务的状态。") } action={<Button onClick={() => void jobs.refetch()}>{t("Refresh tasks", "刷新任务")}</Button>} />}
    {harness.isLoading ? <Skeleton active paragraph={{ rows: 3 }} /> : !binding ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("This run has no persistent session binding. Any existing stage history and testing results remain available in their sections.", "此运行尚无持续会话绑定。已有阶段历史与测试结果仍可在相应栏目中查看。")} /> : <>
      <Space wrap><Tag color={color}>{binding.status === "ACTIVE" ? t("Session available", "会话可继续") : label(binding.status)}</Tag><Typography.Text type="secondary">{t("Updated", "更新于")} {formatDate(binding.updated_at)}</Typography.Text></Space>
      {binding.status === "WAITING_INPUT" && <Alert type="info" showIcon style={{ marginTop: 16 }} message={t("The session is waiting for your answer", "会话正在等待你的回答")} description={t("Answer the recorded question to continue the same task and session.", "回答已记录的问题，即可继续同一任务与会话。") } action={<Button onClick={() => selectTab("input-requests")}>{t("Questions & answers", "问题与回答")}</Button>} />}
      {binding.status === "RECOVERY_REQUIRED" && <Alert type="warning" showIcon style={{ marginTop: 16 }} message={t("Verify the original session before continuing", "继续前需核验原会话")} description={<><p>{t("Recovery checks that the old call has stopped and the original session and workspace are intact. It does not replay an interrupted test. After successful recovery, retry the recorded task explicitly. If a report was already accepted, recovery may only confirm the completed session is closed.", "恢复会核验旧调用已停止、原会话与工作区仍完整，不会重放中断的测试。恢复成功后，请显式重试原任务。若报告已被接受，恢复可能只确认已完成会话的关闭状态。")}</p>{activeJob && <p>{t("Wait for the active task to stop before recovering this session.", "请等待当前任务停止，再恢复此会话。")}</p>}<Button loading={recovery.isPending} disabled={!!harness.error || jobs.isLoading || !!jobs.error || !!activeJob} onClick={() => recovery.mutate(binding)}>{t("Verify & recover session", "核验并恢复会话")}</Button></>} />}
      {recovery.error && <Alert type="error" showIcon style={{ marginTop: 16 }} message={t("Session recovery was not confirmed", "尚未确认会话恢复成功")} description={errorText(recovery.error, locale)} />}
      {retryJob && <Alert type="info" showIcon style={{ marginTop: 16 }} message={t("The original session can continue through the recorded task", "原会话可通过已记录任务继续")} description={<>{t("Review this task and explicitly create its retry. The failed record and completed testing facts remain in history.", "请检查此任务并显式创建关联重试。失败记录与已完成的测试事实会保留在历史中。") }<p className="entity-key">{retryJob.key}</p></>} action={<Button onClick={() => openTask ? openTask(retryJob.id) : selectTab("tasks")}>{t("Review & retry original task", "检查并重试原任务")}</Button>} />}
      {failedGate && <Alert type="warning" showIcon style={{ marginTop: 16 }} message={t("The independent gate task needs review", "独立门禁任务需要检查")} description={t("Review the recorded task before creating its linked retry. The original testing session stays closed.", "请先检查已记录任务，再创建关联重试。原测试会话保持关闭。")} action={<Button onClick={() => openTask ? openTask(failedGate.id) : selectTab("tasks")}>{t("Review gate task", "检查门禁任务")}</Button>} />}
      {terminal && <Alert type={binding.status === "CLOSED" ? "info" : "warning"} showIcon style={{ marginTop: 16 }} message={t("This testing session has ended", "本次测试会话已结束")} description={binding.status === "CLOSED" ? t("This session cannot be reopened. Finding dispositions and independent gate reevaluation use the saved facts without resuming it. To retest or verify a code fix, review the inputs in a new testing round.", "此会话不能重新打开。发现处置与独立门禁重评可使用已有事实，无需恢复会话。需要复测或验证代码修复时，请在新测试轮次中审阅输入。") : t("This session cannot be reopened. Its accepted facts and history remain available. Review the inputs in a new testing round to continue testing.", "此会话不能重新打开。已接受事实与历史记录仍可查看。继续测试请在新的测试轮次中审阅输入。") } action={projectId ? <NewRunLink runId={runId} projectId={projectId} /> : undefined} />}
      <details style={{ marginTop: 16 }}><summary>{t("Session identity & limits", "会话身份与限制")}</summary><Descriptions size="small" column={1} style={{ marginTop: 12 }} items={[
        { key: "binding", label: t("Binding", "绑定标识"), children: <Typography.Text code copyable>{binding.id}</Typography.Text> },
        { key: "session", label: t("Primary session", "主会话标识"), children: <Typography.Text code copyable>{binding.primary_agent_session_id}</Typography.Text> },
        { key: "epoch", label: t("Recovery generation", "恢复代际"), children: binding.binding_epoch },
        ...(harness.data?.state ? [{ key: "budget", label: t("Cycle limits", "周期上限"), children: t(`Up to ${harness.data.state.max_steps} steps; ${harness.data.state.timeout_seconds}s per test execution; ${harness.data.state.harness_budget_seconds}s of active agent time across the run. Waiting for your answer does not use this time.`, `最多 ${harness.data.state.max_steps} 个步骤；每次测试执行限时 ${harness.data.state.timeout_seconds} 秒；整个运行累计 Agent 活跃时间上限 ${harness.data.state.harness_budget_seconds} 秒。等待回答不计入活跃时间。`) }] : []),
      ]} /></details>
    </>}
    <section style={{ marginTop: 28 }} aria-label={t("Testing reports", "测试报告")}>
      <div className="section-heading"><h2>{t("Testing reports", "测试报告")}</h2></div>
      <Typography.Paragraph className="muted">{t("Reports preserve the records and verdict referenced when they were accepted. Later finding dispositions and gate reevaluations do not rewrite them. Use the latest formal verdict and linked evidence for the current quality decision.", "报告保留接受时引用的记录与判定。后续发现处置和门禁重评不会改写原报告。当前质量结论请查看最新正式判定与关联证据。")}</Typography.Paragraph>
      {!!harness.data?.reports.length ? <ul className="input-request-list">{harness.data.reports.map((item) => <li key={item.id}><div><Typography.Text strong>{t("Testing report", "测试报告")}</Typography.Text><p className="muted">{formatDate(item.created_at)}</p>{item.verdict_key && <Space wrap><Typography.Text code>{item.verdict_key}</Typography.Text>{item.verdict_decision && <Tag>{label(item.verdict_decision)}</Tag>}{latestVerdict && latestVerdict.key !== item.verdict_key && <Tag color="gold">{t("Earlier verdict in report", "报告引用先前判定")}</Tag>}</Space>}</div><Button onClick={() => setReportId(item.id)}>{t("Read report", "阅读报告")}</Button></li>)}</ul> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={harness.error ? t("Reports could not be loaded. Refresh to try again.", "暂无法读取报告，请刷新重试。") : t("No report has been submitted yet.", "尚未提交测试报告。")} />}
    </section>
    <section style={{ marginTop: 28 }} aria-label={t("GitLab issues", "GitLab 问题单")}>
      <div className="section-heading"><h2>{t("GitLab issues", "GitLab 问题单")}</h2></div>
      {!!harness.data?.issues.length ? <ul className="input-request-list">{harness.data.issues.map((item) => <li key={item.id}><div><Space wrap><Tag color={item.status === "UNKNOWN" ? "gold" : undefined}>{item.status === "SUCCEEDED" ? t("Issue created", "已创建问题单") : label(item.status)}</Tag><Typography.Text className="muted">{formatDate(item.updated_at)}</Typography.Text></Space><p className="entity-key">{t("Finding", "问题发现")} {item.finding_id}</p>{item.status === "UNKNOWN" && <p>{t("The external result is unknown. Reconcile the existing request before creating another issue.", "外部结果尚不确定。请先核对已有请求，避免重复创建问题单。")}</p>}</div>{item.status === "SUCCEEDED" && item.issue_url ? <a href={item.issue_url} target="_blank" rel="noopener noreferrer">{t("Open issue", "打开问题单")} {item.issue_iid ? `#${item.issue_iid}` : ""}</a> : null}</li>)}</ul> : <Typography.Paragraph className="muted">{harness.error ? t("Issue records could not be loaded.", "暂无法读取提单记录。") : t("No issue request has been recorded for this run.", "本次运行尚无提单请求记录。")}</Typography.Paragraph>}
    </section>
    <Drawer title={t("Testing report", "测试报告")} open={!!reportId} width={840} onClose={() => setReportId(null)}>
      {report?.verdict_key && <Alert type={latestVerdict && latestVerdict.key !== report.verdict_key ? "warning" : "info"} showIcon style={{ marginBottom: 16 }} message={t("Report's original verdict", "报告原始判定")} description={<Space direction="vertical" size={8}><Space wrap><Typography.Text code>{report.verdict_key}</Typography.Text>{report.verdict_decision && <Tag>{label(report.verdict_decision)}</Tag>}</Space>{latestVerdict && latestVerdict.key !== report.verdict_key ? <span>{t(`A later formal verdict (#${latestVerdict.sequence_no}) is available. This report remains an unchanged historical summary.`, `已有更新的正式判定（#${latestVerdict.sequence_no}）。此报告保留原始历史摘要。`)}</span> : <span>{t("This report retains the verdict referenced when it was accepted. Gate reevaluation does not regenerate it.", "此报告保留接受时引用的判定。门禁重评不会重新生成报告。")}</span>}<Button onClick={() => { setReportId(null); selectTab("verdicts"); }}>{t("View verdict history", "查看判定历史")}</Button></Space>} />}
      {report && <Typography.Paragraph style={{ overflowWrap: "anywhere" }}><Typography.Text className="muted">SHA-256 </Typography.Text><Typography.Text code copyable>{report.content_sha256}</Typography.Text></Typography.Paragraph>}
      {content.error && <Alert type="error" showIcon message={t("Report could not be verified", "报告未能通过读取校验")} description={errorText(content.error, locale)} action={<Button onClick={() => void content.refetch()}>{t("Retry", "重试")}</Button>} />}
      {content.isLoading ? <Skeleton active paragraph={{ rows: 8 }} /> : !content.error && content.data !== undefined ? <pre className="artifact-content">{content.data}</pre> : null}
    </Drawer>
  </section>;
}
