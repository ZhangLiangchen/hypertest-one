import type { EnvironmentFormValues } from "./execution-environment";
import { environmentInputIssue } from "./execution-environment";
import type { PolicySnapshot, SourceSnapshot, TestRun } from "./types";

export type RunDraftReaders = {
  run: (id: string) => Promise<TestRun>;
  source: (id: string) => Promise<SourceSnapshot>;
  policy: (id: string) => Promise<PolicySnapshot>;
  prd: (id: string) => Promise<string>;
  configuration: (id: string) => Promise<string>;
};

export type CopiedRunDraft = {
  run: TestRun;
  source: SourceSnapshot;
  policy: PolicySnapshot;
  prd: string;
  configuration: string;
  environment: EnvironmentFormValues;
};

export class RunDraftError extends Error {
  constructor(public readonly code: "run" | "project" | "snapshot" | "environment") {
    super(`Unable to copy run inputs: ${code}`);
    this.name = "RunDraftError";
  }
}

// Copy requests, never frozen image IDs, old bindings, job inputs or request keys.
export async function loadRunDraft(projectId: string, runId: string, readers: RunDraftReaders): Promise<CopiedRunDraft> {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(runId)) throw new RunDraftError("run");
  const run = await readers.run(runId);
  if (run.id !== runId) throw new RunDraftError("run");
  if (run.project_id !== projectId) throw new RunDraftError("project");
  // The content endpoints perform server-side checksum verification. Apply none
  // of this draft if either immutable input is absent, corrupt or unreadable.
  const [source, policy, prd, configuration] = await Promise.all([
    readers.source(run.source_snapshot_id), readers.policy(run.policy_snapshot_id),
    readers.prd(run.source_snapshot_id), readers.configuration(run.source_snapshot_id),
  ]);
  if (source.id !== run.source_snapshot_id || policy.id !== run.policy_snapshot_id
    || !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(source.commit_sha)
    || !policy.compiled_policy || typeof policy.compiled_policy !== "object" || Array.isArray(policy.compiled_policy)) {
    throw new RunDraftError("snapshot");
  }
  const request = source.environment_definition?.request;
  const environment: EnvironmentFormValues = {
    environment_profile_id: request?.profile_id as EnvironmentFormValues["environment_profile_id"],
    service_app: request?.service?.app ?? "",
    service_health_path: request?.service?.health_path ?? (request?.profile_id === "python-pytest-v1" ? "/health" : ""),
    service_startup_timeout_seconds: request?.service?.startup_timeout_seconds ?? (request?.profile_id === "python-pytest-v1" ? 30 : NaN),
  };
  if (environmentInputIssue(environment)) throw new RunDraftError("environment");
  return { run, source, policy, prd, configuration, environment };
}
