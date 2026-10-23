/** Cloud's typed browser client. Secrets and frozen payloads never enter storage. */
export const CLOUD_PROFILE = "cloud-harness-task/v1alpha1";
export const CLOUD_CANCEL_REASON = "OPERATOR_REQUESTED_CANCELLATION";
export type CloudResult = "NOT_RUN" | "PASS" | "FAIL" | "ERROR" | "SKIPPED" | "UNKNOWN" | "BLOCKED";
export type CloudRecord = Record<string, unknown>;
export type CloudSelector = { kind: "BRANCH" | "SHA" | "MR"; value: string; checkout_strategy: "HEAD" | "MERGE"; base_ref?: string };
export type CloudRepository = { url: string; default_selector: CloudSelector; credential_version_id?: string | null };
export type CloudConfiguration = {
  sut: CloudRepository; framework: CloudRepository;
  environment: { name: string; connection: "NONE" | "HTTPS" | "SSH"; host?: string | null; port?: number | null; user?: string | null; host_key?: string | null; network_requirements?: string; credential_version_id?: string | null; expected_deployment: string; require_matching_deployment: boolean;
    ssh_access?: CloudRecord | null; cloud_access_policy?: "LOCAL_ONLY" | "WEB_ONLY" | null };
};
export type CloudConfigRevision = { id: string; revision: number; configuration: CloudConfiguration };
export type CloudTask = { id: string; project_id: string; title: string; status: string; reported_result: CloudResult; version: number; latest_attempt_id?: string | null; config_id: string; inputs: CloudRecord; frozen_manifest?: CloudRecord | null; updated_at?: string };
export type CloudAttempt = { id: string; status: string; reported_result: CloudResult; attempt_no: number; reason?: string | null; checkpoint: CloudRecord; runtime_metadata: CloudRecord; lease_generation: number };
export type CloudRecoverySummary = {
  resume_supported: boolean; resume_reason?: string; old_owner_fenced: boolean;
  local_processes_stopped_observed: boolean; pending_operation_keys: string[];
  remote_operations_reconciled: boolean; can_reconcile: boolean; blocking_reasons: string[];
  reconciliation_source: string; budget_disposition: string;
  phase: "ACTIVE" | "CANCELLATION_REQUESTED" | "STOP_UNCONFIRMED" | "RECONCILIATION_REQUIRED" | "TERMINATED";
};
export type CloudLiveSummary = CloudTask & { current_attempt: CloudAttempt | null; resolutions: CloudRecord[]; observed_at: string; recovery?: CloudRecoverySummary };
export type CloudAsset = { id: string; attempt_id: string; kind: string; key: string; title: string; revision: number; task_version: number; markdown: string; details: CloudRecord; reported_result: CloudResult; artifact_id?: string | null };
export type CloudDocument = { task: CloudTask; attempts: CloudAttempt[]; resolutions: CloudRecord[]; assets: CloudAsset[]; artifacts: CloudRecord[]; runs: CloudRecord[]; run_cases: CloudRecord[]; delegations: CloudRecord[]; questions: CloudRecord[]; answers: CloudRecord[] };
export type CloudReceipt = { status: string; profile: string; project_id: string; operation_key: string; operation: string; version: number; task_id?: string; attempt_id?: string; config_id?: string; resolution_id?: string; credential_id?: string; credential_version_id?: string };
export type CloudMutation = { profile: string; project_id: string; operation_key: string; expected_version: number; operation: string; [key: string]: unknown };
export type CloudPending = { project_id: string; operation_key: string; expected_version: number; operation: string; task_id?: string; attempt_id?: string; digest: string; state: "SENT" | "UNKNOWN" };
export type CloudCapabilities = { enabled?: boolean; worker_enabled?: boolean;
  supported?: { codex_delegation?: boolean; claude_code_delegation?: boolean; ssh_fixed_diagnostics?: boolean; ssh_profile?: string; resume_attempt?: boolean; reconcile_attempt?: boolean };
  recovery?: { resume_supported?: boolean; resume_reason?: string; reconcile_supported?: boolean; reconciliation_source?: string; independent_stop_proof?: boolean; budget_disposition?: string };
  configuration?: { codex_enabled?: boolean; ssh_fixed_diagnostics_enabled?: boolean };
  admission?: { state?: string; scope?: string }; [key: string]: unknown };
export type CloudCredential = { id: string; label: string; kind: string; purpose: string; allowed_targets: string[]; allowed_actions: string[]; version: number; status: string };
export type CloudCredentialVersion = { id: string; credential_id: string; version: number; expires_at?: string | null };

export class CloudApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly code?: string) { super(message); this.name = "CloudApiError"; }
}

