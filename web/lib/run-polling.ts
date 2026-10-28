import type { CloudDocument, CloudLiveSummary } from "./cloud";

export type PollInterval = number | false;
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
