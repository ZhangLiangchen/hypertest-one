"use client";

import { ArrowRightOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, FileSearchOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Skeleton, Space, Tag } from "antd";
import { useI18n } from "@/lib/i18n";
import { latestRunVerdict } from "@/lib/run-summary";
import type { BackgroundJob, Evidence, Finding, TestExecution, Verdict } from "@/lib/types";

type Dataset<T> = { data: T[] | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };

export function RunOverview({ verdicts, executions, evidence, findings, jobs, navigate, openVerdict, openEvidence, openExecution, openFinding, openTask }: {
  verdicts: Dataset<Verdict>; executions: Dataset<TestExecution>; evidence: Dataset<Evidence>;
  findings: Dataset<Finding>; jobs: Dataset<BackgroundJob>;
  navigate: (section: string) => void; openVerdict: (item: Verdict) => void;
  openEvidence: (item: Evidence) => void; openExecution: (item: TestExecution) => void;
  openFinding: (item: Finding) => void; openTask: (id: string) => void;
}) {
  const { t, label, locale, formatDate, verdictReason } = useI18n();
  const latest = latestRunVerdict(verdicts.data);
  const task = [...(jobs.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  const failedExecution = [...(executions.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).find((item) => item.purpose === "OFFICIAL" && (item.outcome === "FAIL" || ["ERROR", "TIMED_OUT"].includes(item.status)));
  const openFindings = findings.data?.filter((item) => ["NEW", "TRIAGED", "CONFIRMED", "REOPENED"].includes(item.status)) || [];
  const recentEvidence = [...(evidence.data || [])].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 3);
  const tone = !latest || latest.status !== "FINAL" ? "pending" : ["RELEASE_READY", "PASS"].includes(latest.decision) ? "success" : ["RELEASE_BLOCKED", "FAIL"].includes(latest.decision) ? "danger" : "warning";
  const errors = [verdicts, executions, evidence, findings, jobs].filter((query) => query.error);
  return <div className="run-overview">
    {!!errors.length && <Alert type="warning" showIcon message={t("Some overview data is unavailable", "部分概览数据暂不可用")} description={t("Recorded results stay visible. Refresh before making a decision.", "已加载记录会保留，请刷新后再作判断。")} action={<Button onClick={() => errors.forEach((query) => { void query.refetch(); })}>{t("Retry", "重试")}</Button>} />}
    <div className="overview-top-grid">
      <section className={`decision-panel tone-${tone}`} aria-label={t("Quality verdict", "质量判定")}>
        <div className="section-heading"><h2>{t("Quality verdict", "质量判定")}</h2><span className="muted">{latest ? `${t("Record", "记录")} #${latest.sequence_no}` : t("Evidence-driven decision", "基于证据的决策")}</span></div>
        {verdicts.isLoading ? <Skeleton active paragraph={{rows: 2}} /> : <>
          <div className="decision-title">{tone === "success" ? <CheckCircleOutlined aria-hidden /> : tone === "danger" || tone === "warning" ? <ExclamationCircleOutlined aria-hidden /> : <ClockCircleOutlined aria-hidden />}<h3>{latest ? label(latest.decision) : verdicts.error ? t("Verdict unavailable", "暂无法读取判定") : t("Awaiting a quality verdict", "等待质量判定")}</h3></div>
          {latest && <Tag>{label(latest.status)}</Tag>}
          <p className="decision-reason">{latest ? verdictReason(latest.reason) : t("After official execution, the quality gate checks coverage, trusted evidence and findings to record a decision.", "正式执行后，质量门禁将核对覆盖情况、可信证据和问题发现，并记录结论。")}</p>
          <div className="panel-bottom"><span>{latest ? formatDate(latest.created_at) : t("Task completion does not mean tests passed.", "任务完成不代表测试通过。")}</span><Button onClick={() => latest ? openVerdict(latest) : navigate("verdicts")}>{t("View rationale", "查看判定依据")} <ArrowRightOutlined aria-hidden /></Button></div>
        </>}
      </section>
      <section className="task-panel">
        <div className="section-heading"><h2>{t("Latest task", "最近任务")}</h2><Button type="link" onClick={() => navigate("tasks")}>{t("All tasks", "全部任务")} <ArrowRightOutlined aria-hidden /></Button></div>
        {jobs.isLoading ? <Skeleton active paragraph={{rows: 2}} /> : task ? <>
          <div className="task-title"><strong>{label(task.job_type)}</strong><Tag color={task.status === "WAITING_INPUT" ? "gold" : ["RUNNING", "QUEUED", "CANCEL_REQUESTED"].includes(task.status) ? "blue" : ["FAILED", "INTERRUPTED"].includes(task.status) ? "red" : undefined}>{label(task.status)}</Tag></div>
          <div className="entity-key">{task.key}</div>
          <p className="task-description">{task.status === "WAITING_INPUT" ? t("Testing is paused for clarification. Answer the recorded question to continue this task.", "测试已暂停等待澄清。请回答已记录的问题，继续此任务。") : task.error_message || (task.status === "SUCCEEDED" ? t("The operation finished. Review the quality verdict for the testing decision.", "本次操作已完成，测试结论以质量判定为准。") : ["RUNNING", "QUEUED", "CANCEL_REQUESTED"].includes(task.status) ? t("The worker processes this saved task. You can leave and return to review progress.", "任务已保存，由 Worker 处理。离开页面后仍可回来查看进度。") : t("Inspect the recorded history before starting recovery.", "恢复操作前，请先检查已保存的任务历史。"))}</p>
          <div className="panel-bottom"><span>{formatDate(task.started_at || task.created_at)}</span><Button onClick={() => openTask(task.id)}>{t("Task details", "任务详情")}</Button></div>
        </> : <div className="quiet-state"><ClockCircleOutlined aria-hidden /><p>{jobs.error ? t("Task status unavailable. Retry above.", "暂无法获取任务状态，请在上方重试。") : t("No tasks yet. Start a complete test cycle using the action above.", "暂无任务。通过上方操作开始完整测试周期。")}</p></div>}
      </section>
    </div>
    <nav className="evidence-trail" aria-label={t("Trace the testing decision", "追溯测试结论")}>
      {[
        { key: "executions", title: t("Executions", "执行记录"), query: executions },
        { key: "findings", title: t("Findings", "问题发现"), query: findings },
        { key: "evidence", title: t("Evidence", "证据"), query: evidence },
        { key: "verdicts", title: t("Verdicts", "质量判定"), query: verdicts },
      ].map(({key, title, query}) => <Button key={key} type="text" onClick={() => navigate(key)}><span>{title}</span><span className="trail-count">{query.data ? query.data.length.toLocaleString(locale === "zh" ? "zh-CN" : "en-US") : "—"}</span><ArrowRightOutlined aria-hidden /></Button>)}
    </nav>
    <div className="overview-bottom-grid">
      <section className="overview-section">
        <div className="section-heading"><h2>{t("Needs attention", "需要关注")}</h2><Button type="link" onClick={() => navigate("findings")}>{t("View findings", "查看发现")}</Button></div>
        {findings.isLoading || executions.isLoading ? <Skeleton active /> : <>
          {failedExecution && <div className="attention-item"><Tag color="red">{t("Recorded failure", "已记录的失败")}</Tag><Button className="text-link" type="link" onClick={() => openExecution(failedExecution)}>{failedExecution.key}</Button><p>{failedExecution.error_message || t("Open the official execution to inspect failed cases, logs and evidence. This record may precede the latest verdict.", "查看正式执行中的失败用例、日志和证据。此历史记录可能早于最新判定。")}</p></div>}
          {openFindings.slice(0, 3).map((finding) => <div className="attention-item" key={finding.id}><Space wrap><Tag color={finding.severity === "BLOCKER" || finding.severity === "CRITICAL" ? "red" : "gold"}>{label(finding.severity)}</Tag><span className="entity-key">{finding.key}</span><Tag>{label(finding.status)}</Tag></Space><Button type="link" className="text-link finding-link" onClick={() => openFinding(finding)}>{finding.title}</Button><p>{finding.root_cause || finding.description}</p></div>)}
          {!failedExecution && !openFindings.length && <div className="quiet-state"><FileSearchOutlined aria-hidden /><p>{findings.error || executions.error ? t("Attention items could not be checked. Retry above.", "暂无法检查关注事项，请在上方重试。") : t("No failures or open findings in the loaded records. Release readiness still depends on the quality verdict.", "已加载记录中暂无失败或未关闭的发现，能否发布仍以质量判定为准。")}</p></div>}
        </>}
      </section>
      <section className="overview-section">
        <div className="section-heading"><h2>{t("Recent evidence", "最近证据")}</h2><Button type="link" onClick={() => navigate("evidence")}>{t("All evidence", "全部证据")}</Button></div>
        {evidence.isLoading ? <Skeleton active /> : recentEvidence.length ? recentEvidence.map((item) => <div className="evidence-item" key={item.id}><div><Button type="link" className="text-link" onClick={() => openEvidence(item)}>{label(item.evidence_type)}</Button><span className="entity-key">{item.key}</span></div><Space wrap><Tag color={item.status === "VERIFIED" ? "green" : undefined}>{label(item.status)}</Tag><Tag>{label(item.trust_level)}</Tag></Space></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={evidence.error ? t("Evidence unavailable. Retry above.", "证据暂不可用，请在上方重试。") : t("Trusted Runner evidence will appear after execution.", "执行后将在这里展示可信 Runner 采集的证据。")} />}
        <p className="table-footnote">{t("Agent reports alone are not trusted execution facts.", "Agent 自述不能替代可信执行事实。")}</p>
      </section>
    </div>
  </div>;
}