export function cloudSubmissionIssue(error: CloudApiError): string {
  if (error.status !== 409) return "REQUEST_REJECTED";
  if (error.code === "OPERATION_KEY_CONFLICT" || error.message === "Cloud operation key conflicts with its original actor or request") return "OPERATION_KEY_CONFLICT";
  if (error.code === "VERSION_CONFLICT" || ["Cloud Task version is stale", "Cloud configuration version is stale", "Credential version is stale"].includes(error.message)) return "VERSION_CONFLICT";
  return error.code === "SDK_RESUME_UNSUPPORTED" ? "SDK_RESUME_UNSUPPORTED" : "REQUEST_PRECONDITION_REQUIRED";
}

export async function cloudRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/cloud/${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    let detail = "Cloud request failed";
    let code: string | undefined;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      if (["VERSION_CONFLICT", "SDK_RESUME_UNSUPPORTED", "REQUEST_PRECONDITION_REQUIRED", "OPERATION_KEY_CONFLICT"].includes(body.code)) code = body.code;
    } catch { /* Never echo proxy HTML. */ }
    throw new CloudApiError(response.status, detail, code);
  }
  return response.json() as Promise<T>;
}

export const cloudSetup = () => cloudRequest<{ configured: boolean }>("setup");
export const cloudCapabilities = () => cloudRequest<CloudCapabilities>("capabilities");
export const cloudConfiguration = (projectId: string) => cloudRequest<{ items: CloudConfigRevision[] }>(`projects/${encodeURIComponent(projectId)}/configuration`);
export const cloudCredentials = (projectId: string) => cloudRequest<{ credentials: CloudCredential[]; versions: CloudCredentialVersion[] }>(`projects/${encodeURIComponent(projectId)}/credentials`);
export const cloudTasks = (projectId: string, offset = 0) => cloudRequest<{ items: CloudTask[]; total: number }>(`projects/${encodeURIComponent(projectId)}/tasks?offset=${offset}&limit=20`);
export const cloudSummary = (projectId: string, taskId: string) => cloudRequest<CloudLiveSummary>(`tasks/${encodeURIComponent(taskId)}/summary?project_id=${encodeURIComponent(projectId)}`);
export const cloudDocument = (projectId: string, taskId: string, version?: number) => cloudRequest<CloudDocument>(`tasks/${encodeURIComponent(taskId)}?project_id=${encodeURIComponent(projectId)}&readback=complete${version === undefined ? "" : `&version=${version}`}`);
export const cloudOperation = (projectId: string, key: string) => cloudRequest<CloudReceipt>(`projects/${encodeURIComponent(projectId)}/operations/${encodeURIComponent(key)}`);
export const cloudDirectory = (projectId: string, mode = "", offset = 0) => cloudRequest<{ items: CloudRecord[]; total: number }>(`projects/${encodeURIComponent(projectId)}/task-directory?offset=${offset}&limit=20${mode ? `&product_mode=${mode}` : ""}`);

export function cloudReceiptMatches(pending: CloudPending, receipt: CloudReceipt): boolean {
  return receipt.status === "ACCEPTED" && receipt.profile === CLOUD_PROFILE && receipt.project_id === pending.project_id
    && receipt.operation_key === pending.operation_key && receipt.operation === pending.operation
    && Number.isSafeInteger(receipt.version) && receipt.version === pending.expected_version + 1
    && (!pending.task_id || receipt.task_id === pending.task_id)
    && (!pending.attempt_id || receipt.attempt_id === pending.attempt_id);
}

export function canReleaseCloudPending(status: number, acknowledged: boolean, issue?: string): boolean {
  // Timeouts and proxy/rate-limit failures are not proof that a write was rejected.
  // A denied readback after ACK also cannot release the original operation.
  return !acknowledged && issue !== "OPERATION_KEY_CONFLICT" && [400, 401, 403, 404, 405, 409, 413, 415, 422].includes(status);
}

export function cloudCredentialReceiptVisible(receipt: CloudReceipt, records: { credentials: CloudCredential[]; versions: CloudCredentialVersion[] }): boolean {
  const parent = records.credentials.find((row) => row.id === receipt.credential_id);
  if (!parent) return false;
  if (receipt.operation === "REVOKE_CREDENTIAL") return parent.status === "REVOKED" && parent.version === receipt.version;
  return parent.version >= receipt.version && !!receipt.credential_version_id && records.versions.some((row) =>
    row.id === receipt.credential_version_id && row.credential_id === receipt.credential_id && row.version === receipt.version);
}

/** Operational observations are separate from the immutable accepted document. */
export function cloudOperationalView(document: CloudDocument, live?: CloudLiveSummary) {
  const task = document.task;
  const valid = !!live && live.id === task.id && live.project_id === task.project_id && live.version === task.version
    && live.latest_attempt_id === task.latest_attempt_id && typeof live.status === "string"
    && (!live.latest_attempt_id ? live.current_attempt === null : live.current_attempt?.id === live.latest_attempt_id)
    && Array.isArray(live.resolutions) && typeof live.observed_at === "string";
  return { valid, status: valid ? live!.status : null, attempt: valid ? live!.current_attempt : null,
    resolutions: valid ? live!.resolutions : [], newerVersion: !!live && live.id === task.id && live.project_id === task.project_id && live.version > task.version };
}

