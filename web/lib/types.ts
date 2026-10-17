export type Project = {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  repository_url?: string | null;
  default_branch: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type TestRun = {
  id: string;
  key: string;
  project_id: string;
  source_snapshot_id: string;
  policy_snapshot_id: string;
  trigger_type: string;
  trigger_ref?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type Mission = {
  id: string;
  key: string;
  test_run_id: string;
  mission_type: string;
  priority: string;
  objective: string;
  status: string;
  current_attempt_no: number;
  created_at: string;
  completed_at?: string | null;
};

export type InputRequest = {
  id: string;
  key: string;
  test_run_id: string;
  mission_id: string;
  attempt_id: string;
  agent_session_id: string;
  durable_job_id: string;
  question_id: string;
  question: string;
  options: string[];
  status: "PENDING" | "ANSWERED" | "CONSUMED" | "CANCELLED";
  answer: string | null;
  created_at: string;
  answered_at: string | null;
  consumed_at: string | null;
  cancelled_at: string | null;
  row_version: number;
};

export type InputAnswer = { answer: string; expected_row_version: number; idempotency_key: string };
export type InputAnswerResult = { input_request: InputRequest; job: BackgroundJob };

export type ProjectCreate = {
  key: string;
  name: string;
  description?: string;
  repository_url?: string;
  default_branch?: string;
};

export type RunCreate = {
  repository_url: string;
  commit_sha: string;
  branch?: string;
  prd_text: string;
  configuration_text: string;
  policy?: Record<string, unknown>;
  idempotency_key?: string;
};

export type SourceResolution = {
  repository_url: string;
  commit_sha: string;
  revision: string;
};

export type MissionAttempt = {
  id: string;
  mission_id: string;
  attempt_no: number;
  provider?: string | null;
  harness?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  result_payload?: Record<string, unknown> | null;
};

export type MissionProposal = {
  id: string;
  proposal_type: string;
  operation: string;
  status: string;
  object_payload: Record<string, unknown>;
  validation_errors?: Array<Record<string, unknown>> | null;
  accepted_entity_type?: string | null;
  accepted_entity_id?: string | null;
};

export type MissionExecution = {
  mission: Mission;
  attempt: MissionAttempt;
  proposals: MissionProposal[];
};

export type TestImplementation = {
  id: string;
  key: string;
  file_path: string;
  symbol: string;
  framework: string;
  language: string;
  commit_sha: string;
  validation_status: string;
  test_case_keys?: string[];
  testcase_keys?: string[];
  created_at: string;
};

export type ExecutionResult = {
  test_case_id: string;
  test_case_key?: string;
  result: string;
  duration_ms?: number | null;
  failure_summary?: string | null;
};

export type TestExecution = {
  id: string;
  key: string;
  test_run_id: string;
  purpose: string;
  runner_backend: string;
  source_commit: string;
  execution_spec_sha256: string;
  status: string;
  outcome: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  case_results?: ExecutionResult[];
};

export type ExecutionDetail = {
  execution: TestExecution;
  test_cases: ExecutionResult[];
  evidence_keys: string[];
};

export type Evidence = {
  id: string;
  key: string;
  execution_id?: string | null;
  evidence_type: string;
  trust_level: string;
  content_type?: string | null;
  sha256: string;
  size_bytes?: number | null;
  inline_summary?: string | null;
  collector: string;
  status: string;
  created_at: string;
  rejection_reason?: string | null;
};

export type Finding = {
  id: string;
  key: string;
  title: string;
  description: string;
  root_cause?: string | null;
  classification: string;
  severity: string;
  status: string;
  resolution?: string | null;
  confidence?: number | null;
  evidence_keys?: string[];
  test_case_keys?: string[];
  testcase_keys?: string[];
  created_at: string;
  row_version: number;
};

export type Verdict = {
  id: string;
  key: string;
  sequence_no: number;
  scope: string;
  decision: string;
  status: string;
  reason: string;
  policy_snapshot_id: string;
  state_snapshot_hash: string | null;
  evidence_manifest_sha256?: string | null;
  evidence_keys?: string[];
  finding_keys?: string[];
  created_at: string;
  finalized_at?: string | null;
};

export type ExecutionCreate = {
  workspace: string;
  backend: "docker" | "local";
  purpose: "OFFICIAL";
  idempotency_key?: string;
  timeout_seconds?: number;
};

export type Capabilities = {
  agent_providers: string[];
  runner_backends: Array<"docker" | "local">;
  workspace_root: string;
  runner_image: string;
  mode: string;
  worker?: { available: boolean; active_workers: number; last_seen_at: string | null };
};

export type FindingTransition = {
  status: string;
  resolution?: string;
  reason: string;
  expected_row_version: number;
};

export type SourceSnapshot = {
  id: string;
  repository_url: string;
  commit_sha: string;
  branch?: string | null;
  prd_sha256: string;
  configuration_sha256: string;
  source_fingerprint: string;
  created_at: string;
};

export type PolicySnapshot = {
  id: string;
  policy_name: string;
  policy_version: string;
  content_sha256: string;
  compiled_policy: Record<string, unknown>;
  created_at: string;
};

export type CycleResult = {
  reason: string;
  steps: Array<{ action: "mission" | "execution" | "verdict"; id: string; key: string; status: string }>;
  mission_id?: string | null;
  execution_id?: string | null;
  verdict_id?: string | null;
};

export type Requirement = {
  id: string;
  key: string;
  logical_key?: string | null;
  title: string;
  description: string;
  requirement_type: string;
  priority: string;
  source_type: string;
  source_ref?: string | null;
  confidence?: number | null;
  lifecycle_status: string;
};

export type Risk = {
  id: string;
  key: string;
  category: string;
  title: string;
  description: string;
  severity: string;
  probability: string;
  rationale?: string | null;
  confidence?: number | null;
  lifecycle_status: string;
  requirement_keys: string[];
};

export type PlannerResult = {
  reason: string;
  mission: Mission | null;
};

export type TestType =
  | "FUNCTIONAL"
  | "BOUNDARY"
  | "NEGATIVE"
  | "FAILURE"
  | "CONCURRENCY"
  | "CONSISTENCY"
  | "COMPATIBILITY"
  | "SECURITY"
  | "PERFORMANCE"
  | "RELIABILITY"
  | "UPGRADE"
  | "DATA"
  | "RECOVERY";

export type TestCase = {
  id: string;
  key: string;
  project_id: string;
  source_snapshot_id: string;
  title: string;
  description: string;
  test_type: TestType;
  priority: string;
  lifecycle_status: string;
  preconditions: string[];
  expected_result: string;
  case_fingerprint: string;
  confidence?: number | null;
  created_at: string;
  updated_at: string;
  row_version: number;
  risk_keys: string[];
};

export type RiskTestCoverage = {
  risk_id: string;
  risk_key: string;
  required_dimensions: TestType[];
  covered_dimensions: TestType[];
  missing_dimensions: TestType[];
  complete: boolean;
};

export type Coverage = {
  requirement_count: number;
  risk_count: number;
  test_case_count: number;
  risk_identification_coverage: number | null;
  risk_test_coverage: number | null;
  risks: RiskTestCoverage[];
  rule_version?: string;
  effective_policy_hash?: string;
};

export type JobOperation = "ADVANCE_RUN" | "EXECUTE_MISSION" | "EXECUTE_TESTS" | "EVALUATE_GATE" | "PREPARE_WORKSPACE";
export type JobStatus = "QUEUED" | "RUNNING" | "WAITING_INPUT" | "SUCCEEDED" | "FAILED" | "CANCEL_REQUESTED" | "CANCELLED" | "INTERRUPTED";

export type BackgroundJob = {
  id: string;
  key: string;
  test_run_id: string;
  mission_id?: string | null;
  job_type: JobOperation;
  status: JobStatus;
  idempotency_key: string;
  retry_of_job_id?: string | null;
  progress?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  heartbeat_at?: string | null;
  lease_expires_at?: string | null;
  updated_at?: string;
  cancel_requested_at?: string | null;
  attempts?: number;
  worker_id?: string | null;
};

export type JobCreate = {
  operation: JobOperation;
  mission_id?: string;
  idempotency_key: string;
  payload: Record<string, unknown>;
};
