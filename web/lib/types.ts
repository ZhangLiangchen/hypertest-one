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