/** Fixed control input also permits the fail-closed API's emergency fence path. */
export function cloudCancellation(attemptId?: string): CloudRecord {
  return { operation: attemptId ? "CANCEL_ATTEMPT" : "CANCEL_TASK", ...(attemptId ? { attempt_id: attemptId } : {}), reason: CLOUD_CANCEL_REASON };
}

export function cloudProgressTone(status: string): "blue" | "gold" | "red" | undefined {
  return ["RUNNING", "PREPARING", "QUEUED"].includes(status) ? "blue"
    : ["WAITING_INPUT", "RECOVERY_REQUIRED"].includes(status) ? "gold" : status === "FAILED" ? "red" : undefined;
}

export function credentialFreeUrl(value: string): boolean {
  try { const url = new URL(value); return ["https:", "ssh:"].includes(url.protocol) && !!url.hostname && !url.password && !url.search && !url.hash && (!url.username || (url.protocol === "ssh:" && url.username === "git")); }
  catch { return false; }
}

export function cloudSelector(kind: CloudSelector["kind"], value: string, strategy: CloudSelector["checkout_strategy"] = "HEAD", baseRef?: string): CloudSelector {
  const clean = value.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_./:-]*$/.test(clean) || clean.includes("..") || clean.includes("@{") || (kind === "SHA" && !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(clean))) throw new Error("INVALID_SELECTOR");
  if (kind === "MR" && (!/^\d+$/.test(clean) || Number(clean) < 1 || !baseRef?.trim())) throw new Error("MR_BASE_REQUIRED");
  if (kind === "MR" && (!/^[A-Za-z0-9][A-Za-z0-9_./-]*$/.test(baseRef!.trim()) || baseRef!.includes("..") || baseRef!.trim().endsWith(".lock"))) throw new Error("INVALID_MR_BASE");
  return { kind, value: clean, checkout_strategy: strategy, ...(kind === "MR" ? { base_ref: baseRef!.trim() } : {}) };
}

export function cloudStorageKey(projectId: string): string { return `hypertest:cloud:pending:${projectId}`; }

export function parseCloudPending(raw: string | null, projectId: string): CloudPending | null {
  if (!raw) return null;
  const value = JSON.parse(raw) as CloudPending;
  if (value.project_id !== projectId || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value.operation_key)
    || !Number.isSafeInteger(value.expected_version) || value.expected_version < 0 || typeof value.operation !== "string"
    || (value.task_id !== undefined && (typeof value.task_id !== "string" || !value.task_id || value.task_id.length > 128))
    || (value.attempt_id !== undefined && (typeof value.attempt_id !== "string" || !value.attempt_id || value.attempt_id.length > 128))
    || !["SENT", "UNKNOWN"].includes(value.state) || !/^[a-f0-9]{64}$/.test(value.digest)) throw new Error("PENDING_RECORD_INVALID");
  return { project_id: value.project_id, operation_key: value.operation_key, expected_version: value.expected_version,
    operation: value.operation, digest: value.digest, state: value.state, ...(value.task_id ? { task_id: value.task_id } : {}), ...(value.attempt_id ? { attempt_id: value.attempt_id } : {}) };
}

/** Browser-safe SHA-256 for an HTTP deployment where Web Crypto may be unavailable. */
export function cloudInputIdentity(input: CloudRecord): string {
  const bytes = new TextEncoder().encode(JSON.stringify(input));
  const padded = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
  padded.set(bytes); padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, Math.floor(bytes.length / 0x20000000));
  view.setUint32(padded.length - 4, (bytes.length * 8) >>> 0);
  const constants = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const state = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const rotate = (value: number, count: number) => (value >>> count) | (value << (32 - count));
  for (let offset = 0; offset < padded.length; offset += 64) {
    const words = new Int32Array(64);
    for (let i = 0; i < 16; i++) words[i] = view.getInt32(offset + i * 4);
    for (let i = 16; i < 64; i++) {
      const x = words[i - 15], y = words[i - 2];
      words[i] = (words[i - 16] + (rotate(x, 7) ^ rotate(x, 18) ^ (x >>> 3)) + words[i - 7] + (rotate(y, 17) ^ rotate(y, 19) ^ (y >>> 10))) | 0;
    }
    let [a,b,c,d,e,f,g,h] = state;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) + ((e & f) ^ (~e & g)) + constants[i] + words[i]) | 0;
      const t2 = ((rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      h=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0;
    }
    [a,b,c,d,e,f,g,h].forEach((value, i) => { state[i] = (state[i] + value) | 0; });
  }
  return state.map((word) => (word >>> 0).toString(16).padStart(8, "0")).join("");
}
