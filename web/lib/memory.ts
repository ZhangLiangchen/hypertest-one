/** Memory is optional historical context, with its own authorization and receipts. */
export const MEMORY_PROFILE = "hypertest-project-memory/v1alpha1";
export type MemoryAction = "CONFIGURE" | "CREATE_CANDIDATE" | "PUBLISH" | "REVISE" | "RETRACT";
export type MemorySource = { mode: "LOCAL" | "CLOUD" | "LOCAL_ARCHIVE"; task_id: string; task_version?: number; archive_version?: number; submission_id?: string; report_id?: string; attempt_id?: string; asset_revision_id?: string };
export type MemoryEntry = { id: string; project_id: string; version: number; status: "CANDIDATE" | "PUBLISHED" | "RETRACTED" | "PENDING" | "SUPERSEDED" | "EXPIRED"; revision_status?: "CANDIDATE" | "PUBLISHED" | "RETRACTED"; title: string; content: string; source?: MemorySource | null; publication_note?: string; applicability?: string; observed_at?: string; expires_at?: string; created_at?: string; updated_at?: string };
export type MemoryConfiguration = { project_id?: string; enabled: boolean; version: number; scope_id?: string; status?: string };
export type MemoryProject = { profile: string; enabled: boolean; configuration: MemoryConfiguration; entries: MemoryEntry[]; operations: MemoryReceipt[]; offset?: number; limit?: number; has_more?: boolean };
export type MemoryMutation = { project_id: string; operation_key: string; operation: MemoryAction; expected_version: number; entry_id?: string; title?: string; content?: string; source?: MemorySource; publication_note?: string; applicability?: string; observed_at?: string; expires_at?: string; enabled?: boolean };
export type MemoryPending = { project_id: string; operation_key: string; operation: MemoryAction; expected_version: number; entry_id?: string; digest: string; state: "SENT" | "UNKNOWN" };
export type MemoryReceipt = { profile: string; project_id: string; operation_key: string; operation: MemoryAction; status: "ACCEPTED" | "SENT" | "UNKNOWN"; entry_id?: string; accepted_version?: number; expected_version?: number; request_digest?: string };
export class MemoryApiError extends Error { constructor(public status: number, public code: string) { super(code); } }

export async function memoryRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/memory/${path}`, { ...init, headers: { "Content-Type": "application/json" }, cache: "no-store" });
  if (!response.ok) { let code = "MEMORY_UNAVAILABLE"; try { const body = await response.json(); if (typeof body.code === "string") code = body.code; } catch { /* No raw upstream data leaves this boundary. */ } throw new MemoryApiError(response.status, code); }
  return response.json() as Promise<T>;
}
export const memoryProject = (projectId: string, status = "PUBLISHED", offset = 0) => memoryRequest<MemoryProject>(`projects/${encodeURIComponent(projectId)}?${new URLSearchParams({ status, offset: String(offset), limit: "20" })}`);
export const memoryConfiguration = (projectId: string, version: number) => memoryRequest<MemoryConfiguration>(`projects/${encodeURIComponent(projectId)}/configuration?version=${version}`);
export const memoryEntry = (projectId: string, entryId: string, version: number) => memoryRequest<MemoryEntry>(`entries/${encodeURIComponent(entryId)}?project_id=${encodeURIComponent(projectId)}&version=${version}`);
export const memoryOperation = (projectId: string, key: string) => memoryRequest<MemoryReceipt>(`operations/by-key?${new URLSearchParams({ project_id: projectId, operation_key: key })}`);
export const memoryQuery = (projectId: string, query: string) => memoryRequest<{ results: MemoryEntry[]; degraded?: boolean }>("query", { method: "POST", body: JSON.stringify({ project_id: projectId, query, limit: 20 }) });

export function parseMemoryPending(value: unknown, projectId: string): MemoryPending {
  if (!value || typeof value !== "object") throw new Error("MEMORY_JOURNAL_INVALID");
  const row = value as MemoryPending;
  if (row.project_id !== projectId || typeof row.operation_key !== "string" || !/^[A-Za-z0-9_.:-]{1,128}$/.test(row.operation_key)
    || !["CONFIGURE", "CREATE_CANDIDATE", "PUBLISH", "REVISE", "RETRACT"].includes(row.operation) || !["SENT", "UNKNOWN"].includes(row.state)
    || !Number.isSafeInteger(row.expected_version) || row.expected_version < 0 || !/^[a-f0-9]{64}$/.test(row.digest)
    || (!["CONFIGURE", "CREATE_CANDIDATE"].includes(row.operation) && typeof row.entry_id !== "string")) throw new Error("MEMORY_JOURNAL_INVALID");
  return { project_id: row.project_id, operation_key: row.operation_key, operation: row.operation, expected_version: row.expected_version, state: row.state, digest: row.digest,
    ...(typeof row.entry_id === "string" ? { entry_id: row.entry_id } : {}) };
}
export async function memoryDigest(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
export function memoryReceiptMatches(pending: MemoryPending, receipt: MemoryReceipt): boolean {
  return receipt.profile === MEMORY_PROFILE && receipt.status === "ACCEPTED" && receipt.project_id === pending.project_id
    && receipt.operation_key === pending.operation_key && receipt.operation === pending.operation
    && receipt.expected_version === pending.expected_version && receipt.accepted_version === pending.expected_version + 1
    && (pending.entry_id ? receipt.entry_id === pending.entry_id : pending.operation === "CONFIGURE" || typeof receipt.entry_id === "string");
}
