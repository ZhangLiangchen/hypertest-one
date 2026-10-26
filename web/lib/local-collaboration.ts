import type { ReportedResult, SessionTask } from "@/lib/types";

export const collaborationProfile = "local-task-collaboration/v1alpha1" as const;
export type CollaborationOperation = "ENABLE" | "AUTHORIZE" | "REVOKE" | "HANDOFF";
export type TaskParticipant = {
  id: string; task_id: string; project_id: string; provider: string; session_id: string; actor_ref: string;
  role: "PRIMARY" | "CONTRIBUTOR"; status: "AUTHORIZED" | "ACTIVE" | "REVOKED"; assignment: string;
  initial_binding: boolean;
  authorized_at: string; joined_at: string | null; revoked_at: string | null; created_at: string;
};
export type TaskContribution = {
  id: string; task_id: string; participant_id: string; kind: "PLAN" | "CASE" | "REPORT" | "REVIEW";
  stable_key: string; revision: number; task_version: number; content: Record<string, unknown> & { reported_result?: ReportedResult };
  actor_ref: string; provider: string; session_id: string; created_at: string;
};
export type CollaborationRequest = {
  profile: typeof collaborationProfile; operation: CollaborationOperation; expected_version: number; idempotency_key: string;
  actor_ref?: string; provider?: string; session_id?: string; assignment?: string; participant_id?: string;
  expected_primary_generation?: number;
  handoff?: { materials: string[]; unresolved_items: string[]; private_journals_observed: false };
};
export type CollaborationReceipt = {
  status: "ACCEPTED"; profile: typeof collaborationProfile; operation: string; idempotency_key: string;
  project_id: string; task_id: string; provider: string | null; session_id: string | null; actor_ref: string;
  participant_id: string | null; version: number; request_digest: string; primary_generation: number;
  contribution_refs: unknown[];
};
export type CollaborationDocument = {
  profile: typeof collaborationProfile;
  task: SessionTask & { collaboration_enabled: boolean; primary_participant_id: string | null; primary_generation: number };
  collaboration: {
    enabled: boolean; primary_participant_id: string | null; primary_generation: number;
    participants: TaskParticipant[]; contributions: TaskContribution[];
    publications: { task_version: number; participant_id: string; primary_generation: number; summary: Record<string, unknown>; created_at: string }[];
  };
  operation_history: {
    id: string; task_id: string; project_id: string; actor_ref: string; operation: string; idempotency_key: string;
    input_digest: string; task_version: number; provider: string | null; session_id: string | null; participant_id: string | null;
    request_payload: Record<string, unknown>; response: CollaborationReceipt; created_at: string;
  }[];
};
export type CollaborationPending = {
  project_id: string; task_id: string; operation_key: string; state: "SENT" | "UNKNOWN"; payload: CollaborationRequest;
};
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((value, index) => same(value, b[index]));
  if (object(a) && object(b)) return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((key) => Object.hasOwn(b, key) && same(a[key], b[key]));
  return Object.is(a, b);
}
export function validateCollaborationPending(value: unknown, projectId: string): CollaborationPending {
  const row = value as CollaborationPending, payload = row?.payload;
  if (!row || row.project_id !== projectId || !row.task_id || !["SENT", "UNKNOWN"].includes(row.state)
    || !payload || payload.profile !== collaborationProfile || !["ENABLE", "AUTHORIZE", "REVOKE", "HANDOFF"].includes(payload.operation)
    || !Number.isSafeInteger(payload.expected_version) || payload.expected_version < 1 || !payload.idempotency_key || row.operation_key !== payload.idempotency_key
    || (payload.operation === "AUTHORIZE" && (!payload.actor_ref || !payload.provider || !payload.session_id || typeof payload.assignment !== "string"))
    || (["REVOKE", "HANDOFF"].includes(payload.operation) && !payload.participant_id)
    || (payload.operation === "HANDOFF" && (!Number.isSafeInteger(payload.expected_primary_generation) || !payload.handoff
      || !Array.isArray(payload.handoff.materials) || !Array.isArray(payload.handoff.unresolved_items) || payload.handoff.private_journals_observed !== false))) throw new Error("LOCAL_COLLABORATION_PENDING_INVALID");
  return JSON.parse(JSON.stringify(row)) as CollaborationPending;
}
/** A key conflict is uncertain: only explicit rejection of a new request settles it. */
export function collaborationWasRejected(error: unknown): boolean {
  const value = error as { status?: number; detail?: string };
  return [400, 401, 403, 404, 409, 410, 422].includes(value?.status || 0) && !/KEY_CONFLICT/.test(value?.detail || "");
}
export function validateCollaborationReadback(original: CollaborationPending, receipt: CollaborationReceipt, doc: CollaborationDocument): CollaborationDocument {
  const mismatch = () => { throw new Error("LOCAL_COLLABORATION_READBACK_PENDING"); };
  const request = original.payload;
  if (!receipt || receipt.status !== "ACCEPTED" || receipt.profile !== collaborationProfile || receipt.operation !== request.operation
    || receipt.idempotency_key !== original.operation_key || receipt.project_id !== original.project_id || receipt.task_id !== original.task_id
    || receipt.version !== request.expected_version + 1 || !receipt.request_digest || !receipt.actor_ref || receipt.provider !== null || receipt.session_id !== null
    || receipt.participant_id !== null || !Array.isArray(receipt.contribution_refs)) return mismatch();
  const state = doc?.collaboration, task = doc?.task;
  if (doc?.profile !== collaborationProfile || !task || task.id !== original.task_id || task.project_id !== original.project_id || task.version !== receipt.version
    || !state || !state.enabled || state.primary_generation !== receipt.primary_generation || state.enabled !== task.collaboration_enabled
    || state.primary_participant_id !== task.primary_participant_id || state.primary_generation !== task.primary_generation
    || ![state.participants, state.contributions, state.publications, doc.operation_history].every(Array.isArray)
    || !["title", "objective", "plan_markdown", "status", "reported_result", "created_at", "provider", "session_id", "source"].every((key) => Object.hasOwn(task, key))) return mismatch();
  const history = doc.operation_history.find((entry) => entry.idempotency_key === original.operation_key && entry.task_version === receipt.version);
  if (!history || history.task_id !== task.id || history.project_id !== task.project_id || history.operation !== request.operation
    || history.input_digest !== receipt.request_digest || !same(history.response, receipt)
    || !Object.keys(request).every((key) => same(request[key as keyof CollaborationRequest], history.request_payload[key]))) return mismatch();
  if (request.operation === "AUTHORIZE" && !state.participants.some((p) => p.actor_ref === request.actor_ref && p.provider === request.provider
    && p.session_id === request.session_id && p.assignment === request.assignment && p.status === "AUTHORIZED")) return mismatch();
  if (request.operation === "REVOKE" && !state.participants.some((p) => p.id === request.participant_id && p.status === "REVOKED")) return mismatch();
  if (request.operation === "HANDOFF" && (state.primary_participant_id !== request.participant_id || state.primary_generation !== (request.expected_primary_generation || 0) + 1
    || !state.participants.some((p) => p.id === request.participant_id && p.role === "PRIMARY" && p.status === "ACTIVE"))) return mismatch();
  return doc;
}
