import type {
  BackgroundJob, Capabilities, Coverage, Evidence, ExecutionDetail, Finding, FindingTransition, JobCreate, Mission, MissionAttempt,
  MissionProposal, PlannerResult, PolicySnapshot, Project, ProjectCreate, Requirement, Risk, RunCreate,
  SourceResolution, SourceSnapshot, TestCase, TestExecution, TestImplementation, TestRun, Verdict, InputRequest, InputAnswer, InputAnswerResult,
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
  if (detail.includes("repository origin must not contain embedded credentials")) {
    return "仓库源地址不能包含 token、用户名密码等内嵌凭据。请使用不含凭据的 origin 地址，并在 Worker 主机配置 Git 访问授权。";
  }
  if (detail.includes("repository origin is not a valid credential-free Git address")) {
    return "仓库源地址格式无效。请检查 origin 地址，并在 Worker 主机配置 Git 访问授权。";
  }
  const known: Record<string, string> = {
    "project not found": "项目不存在，请返回项目列表刷新后重试。",
    "project key already exists": "项目标识已存在。请打开已有项目，或使用其他标识。",
    "cannot resolve repository revision; verify the branch/tag, configured Git access and network availability": "无法解析仓库版本。请检查分支或标签是否存在，以及主机上的 Git 访问授权和网络。",
    "revision is missing or ambiguous; use an explicit refs/heads/branch or refs/tags/tag": "版本不存在或分支、标签同名。请明确填写 refs/heads/分支 或 refs/tags/标签。",
    "choose a valid branch or tag, or enter a full commit SHA": "请填写有效的分支、标签或完整提交 SHA。",
    "Git is unavailable on the HyperTest host": "HyperTest 主机上未检测到 Git，请先完成运行环境配置。",
    "idempotency key is already bound to a different run request": "此请求标识已用于另一组运行输入。请返回检查需求、源码和策略，再创建新的测试运行。",
    "Select a mission first.": "请先选择一个任务阶段。",
    "The saved requirements are unavailable or failed integrity verification.": "已保存的需求不可用，或未通过完整性校验。请重试；仍失败时检查服务端产物存储。",
    "The saved configuration is unavailable or failed integrity verification.": "已保存的配置不可用，或未通过完整性校验。请重试；仍失败时检查服务端产物存储。",
    "Unable to load evidence content": "无法读取证据内容，请重试并检查服务端产物存储。",
    "input request not found": "未找到此问题。请刷新“问题与回答”，核对当前任务。",
    "this question already has an immutable answer": "此问题已有不可修改的回答。请刷新查看已保存回答及原后台任务，未提交的草稿会保留。",
    "question is no longer awaiting this answer; refresh its current state": "此问题的状态已变化。请刷新问题与后台任务，再决定下一步；不要创建新周期来绕过问题。",
    "answer must contain 1–12000 characters and no NUL": "请输入 1–12,000 个字符的非空白回答，并移除 NUL 空字符。",
    "test run has active background work; use its task controls": "此运行已有后台任务。请使用该任务的回答或取消入口，等待期间不能新建周期。",
    "test run already has active work; wait or cancel the active job": "此运行已有任务。请等待、回答待答问题，或在后台任务详情中取消。",
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
export const resolveSource = (payload: { repository_url: string; revision: string }) =>
  api<SourceResolution>("/sources/resolve", { method: "POST", body: JSON.stringify(payload) });
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
export const getInputRequests = (runId: string) => api<InputRequest[]>(`/test-runs/${runId}/input-requests`);
export const getInputRequest = (requestId: string) => api<InputRequest>(`/input-requests/${requestId}`);
export const answerInputRequest = (requestId: string, payload: InputAnswer) =>
  api<InputAnswerResult>(`/input-requests/${requestId}/answer`, { method: "POST", body: JSON.stringify(payload) });
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
