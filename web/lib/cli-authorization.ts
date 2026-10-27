import { ApiError } from "@/lib/api";
import type { LocalWebPending } from "@/lib/archive-operation";
export type CliGrant = { grant_id: string; request_id: string; client_instance_id: string; client_name: string; actor_ref: string; project_id: string; scopes: string[]; expires_at: string; status: string; credential_fingerprint: string; idempotency_key?: string };
export type CliApproval = { idempotency_key: string; actor_identity_id: string; actor_ref: string; project_ids: string[]; scopes: string[]; expires_in_days: number; expires_at: string; approval_digest: string };
export type CliRequest = { request_id: string; status: "PENDING" | "APPROVED" | "BOUND" | "DENIED" | "EXPIRED"; client_instance_id: string; client_name: string; server_url: string; requested_project_id?: string | null; short_code: string; expires_at: string; credential_fingerprint: string; approval: CliApproval | null; grants: CliGrant[] };
export async function cliAuthorizationApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/cli-authorizations/${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers }, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, typeof body.detail === "string" ? body.detail : "CLI_AUTH_REQUEST_FAILED");
  return body as T;
}
const list = (value: unknown) => Array.isArray(value) ? [...value].sort().join("|") : "";
export function validateCliApproval(original: LocalWebPending, value: CliRequest): CliRequest {
  const approval = value.approval;
  if (!approval || value.request_id !== original.path.split("/")[1] || approval.idempotency_key !== original.operation_key
    || typeof approval.actor_identity_id !== "string" || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(approval.actor_identity_id)
    || approval.actor_ref !== `interactive:${approval.actor_identity_id}`
    // Earlier frozen approvals selected an actor; their original identity must still match.
    || ("actor_identity_id" in original.payload && approval.actor_identity_id !== original.payload.actor_identity_id) || list(approval.project_ids) !== list(original.payload.project_ids)
    || list(approval.scopes) !== list(original.payload.scopes) || approval.expires_in_days !== original.payload.expires_in_days
    || value.short_code !== original.payload.short_code || !["APPROVED", "BOUND"].includes(value.status)) throw new Error("CLI_AUTH_RECEIPT_MISMATCH");
  return value;
}
export function validateCliRevocation(original: LocalWebPending, value: CliGrant): CliGrant {
  if (value.grant_id !== original.path.split("/")[1] || value.status !== "REVOKED" || value.idempotency_key !== original.operation_key) throw new Error("CLI_AUTH_RECEIPT_MISMATCH");
  return value;
}
