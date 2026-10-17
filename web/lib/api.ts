import type {
  BackgroundJob, Capabilities, Coverage, Evidence, ExecutionDetail, Finding, FindingTransition, JobCreate, Mission, MissionAttempt,
  MissionProposal, PlannerResult, PolicySnapshot, Project, ProjectCreate, Requirement, Risk, RunCreate,
  SourceSnapshot, TestCase, TestExecution, TestImplementation, TestRun, Verdict,
} from "@/lib/types";
import type { Locale } from "@/lib/i18n";

const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly detail: string) {
    super(detail || `Request failed: ${status}`);
    this.name = "ApiError";
  }
}

export function errorText(error: unknown, locale: Locale): string {
  const detail = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (locale === "en") return detail || "Something went wrong. Please try again.";
  if (error instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(detail)) {
    return "无法连接服务。请确认 SSH 隧道已连接，再重试。";
  }
  const known: Record<string, string> = {
    "project not found": "项目不存在，请返回项目列表刷新后重试。",
    "project key already exists": "项目标识已存在。请打开已有项目，或使用其他标识。",
    "idempotency key is already bound to a different run request": "此请求标识已用于另一组运行输入。请返回检查需求、源码和策略，再创建新的测试运行。",
    "Select a mission first.": "请先选择一个任务阶段。",
    "The saved requirements are unavailable or failed integrity verification.": "已保存的需求不可用，或未通过完整性校验。请重试；仍失败时检查服务端产物存储。",
    "The saved configuration is unavailable or failed integrity verification.": "已保存的配置不可用，或未通过完整性校验。请重试；仍失败时检查服务端产物存储。",
    "Unable to load evidence content": "无法读取证据内容，请重试并检查服务端产物存储。",
  };
  if (known[detail]) return known[detail];
  if (error instanceof ApiError) {
    const hint = error.status === 409 ? "请求与已有状态冲突。请刷新当前状态并检查输入后重试。"
      : error.status === 422 || error.status === 400 ? "输入未通过校验，请检查表单。"
      : error.status === 404 ? "未找到请求的数据，请刷新后重试。"
      : error.status >= 500 ? "服务暂时不可用。请确认 SSH 隧道和服务运行状态后重试。"
      : "请求未完成，请检查输入后重试。";
    return detail ? `${hint} 服务端详情：${detail}` : hint;
  }
  return detail ? `操作未完成：${detail}` : "操作未完成，请重试。";
}

async function responseError(response: Response, fallback?: string): Promise<ApiError> {
  const body = await response.text();
  let detail = fallback || "";
  try {
    const problem = JSON.parse(body) as { detail?: unknown };
    if (typeof problem.detail === "string") detail = problem.detail;
    else if (Array.isArray(problem.detail)) {
      detail = problem.detail.map((issue) => `${issue.loc?.slice(1).join(".") || "Input"}: ${issue.msg}`).join("; ");
    }
  } catch {
    // Proxy HTML is not a useful form error. Retain safe text diagnostics only.
    if (!response.headers.get("content-type")?.includes("text/html")) detail ||= body.slice(0, 2000);
  }
  return new ApiError(response.status, detail);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw await responseError(response);
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
export const retryMission = (missionId: string) => api<Mission>(`/missions/${missionId}/retry`, { method: "POST" });
export const cancelMission = (missionId: string) => api<Mission>(`/missions/${missionId}/cancel`, { method: "POST" });
export const getImplementations = (runId: string) => api<TestImplementation[]>(`/test-runs/${runId}/implementations`);
export const getExecutions = (runId: string) => api<TestExecution[]>(`/test-runs/${runId}/executions`);
export const getExecution = (executionId: string) => api<ExecutionDetail>(`/executions/${executionId}`);
export const getEvidence = (runId: string) => api<Evidence[]>(`/test-runs/${runId}/evidence`);
export const getEvidenceContent = async (evidenceId: string) => {
  const response = await fetch(`${API_PREFIX}/evidence/${evidenceId}/content`);
  if (!response.ok) throw await responseError(response, "Unable to load evidence content");
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
  if (!response.ok) throw await responseError(response, "The saved requirements are unavailable or failed integrity verification.");
  return response.text();
};
export const getConfigurationContent = async (snapshotId: string) => {
  const response = await fetch(`${API_PREFIX}/source-snapshots/${snapshotId}/configuration`);
  if (!response.ok) throw await responseError(response, "The saved configuration is unavailable or failed integrity verification.");
  return response.text();
};
export const getVerdicts = (runId: string) => api<Verdict[]>(`/test-runs/${runId}/verdicts`);
export const getJobs = (runId: string) => api<BackgroundJob[]>(`/test-runs/${runId}/jobs`);
export const getJob = (jobId: string) => api<BackgroundJob>(`/jobs/${jobId}`);
export const createJob = (runId: string, payload: JobCreate) =>
  api<BackgroundJob>(`/test-runs/${runId}/jobs`, { method: "POST", body: JSON.stringify(payload) });
export const cancelJob = (jobId: string) => api<BackgroundJob>(`/jobs/${jobId}/cancel`, { method: "POST" });
export const retryJob = (jobId: string, idempotencyKey: string) =>
  api<BackgroundJob>(`/jobs/${jobId}/retry`, { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey }) });
