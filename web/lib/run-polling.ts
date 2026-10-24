import type { CloudDocument, CloudLiveSummary } from "./cloud";

export type PollInterval = number | false;
type StatusRecord = { status: string };

const activeJobs = new Set(["QUEUED", "RUNNING", "CANCEL_REQUESTED"]);
const settledJobs = new Set(["SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"]);
const settledRuns = new Set(["COMPLETED", "CANCELLED"]);

/** Waiting, blocked and unknown states retain a control observer. */
export function runPollInterval(status?: string): PollInterval {
  if (status && settledRuns.has(status)) return false;
  if (!status || ["ANALYZING", "DESIGNING", "IMPLEMENTING", "EXECUTING", "DIAGNOSING", "VERIFYING"].includes(status)) return 5_000;
  return 15_000;
}

export function jobPollInterval(status?: string): PollInterval {
  if (status && settledJobs.has(status)) return false;
  if (!status || activeJobs.has(status)) return 1_500;
  return status === "WAITING_INPUT" ? 5_000 : 15_000;
}

export function jobsPollInterval(jobs?: StatusRecord[], runStatus?: string): PollInterval {
  if (!jobs || jobs.some((job) => activeJobs.has(job.status))) return 1_500;
  if (jobs.some((job) => !settledJobs.has(job.status))) return 5_000;
  return runStatus && settledRuns.has(runStatus) ? false : 15_000;
}

export function inputPollInterval(requests: StatusRecord[] | undefined, jobs: StatusRecord[], runStatus?: string): PollInterval {
  if (requests?.some((request) => ["PENDING", "ANSWERED"].includes(request.status)) || jobs.some((job) => !settledJobs.has(job.status))) return 5_000;
  return runStatus && settledRuns.has(runStatus) ? false : 15_000;
}

export function harnessPollInterval(harness: { binding?: StatusRecord | null; issues?: StatusRecord[] } | undefined, jobs: StatusRecord[], runStatus?: string): PollInterval {
  if (jobs.some((job) => !settledJobs.has(job.status))) return 5_000;
  if (harness?.issues?.some((issue) => ["PENDING", "UNKNOWN"].includes(issue.status))) return 15_000;
  if (!harness || harness.binding && !["CLOSED", "FAILED", "CANCELLED"].includes(harness.binding.status)) return 15_000;
  return runStatus && settledRuns.has(runStatus) ? false : 15_000;
}

/** Hidden record panels keep their cache and drafts without scheduling timers. */
export function runRecordsPollInterval(runStatus: string | undefined, visible: boolean, jobs: StatusRecord[] = []): PollInterval {
  if (!visible) return false;
  if (jobs.some((job) => !settledJobs.has(job.status))) return 5_000;
  return runPollInterval(runStatus);
}

export function missionPollInterval(status?: string): PollInterval {
  if (status && ["COMPLETED", "FAILED", "CANCELLED", "REJECTED"].includes(status)) return false;
  return status === "WAITING_INPUT" || status === "BLOCKED" ? 15_000 : 3_000;
}

export function cloudPollingVersion(projectId: string, taskId: string, live?: CloudLiveSummary): number | undefined {
  if (!live || live.id !== taskId || live.project_id !== projectId || !Number.isSafeInteger(live.version) || live.version < 1) return undefined;
  if (live.latest_attempt_id ? live.current_attempt?.id !== live.latest_attempt_id : live.current_attempt !== null) return undefined;
  return live.version;
}

export function cloudSummaryPollInterval(projectId: string, taskId: string, live?: CloudLiveSummary): PollInterval {
  if (cloudPollingVersion(projectId, taskId, live) === undefined) return 3_000;
  if (live!.resolutions?.some((resolution) => ["PENDING", "RESOLVING"].includes(String(resolution.status)))) return 3_000;
  if (["QUEUED", "PREPARING", "RUNNING"].includes(live!.status)) return 3_000;
  if (["COMPLETED", "FAILED", "CANCELLED"].includes(live!.status)) return live!.recovery && live!.recovery.phase !== "TERMINATED" ? 15_000 : false;
  return 15_000;
}

/** Pin each complete read to its observed accepted version; never replace it with a summary. */
export async function readCloudPollingDocument(projectId: string, taskId: string, live: CloudLiveSummary | undefined,
  read: (projectId: string, taskId: string, version: number) => Promise<CloudDocument>): Promise<CloudDocument> {
  const version = cloudPollingVersion(projectId, taskId, live);
  if (version === undefined) throw new Error("Cloud summary identity is not verified");
  const document = await read(projectId, taskId, version);
  if (document.task.id !== taskId || document.task.project_id !== projectId || document.task.version !== version
    || document.task.latest_attempt_id !== live!.latest_attempt_id) throw new Error("Cloud accepted version did not match its observed identity");
  return document;
}
