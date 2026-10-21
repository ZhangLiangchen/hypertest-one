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

export type SessionTaskStatus = "DRAFT" | "IN_PROGRESS" | "BLOCKED" | "COMPLETED" | "CANCELLED";
export type ReportedResult = "NOT_RUN" | "PASS" | "FAIL" | "ERROR" | "SKIPPED" | "UNKNOWN" | "BLOCKED";
export type SessionTask = {
  id: string;
  project_id: string;
  provider: string;
  session_id: string;
  title: string;
  objective: string;
  plan_markdown: string;
  status: SessionTaskStatus;
  reported_result: ReportedResult;
  version: number;
  source: string;
  created_at: string;
  last_synced_at: string;
};
export type SessionCaseRevision = {
  id: string;
  task_id: string;
  key: string;
  title: string;
  steps: string[];
  expected: string;
  actual: string;
  reported_result: ReportedResult;
  implementation_ref?: string | null;
  revision: number;
  task_version: number;
  source: string;
  created_at: string;
};
export type SessionReportRevision = {
  id: string;
  task_id: string;
  key: string;
  title: string;
  markdown: string;
  artifact_uri?: string | null;
  source_ref?: string | null;
  reported_result: ReportedResult;
  revision: number;
  task_version: number;
  source: string;
  created_at: string;
};
export type SessionSyncReceipt = {
  id: string;
  task_id: string;
  task_version: number;
  idempotency_key: string;
  actor_ref: string;
  created_at: string;
  task_snapshot: SessionTask;
};
export type SessionTaskDetail = {
  task: SessionTask;
  cases: SessionCaseRevision[];
  reports: SessionReportRevision[];
  case_history: SessionCaseRevision[];
  report_history: SessionReportRevision[];
  sync_history: SessionSyncReceipt[];
};
export type SessionTaskList = { items: SessionTask[]; total: number; limit: number; offset: number };

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
  scope?: "mission" | "run";
  mission_id: string | null;
  attempt_id: string | null;
  binding_id?: string | null;
  context_mission_id?: string | null;
  context_attempt_id?: string | null;
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
  harness_mode?: "SERVER_HOST" | "LOCAL_CONNECTOR";
  harness_node_id?: string;
  source_bundle_transfer_id?: string;
  repository_url: string;
  commit_sha: string;
  branch?: string;
  prd_text: string;
  configuration_text: string;
  policy?: Record<string, unknown>;
  idempotency_key?: string;
  environment?: EnvironmentRequest;
};

export type EnvironmentProfileId = "python-pytest-v1" | "python-api-v1" | "python-api-v2";
export type ServiceRequest = { app: string; health_path: string; startup_timeout_seconds: number };
export type EnvironmentRequest = { profile_id: EnvironmentProfileId; service?: ServiceRequest };
export type ExecutionEnvironmentProfile = {
  profile_id: EnvironmentProfileId;
  kind: "pytest" | "asgi";
  dependencies: Record<string, string>;
  dependency_lock_sha256: string;
  launcher_sha256: string;
  network: "none";
  available: boolean;
  reason_code?: string;
  checked_at: string;
};
export type EnvironmentCatalog = { profiles: ExecutionEnvironmentProfile[] };
export type EnvironmentDefinition = {
  schema_version: "hypertest.environment/v1";
  request: EnvironmentRequest;
  image_id: string;
  image_os: string;
  image_architecture: string;
  dependency_lock_sha256: string;
  dependencies: Record<string, string>;
  launcher_sha256: string;
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
  project_id?: string;
  source_snapshot_id?: string;
  repository_url?: string;
  file_path: string;
  symbol: string;
  framework: string;
  language: string;
  commit_sha: string;
  validation_status: string;
  artifact_uri?: string | null;
  source_sha256?: string | null;
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
  environment_id?: string | null;
  environment_fingerprint?: string | null;
  spec?: Record<string, unknown> | null;
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

export type FindingHistoryState = { status: string | null; resolution: string | null; row_version: number | null };
export type FindingHistoryEvent = {
  id: string;
  created_at: string;
  actor_type: string;
  action: string;
  before: FindingHistoryState | null;
  after: FindingHistoryState | null;
  reason: string | null;
  reason_truncated: boolean;
};
export type FindingHistory = { events: FindingHistoryEvent[]; truncated: boolean };

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
  execution_profile?: "run-persistent-harness/v1" | null;
  harness_bridge?: string;
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
  environment_definition?: EnvironmentDefinition | null;
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
  project_id: string;
  test_run_id: string;
  mission_id?: string | null;
  job_type: JobOperation;
  status: JobStatus;
  idempotency_key: string;
  retry_of_job_id?: string | null;
  payload?: Record<string, unknown>;
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

export type ActivityKind = "SIGNAL_RECEIVED" | "TURN_STARTED" | "TURN_COMPLETED" | "MODEL_ACTIVITY" | "TOOL_STARTED" | "TOOL_COMPLETED" | "FILE_ACTIVITY" | "MISSION_STARTED" | "RESUMED" | "RESULT_SUBMITTED" | "MISSION_FINISHED" | "ERROR";
export type ActivitySource = "PROVIDER" | "CONTROL_PLANE";
export type ActivityPhase = "QUEUED" | "WAITING_INPUT" | "CANCEL_REQUESTED" | "AGENT_RUNNING" | "RESULT_VALIDATION" | "PLATFORM_WORK" | "TERMINAL";
export type JobActivityItem = {
  id: string;
  kind: ActivityKind;
  source: ActivitySource;
  recorded_at: string;
  last_observed_at: string;
  count: number;
  mission_id: string;
  attempt_id: string;
  agent_session_id: string | null;
};
export type JobActivity = {
  job_id: string;
  server_time: string;
  summary: {
    phase: ActivityPhase;
    current_attempt: {
      mission_id: string;
      mission_key: string;
      mission_type: string;
      attempt_id: string;
      attempt_no: number;
      agent_session_id: string | null;
    } | null;
    turn_started_at: string | null;
    last_provider_signal_at: string | null;
    provider_signal_age_seconds: number | null;
    worker_heartbeat_at: string | null;
    worker_heartbeat_age_seconds: number | null;
  };
  items: JobActivityItem[];
  next_cursor: string | null;
  retention_per_attempt: number;
  window_seconds: number;
  truncated: boolean;
};

export type RunBinding = {
  id: string;
  test_run_id: string;
  logical_worker_id: string;
  primary_agent_session_id: string;
  binding_epoch: number;
  status: "RESERVED" | "ACTIVE" | "WAITING_INPUT" | "RECOVERY_REQUIRED" | "CLOSED" | "FAILED" | "CANCELLED";
  created_at: string;
  updated_at: string;
  row_version: number;
};
export type RunReport = {
  id: string;
  test_run_id: string;
  binding_id: string;
  durable_job_id: string;
  content_sha256: string;
  verdict_key?: string | null;
  verdict_decision?: string | null;
  created_at: string;
};
export type GitLabIssueOperation = {
  id: string;
  finding_id: string;
  status: "PENDING" | "UNKNOWN" | "SUCCEEDED" | "REJECTED";
  issue_iid: number | null;
  issue_url: string | null;
  created_at: string;
  updated_at: string;
};
export type RunHarness = {
  selection?: { mode: "LOCAL_CONNECTOR"; node_id: string; display_name: string | null; online: boolean } | null;
  binding: RunBinding | null;
  state: { max_steps: number; timeout_seconds: number; harness_budget_seconds: number; active_mission_id: string | null; active_attempt_id: string | null } | null;
  reports: RunReport[];
  issues: GitLabIssueOperation[];
};
