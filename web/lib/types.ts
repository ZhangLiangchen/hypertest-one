export type Project = {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  repository_url?: string | null;
  test_framework_repository_url?: string | null;
  default_branch: string;
  status: string;
  row_version: number;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type ReportedResult = "NOT_RUN" | "PASS" | "FAIL" | "ERROR" | "SKIPPED" | "UNKNOWN" | "BLOCKED";
export type ProjectUpdate = {
  expected_version: number;
  name?: string;
  description?: string | null;
  repository_url?: string | null;
  test_framework_repository_url?: string | null;
  default_branch?: string;
  status?: "ACTIVE" | "ARCHIVED";
};
export type ProjectCreate = {
  key: string;
  name: string;
  description?: string;
  repository_url?: string;
  test_framework_repository_url?: string;
  default_branch?: string;
};
