"use client";

import { Alert, Button, Empty, Space, Spin, Tag, Typography } from "antd";
import { useId } from "react";

import { useI18n } from "@/lib/i18n";
import { activityKindLabels, activityPhaseLabels, activityTimestamp, activityTiming, MAX_ACTIVITY_ITEMS, visibleActivityItems } from "@/lib/job-activity";
import type { ActivityFeed } from "@/lib/job-activity";
import type { BackgroundJob, JobActivity } from "@/lib/types";
import { useJobActivity } from "./use-job-activity";

const missionTypes = new Set(["ANALYZE_REQUIREMENTS", "ANALYZE_IMPACT", "ANALYZE_RISKS", "DESIGN_TESTS", "REVIEW_TESTS", "IMPLEMENT_TESTS", "REVIEW_IMPLEMENTATION", "DIAGNOSE_FAILURE", "INVESTIGATE_FINDING", "REPAIR_TEST", "RETEST_ANALYSIS", "VERIFY_COVERAGE"]);

type ViewProps = {
  job: BackgroundJob;
  activity?: JobActivity;
  feed: ActivityFeed;
  loading: boolean;
  refreshing: boolean;
  refreshFailed: boolean;
  taskStale: boolean;
  olderLoading: boolean;
  olderFailed: boolean;
  cursorExpired: boolean;
  onRefresh: () => void;
  onEarlier: () => void;
  onReset: () => void;
  onResults: () => void;
};

