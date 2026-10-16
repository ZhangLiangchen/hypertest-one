import type {
  Capabilities, Coverage, CycleResult, Evidence, ExecutionCreate, ExecutionDetail, Finding, FindingTransition, Mission, MissionAttempt, MissionExecution,
  MissionProposal, PlannerResult, PolicySnapshot, Project, ProjectCreate, Requirement, Risk, RunCreate,
  SourceSnapshot, TestCase, TestExecution, TestImplementation, TestRun, Verdict,
} from "@/lib/types";

const API_PREFIX = "/api/v1";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try {
      const problem = JSON.parse(body) as { detail?: unknown };
      if (typeof problem.detail === "string") detail = problem.detail;
      else if (Array.isArray(problem.detail)) {
        detail = problem.detail.map((issue) => `${issue.loc?.slice(1).join(".") || "Input"}: ${issue.msg}`).join("; ");
      }
    } catch {
      // Non-JSON responses still retain the server's diagnostic message.
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const getProjects = () => api<Project[]>("/projects");
export const createProject = (payload: ProjectCreate) =>
  api<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
export const createRun = (projectId: string, payload: RunCreate) =>
  api<TestRun>(`/projects/${projectId}/runs/bootstrap`, { method: "POST", body: JSON.stringify(payload) });
export const getProject = (projectId: string) => api<Project>(`/projects/${projectId}`);
export const getProjectRuns = (projectId: string) =>
  api<TestRun[]>(`/projects/${projectId}/test-runs`);
export const getRun = (runId: string) => api<TestRun>(`/test-runs/${runId}`);
export const getRequirements = (runId: string) =>
  api<Requirement[]>(`/test-runs/${runId}/requirements`);
export const getRisks = (runId: string) => api<Risk[]>(`/test-runs/${runId}/risks`);
export const getTestCases = (runId: string) => api<TestCase[]>(`/test-runs/${runId}/test-cases`);
export const getCoverage = (runId: string) => api<Coverage>(`/test-runs/${runId}/coverage`);
export const getMissions = (runId: string) => api<Mission[]>(`/test-runs/${runId}/missions`);
export const getMission = (missionId: string) => api<Mission>(`/missions/${missionId}`);
export const planNext = (runId: string) =>
  api<PlannerResult>(`/test-runs/${runId}/plan-next`, { method: "POST" });
export const getMissionAttempts = (missionId: string) => api<MissionAttempt[]>(`/missions/${missionId}/attempts`);
export const getMissionProposals = (missionId: string) => api<MissionProposal[]>(`/missions/${missionId}/proposals`);
export const executeMission = (missionId: string, payload: { workspace: string; provider: string }) =>
  api<MissionExecution>(`/missions/${missionId}/execute`, { method: "POST", body: JSON.stringify(payload) });
export const retryMission = (missionId: string) => api<Mission>(`/missions/${missionId}/retry`, { method: "POST" });
export const cancelMission = (missionId: string) => api<Mission>(`/missions/${missionId}/cancel`, { method: "POST" });
export const getImplementations = (runId: string) => api<TestImplementation[]>(`/test-runs/${runId}/implementations`);
export const getExecutions = (runId: string) => api<TestExecution[]>(`/test-runs/${runId}/executions`);
export const getExecution = (executionId: string) => api<ExecutionDetail>(`/executions/${executionId}`);
export const createExecution = (runId: string, payload: ExecutionCreate) =>
  api<TestExecution>(`/test-runs/${runId}/executions`, { method: "POST", body: JSON.stringify(payload) });
export const getEvidence = (runId: string) => api<Evidence[]>(`/test-runs/${runId}/evidence`);
export const getEvidenceContent = async (evidenceId: string) => {
  const response = await fetch(`${API_PREFIX}/evidence/${evidenceId}/content`);
  if (!response.ok) throw new Error((await response.text()) || "Unable to load evidence content");
  return response.text();
};
export const getFindings = (runId: string) => api<Finding[]>(`/test-runs/${runId}/findings`);
export const transitionFinding = (findingId: string, payload: FindingTransition) =>
  api<Finding>(`/findings/${findingId}/transition`, { method: "POST", body: JSON.stringify(payload) });
export const getCapabilities = () => api<Capabilities>("/capabilities");
export const getSourceSnapshot = (snapshotId: string) => api<SourceSnapshot>(`/source-snapshots/${snapshotId}`);
export const getPolicySnapshot = (snapshotId: string) => api<PolicySnapshot>(`/policy-snapshots/${snapshotId}`);
export const getPrdContent = async (snapshotId: string) => {
  const response = await fetch(`${API_PREFIX}/source-snapshots/${snapshotId}/prd`);
  if (!response.ok) throw new Error("The saved requirements are unavailable or failed integrity verification.");
  return response.text();
};
export const getConfigurationContent = async (snapshotId: string) => {
  const response = await fetch(`${API_PREFIX}/source-snapshots/${snapshotId}/configuration`);
  if (!response.ok) throw new Error("The saved configuration is unavailable or failed integrity verification.");
  return response.text();
};
export const getVerdicts = (runId: string) => api<Verdict[]>(`/test-runs/${runId}/verdicts`);
export const evaluateGate = (runId: string) =>
  api<Verdict>(`/test-runs/${runId}/evaluate`, { method: "POST", body: JSON.stringify({ finalize: true }) });
export const advanceRun = (runId: string, payload: { workspace: string; backend: "docker" | "local"; timeout_seconds?: number; max_steps: number }) =>
  api<CycleResult>(`/test-runs/${runId}/advance`, { method: "POST", body: JSON.stringify(payload) });
export const prepareWorkspace = (runId: string) =>
  api<{ workspace: string; repository_url: string; commit_sha: string }>(`/test-runs/${runId}/prepare-workspace`, { method: "POST" });
