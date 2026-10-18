import type { ActivityKind, ActivityPhase, BackgroundJob, JobActivity, JobActivityItem } from "@/lib/types";

export const MAX_ACTIVITY_ITEMS = 300;
export const QUIET_SIGNAL_SECONDS = 300;

export const activityKindLabels: Record<ActivityKind, readonly [string, string]> = {
  SIGNAL_RECEIVED: ["Runtime signal received", "收到运行信号"],
  TURN_STARTED: ["Agent turn started", "Agent 轮次开始"],
  TURN_COMPLETED: ["Agent turn ended", "Agent 轮次结束"],
  MODEL_ACTIVITY: ["Agent activity signal", "Agent 活动信号"],
  TOOL_STARTED: ["Tool activity started", "工具活动开始"],
  TOOL_COMPLETED: ["Tool activity ended", "工具活动结束"],
  FILE_ACTIVITY: ["File activity signal", "文件活动信号"],
  MISSION_STARTED: ["Mission started", "测试任务开始"],
  RESUMED: ["Mission resumed", "测试任务已恢复"],
  RESULT_SUBMITTED: ["Result received; awaiting validation", "已收到结果，待验证"],
  MISSION_FINISHED: ["Mission ended", "测试任务结束"],
  ERROR: ["Runtime error signal", "运行错误信号"],
};
export const activityPhaseLabels: Record<ActivityPhase, readonly [string, string]> = {
  QUEUED: ["Waiting for a worker", "等待 Worker"],
  WAITING_INPUT: ["Waiting for your answer", "等待你的回答"],
  CANCEL_REQUESTED: ["Cancellation requested", "已请求取消"],
  AGENT_RUNNING: ["Agent mission running", "Agent 任务运行中"],
  RESULT_VALIDATION: ["Validating the submitted result", "正在验证提交结果"],
  PLATFORM_WORK: ["HyperTest operation in progress", "HyperTest 操作处理中"],
  TERMINAL: ["Task ended", "任务已结束"],
};

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function activityTimestamp(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value));
}

// Explicit projection prevents new provider fields or unknown event names reaching the UI.
export function visibleActivityItems(items: readonly unknown[]): JobActivityItem[] {
  return items.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;
    if (typeof row.kind !== "string" || !Object.hasOwn(activityKindLabels, row.kind)
      || !["PROVIDER", "CONTROL_PLANE"].includes(row.source as string)
      || ![row.id, row.mission_id, row.attempt_id].every((id) => typeof id === "string" && uuid.test(id))
      || !activityTimestamp(row.recorded_at) || !activityTimestamp(row.last_observed_at)
      || Date.parse(row.last_observed_at) < Date.parse(row.recorded_at)
      || !Number.isSafeInteger(row.count) || (row.count as number) < 1) return [];
    return [{
      id: row.id as string, kind: row.kind as ActivityKind, source: row.source as JobActivityItem["source"],
      recorded_at: row.recorded_at, last_observed_at: row.last_observed_at, count: row.count as number,
      mission_id: row.mission_id as string, attempt_id: row.attempt_id as string,
      agent_session_id: typeof row.agent_session_id === "string" && uuid.test(row.agent_session_id) ? row.agent_session_id : null,
    }];
  });
}

export type ActivityFeed = { items: JobActivityItem[]; nextCursor: string | null; atLimit: boolean; truncated: boolean; headTime: string | null };
export function emptyActivityFeed(): ActivityFeed {
  return { items: [], nextCursor: null, atLimit: false, truncated: false, headTime: null };
}

export function reconcileActivity(previous: ActivityFeed, page: JobActivity, mode: "head" | "older" | "reset", requestedCursor?: string): ActivityFeed {
  if (mode === "head" && previous.headTime && Date.parse(page.server_time) < Date.parse(previous.headTime)) return previous;
  const prior = mode === "reset" ? emptyActivityFeed() : previous;
  const incoming = visibleActivityItems(page.items);
  const records = new Map(prior.items.map((item) => [item.id, item]));
  const overlaps = incoming.some((item) => records.has(item.id));
  for (const item of incoming) {
    const old = records.get(item.id);
    records.set(item.id, old ? {
      ...old,
      count: Math.max(old.count, item.count),
      last_observed_at: Date.parse(item.last_observed_at) > Date.parse(old.last_observed_at) ? item.last_observed_at : old.last_observed_at,
    } : item);
  }
  const ordered = [...records.values()].sort((a, b) => Date.parse(b.recorded_at) - Date.parse(a.recorded_at) || b.id.localeCompare(a.id));
  // A missed latest-page window may leave a gap. Rewind explicit pagination to that
  // page's cursor, retaining loaded rows, so asking for earlier records fills it.
  const cursor = mode === "older" && requestedCursor && requestedCursor !== prior.nextCursor ? prior.nextCursor
    : mode !== "head" || !prior.headTime || (incoming.length > 0 && !overlaps) ? page.next_cursor : prior.nextCursor;
  return {
    items: ordered.slice(0, MAX_ACTIVITY_ITEMS), nextCursor: cursor,
    atLimit: prior.atLimit || ordered.length > MAX_ACTIVITY_ITEMS || (ordered.length === MAX_ACTIVITY_ITEMS && !!cursor),
    truncated: prior.truncated || page.truncated,
    headTime: mode === "older" ? prior.headTime : page.server_time,
  };
}

export function effectiveActivityPhase(status: BackgroundJob["status"], phase: string): ActivityPhase {
  if (["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"].includes(status)) return "TERMINAL";
  if (status === "WAITING_INPUT" || status === "CANCEL_REQUESTED" || status === "QUEUED") return status;
  return Object.hasOwn(activityPhaseLabels, phase) ? phase as ActivityPhase : "PLATFORM_WORK";
}

export function serverElapsed(serverTime: string, timestamp: string | null, suppliedAge?: number | null): number | null {
  if (!activityTimestamp(serverTime) || !activityTimestamp(timestamp)) return null;
  const elapsed = (Date.parse(serverTime) - Date.parse(timestamp)) / 1000;
  if (elapsed < 0) return null;
  return typeof suppliedAge === "number" && Number.isFinite(suppliedAge) && suppliedAge >= 0 ? suppliedAge : elapsed;
}

export function activityTiming(job: Pick<BackgroundJob, "status">, activity: JobActivity, stale: boolean) {
  const summary = activity.summary;
  const phase = effectiveActivityPhase(job.status, summary.phase);
  const signalAge = serverElapsed(activity.server_time, summary.last_provider_signal_at, summary.provider_signal_age_seconds);
  const turnAge = serverElapsed(activity.server_time, summary.turn_started_at);
  return {
    phase, signalAge,
    heartbeatAge: serverElapsed(activity.server_time, summary.worker_heartbeat_at, summary.worker_heartbeat_age_seconds),
    quiet: !stale && phase === "AGENT_RUNNING" && (signalAge ?? turnAge ?? -1) >= QUIET_SIGNAL_SECONDS,
  };
}