// This view deliberately accepts no event detail, message, command or raw payload.
export function JobActivityView({ job, activity, feed, loading, refreshing, refreshFailed, taskStale, olderLoading, olderFailed, cursorExpired, onRefresh, onEarlier, onReset, onResults }: ViewProps) {
  const { t, label, formatDate } = useI18n();
  const headingId = useId();
  const timing = activity ? activityTiming(job, activity, refreshFailed || taskStale) : null;
  const phase = timing?.phase;
  const attempt = activity?.summary.current_attempt;
  const rows = visibleActivityItems(feed.items);

  function ageText(seconds: number | null | undefined) {
    if (seconds === null || seconds === undefined) return t("Elapsed time unavailable", "未提供经过时间");
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.floor(seconds % 60);
    return minutes ? t(`${minutes} min ${remainder} s ago`, `${minutes} 分 ${remainder} 秒前`) : t(`${remainder} s ago`, `${remainder} 秒前`);
  }
  function observed(timestamp: string | null | undefined, age: number | null | undefined, empty: string) {
    return activityTimestamp(timestamp) ? <><time dateTime={timestamp}>{formatDate(timestamp)}</time><span className="activity-age">{ageText(age)}</span></> : empty;
  }

  return <section className="job-activity" aria-labelledby={headingId}>
    <div className="activity-heading">
      <Typography.Title level={4} id={headingId}>{t("Agent activity", "Agent 活动")}</Typography.Title>
      <Button size="small" loading={refreshing} onClick={onRefresh}>{t("Refresh activity", "刷新活动")}</Button>
    </div>
    <Typography.Paragraph className="muted activity-explanation">{t("Runtime signals are supporting information. They do not prove model connectivity, accepted proposals or test results. Formal results come from executions, evidence and quality verdicts.", "运行信号仅作辅助，不代表模型连接正常、Proposal 已接受或测试已通过。正式结果请查看执行、证据与质量判定。")}</Typography.Paragraph>
    {refreshFailed && <Alert type="warning" showIcon message={t("Activity has not refreshed", "活动暂未刷新")} description={t("Previously loaded records remain below. Refresh activity to try again; no task will be restarted.", "下方保留已加载记录。可点击“刷新活动”重试读取，此操作不会重启任务。")} />}
    {loading && !activity ? <div className="activity-loading"><Spin size="small" /><span>{t("Loading activity", "正在加载活动")}</span></div> : activity && timing && <>
      <dl className="activity-summary">
        <div><dt>{t("Recorded stage", "已记录阶段")}</dt><dd><Tag>{t(...activityPhaseLabels[timing.phase])}</Tag></dd></div>
        <div><dt>{t("Mission / attempt", "测试任务 / 尝试")}</dt><dd>{attempt ? <><span>{missionTypes.has(attempt.mission_type) ? label(attempt.mission_type) : t("Agent mission", "Agent 测试任务")}</span><span className="activity-identity">{attempt.mission_key} · {t(`Attempt ${attempt.attempt_no}`, `第 ${attempt.attempt_no} 次尝试`)}</span></> : t("No Agent attempt is currently running", "当前没有运行中的 Agent 尝试")}</dd></div>
        <div><dt>{t("Last Agent runtime signal", "最近 Agent 运行信号")}</dt><dd>{observed(activity.summary.last_provider_signal_at, timing.signalAge, t("No signal recorded for this turn", "本轮尚无运行信号记录"))}</dd></div>
        <div><dt>{t("This task's Worker heartbeat", "本任务 Worker 心跳")}</dt><dd>{observed(activity.summary.worker_heartbeat_at, timing.heartbeatAge, t("No heartbeat recorded", "尚无心跳记录"))}</dd></div>
      </dl>
      <Typography.Paragraph className="muted activity-clock">{t("Times and ages reflect the last server read", "时间与间隔以最近一次服务端读取为准")} · {activityTimestamp(activity.server_time) ? formatDate(activity.server_time) : "—"}</Typography.Paragraph>
      {timing.quiet && <Alert type="info" showIcon message={t("No new runtime signal for a while", "一段时间未收到新运行信号")} description={t("The Agent may still be working normally. A Worker heartbeat only confirms the worker's lease, and neither signal proves model connectivity. You can refresh or use the existing task controls; no automatic retry occurs.", "Agent 仍可能正常工作。Worker 心跳仅反映 Worker 租约，两类信号都不能证明模型连接正常。可刷新，或使用原有任务操作；系统不会据此自动重试。")} />}
      {phase === "WAITING_INPUT" && <Typography.Paragraph className="activity-state-note">{t("This task is waiting for your answer. Use Answer question above to resume the same task; runtime silence is expected while it waits.", "此任务正在等待你的回答。请使用上方“回答问题”恢复同一任务，等待期间没有运行信号属于正常情况。")}</Typography.Paragraph>}
      {phase === "RESULT_VALIDATION" && <Typography.Paragraph className="activity-state-note">{t("A structured result has arrived. HyperTest still needs to validate it before any proposal becomes official state.", "已收到结构化结果。Proposal 成为正式状态前，仍需由 HyperTest 验证。")}</Typography.Paragraph>}
      {phase === "TERMINAL" && <div className="activity-result-link"><span>{t("Activity history does not determine the testing decision.", "活动历史不能代替测试结论。")}</span><Button size="small" onClick={onResults}>{t("View quality verdicts", "查看质量判定")}</Button></div>}
    </>}
    <Typography.Title level={5}>{t("Recent recorded activity", "最近活动记录")}</Typography.Title>
    {rows.length ? <ol className="activity-records">
      {rows.map((item) => <li key={item.id}>
        <div className="activity-record-main"><strong>{t(...activityKindLabels[item.kind])}</strong><Space size={4} wrap><Tag>{item.source === "PROVIDER" ? t("Agent runtime", "Agent 运行时") : "HyperTest"}</Tag>{item.count > 1 && <span className="activity-count">{t(`${item.count} signals`, `${item.count} 次信号`)}</span>}</Space></div>
        <div className="activity-record-meta"><time dateTime={item.last_observed_at}>{formatDate(item.last_observed_at)}</time><span>{t("Mission", "测试任务")} <code>{item.mission_id}</code></span></div>
      </li>)}
    </ol> : !loading && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("No displayable activity recorded yet. Task status and formal testing records remain authoritative.", "暂无可展示的活动记录。任务状态与正式测试记录仍为权威。")} />}
    {olderFailed && <Alert type="warning" showIcon message={cursorExpired ? t("Earlier activity is no longer available at this position", "此位置的更早活动已不可读取") : t("Unable to load earlier activity", "暂时无法读取更早活动")} description={cursorExpired ? t("Retention removed this cursor. Loaded records remain visible; reload recent records to continue browsing.", "保留策略已移除此游标。已加载记录仍会保留，请重新加载最近记录后继续查看。") : t("Loaded records remain visible. Try loading earlier records again.", "已加载记录仍会保留。可再次尝试读取更早记录。") } />}
    <div className="activity-pagination">
      {feed.nextCursor && !feed.atLimit && !cursorExpired && <Button loading={olderLoading} disabled={refreshing} onClick={onEarlier}>{t("Load earlier activity", "读取更早活动")}</Button>}
      {(cursorExpired || feed.atLimit) && <Button loading={refreshing} disabled={olderLoading} onClick={onReset}>{t("Reload recent records", "重新加载最近记录")}</Button>}
      {feed.atLimit && <span className="muted">{t(`Showing up to ${MAX_ACTIVITY_ITEMS} recent records in this view.`, `此视图最多显示最近 ${MAX_ACTIVITY_ITEMS} 条记录。`)}</span>}
    </div>
    {activity && <Typography.Paragraph className="muted activity-footnote">{t("Newest first. Repeated signals of one kind are grouped; counts are not completed work or test progress.", "按时间从新到旧显示，同类重复信号会合并。次数不表示已完成工作量或测试进度。")}{feed.truncated && ` ${t("Older records were removed by the per-attempt retention limit; this timeline is incomplete.", "部分较早记录已按单次尝试的保留上限移除，此时间线并不完整。")}`}</Typography.Paragraph>}
  </section>;
}

export function JobActivityPanel({ job, taskStale, onResults }: { job: BackgroundJob; taskStale: boolean; onResults: () => void }) {
  const { latest, feed, older, cursorExpired, reset, loadEarlier } = useJobActivity(job);
  return <JobActivityView job={job} activity={latest.data} feed={feed} loading={latest.isPending} refreshing={latest.isFetching} refreshFailed={latest.isError} taskStale={taskStale} olderLoading={older.isPending} olderFailed={older.isError} cursorExpired={cursorExpired} onRefresh={() => void latest.refetch()} onEarlier={loadEarlier} onReset={() => void reset()} onResults={onResults} />;
}
