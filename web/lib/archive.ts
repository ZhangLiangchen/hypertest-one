import type { ReportedResult } from "@/lib/types";
import { ApiError } from "@/lib/api";

export const ARCHIVE_PROFILE = "local-artifact-archive/v1alpha1";
export type ArchiveTask = { id: string; project_id: string; title: string; objective: string; owner_uploader_actor_ref: string | null; version: number; archive_version: number; status: string; reported_result: ReportedResult; created_at: string; updated_at: string };
export type ArchiveSubtask = { id: string; task_id: string; project_id: string; title: string; objective: string; authorized_uploader_actor_ref: string | null; archive_version: number; status: string; reported_result: ReportedResult; created_at: string };
export type ArchiveAsset = { id: string; kind: "PLAN" | "CASE" | "REPORT"; stable_key: string; revision: number; title: string; content?: string; case?: Record<string, unknown>; reported_result: ReportedResult; origin: Record<string, unknown>; submission_id: string; accepted_at: string; [key: string]: unknown };
export type ArchivePublication = { id: string; task_version: number; root_archive_version: number; subtask_versions: { subtask_id: string; archive_version: number }[]; asset_revision_ids: string[]; omitted_subtask_ids: string[]; incomplete_subtask_ids: string[]; summary: string; status: string; reported_result: ReportedResult; created_at: string };
export type ArchiveReceipt = { profile?: string; project_id: string; task_id: string; idempotency_key: string; operation?: string; task_version?: number; [key: string]: unknown };
export type ArchiveManagement = { task: ArchiveTask; subtasks: ArchiveSubtask[]; receipt: ArchiveReceipt };
export type ArchiveDetail = { task: ArchiveTask; subtasks: ArchiveSubtask[]; publications: ArchivePublication[]; management_history: Record<string, unknown>[]; submission_history: Record<string, unknown>[] };
export type ArchiveSnapshot = { profile: string; project_id: string; task_id: string; target_kind: "TASK" | "SUBTASK"; subtask_id: string | null; archive_version: number; assets: ArchiveAsset[]; [key: string]: unknown };
export type ArchiveRequest = { project_id: string; idempotency_key: string; [key: string]: unknown };
export type ArchiveActors = { items: { actor_ref: string; label: string }[]; total: number };

export async function archiveApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/archive/${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers }, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : "ARCHIVE_REQUEST_FAILED");
  return body as T;
}
export const getArchiveTasks = (projectId: string, offset = 0) => archiveApi<{ items: ArchiveTask[]; total: number }>(`tasks?project_id=${encodeURIComponent(projectId)}&offset=${offset}&limit=20`);
export const getArchiveActors = (projectId: string) => archiveApi<ArchiveActors>(`actors?project_id=${encodeURIComponent(projectId)}`);
export const getArchiveTask = (projectId: string, taskId: string) => archiveApi<ArchiveDetail>(`tasks/${taskId}?project_id=${encodeURIComponent(projectId)}`);
export const getArchiveSnapshot = (projectId: string, taskId: string, version: number, subtaskId?: string) => archiveApi<ArchiveSnapshot>(`tasks/${taskId}/${subtaskId ? `subtasks/${subtaskId}/` : ""}archive?project_id=${encodeURIComponent(projectId)}&archive_version=${version}&readback=complete`);
export const getArchiveOperation = (projectId: string, key: string) => archiveApi<ArchiveManagement>(`operations/by-key?project_id=${encodeURIComponent(projectId)}&idempotency_key=${encodeURIComponent(key)}`);
export const archiveManage = (path: string, payload: ArchiveRequest) => archiveApi<ArchiveManagement>(path, { method: "POST", body: JSON.stringify(payload) });

/** IDs are explicit. Omission is the task root; no default or guessed child. */
export function archiveSkillInstruction(projectId: string, taskId: string, subtaskId?: string, english = false): string {
  return `$hypertest-archive\n${english ? "Archive the approved test artifacts using profile default." : "请使用 profile default 归档本轮正式测试产物。"}\n--project-id ${projectId} --task-id ${taskId}${subtaskId ? ` --subtask-id ${subtaskId}` : ""}\n${english ? "Artifact scope: replace with the approved absolute file paths or manifest." : "产物范围：请填写获准的绝对文件路径或清单。"}`;
}
