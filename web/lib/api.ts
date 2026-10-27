import type {
  RunHarness, RunBinding, RunReport, BackgroundJob, Capabilities, Coverage, Evidence, ExecutionDetail, Finding, FindingHistory, FindingTransition, JobActivity, JobCreate, Mission, MissionAttempt,
  MissionProposal, PlannerResult, PolicySnapshot, Project, ProjectCreate, Requirement, Risk, RunCreate, EnvironmentCatalog,
  SourceResolution, SourceSnapshot, TestCase, TestExecution, TestImplementation, TestRun, Verdict, InputRequest, InputAnswer, InputAnswerResult,
  SessionTaskDetail, SessionTaskList, SessionReportRevision, ProjectUpdate, SessionTaskUpdate, LocalTaskActorList, LocalTaskCreate, TaskBindingAuthorization,
} from "@/lib/types";
import type { Locale } from "@/lib/i18n";
import type { CollaborationDocument, CollaborationReceipt, CollaborationRequest } from "@/lib/local-collaboration";

const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly detail: string, public readonly existingTaskId?: string) {
    super(detail || `Request failed: ${status}`);
    this.name = "ApiError";
  }
}

export function errorText(error: unknown, locale: Locale): string {
  const detail = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const archiveProblems: Record<string, [string, string]> = {
    ARCHIVE_WEB_UNAVAILABLE: ["CLI authorization and archive management are not configured on this server.", "此服务器尚未配置 CLI 授权与归档管理入口。"],
    ARCHIVE_TASK_VERSION_CONFLICT: ["The task changed. Your draft is retained; refresh and reopen this action to review its latest version.", "任务版本已变化。草稿已保留，请刷新并重新打开操作，核对最新版本。"],
    ARCHIVE_ROOT_VERSION_CONFLICT: ["New root artifacts arrived. Review the latest versions before publishing a new summary.", "任务根空间已有新产物，请核对最新版本后重新发布汇总。"],
    ARCHIVE_SUBTASK_VERSION_CONFLICT: ["A subtask archive changed. Review the latest versions before publishing.", "子任务归档版本已变化，请核对最新版本后再发布。"],
    ARCHIVE_OPERATION_KEY_CONFLICT: ["The original key belongs to different input. Query it without resubmitting.", "原请求标识对应不同输入，请查询原请求，不要重发。"],
    ARCHIVE_ORIGINAL_KEY_REQUIRED: ["The result is uncertain. Query the original request; do not submit it again.", "操作结果未决，请查询原请求，不要再次提交。"],
    ARCHIVE_READBACK_UNAVAILABLE: ["The complete fixed snapshot could not be verified. Retry the read; previously loaded records are preserved.", "未能核对完整固定快照。请重试读取，已加载记录保留。"],
    ARCHIVE_ACCEPTED_OWNER_IMMUTABLE: ["The uploader cannot change after an accepted archive. Keep the original ownership.", "已有归档提交后不可更改上传所有者，请保留原归属。"],
    ARCHIVE_UPLOADER_UNAVAILABLE: ["The uploader has no valid archive grant for this project. Authorize the CLI first.", "上传身份没有此项目的有效归档授权，请先完成 CLI 授权。"],
    ARCHIVE_SUBTASK_OWNER_MISMATCH: ["A subtask can only authorize its task's uploader.", "子任务只能授权给任务所属的上传身份。"],
    ARCHIVE_RECEIPT_MISMATCH: ["The receipt does not match the frozen request. Query the original request without resubmitting.", "回执与固定请求不一致，请查询原请求，不要重发。"],
    ARCHIVE_REQUEST_REJECTED: ["The request was rejected. Check its fields, target and authorization.", "请求被拒绝，请核对字段、目标与授权。"],
    CLI_AUTH_RECEIPT_MISMATCH: ["The authorization receipt does not match the approved request. Query its original key.", "授权回执与批准请求不一致，请查询原 key。"],
    CLI_PAIRING_NOT_PENDING_OR_EXPIRED: ["This pairing request has expired or is no longer pending. Refresh its state.", "配对请求已过期或已不处于待批准状态，请刷新查看。"],
    CLI_UPLOADER_NOT_ACTIVE: ["This uploader identity is inactive. Select an existing active identity.", "此上传身份未启用，请选择已有的有效身份。"],
    CLI_AUTHORIZATION_KEY_CONFLICT: ["The original authorization key conflicts. Query it without issuing another grant.", "原授权 key 冲突，请查询原请求，不要重新签发授权。"],
  };
  if (archiveProblems[detail]) return archiveProblems[detail][locale === "en" ? 0 : 1];
  if (locale === "en") {
    const bindingProblems: Record<string, string> = {
      TASK_VERSION_CONFLICT: "The task version changed. Refresh, then reopen this operation to review the latest version; your input is preserved.",
      TASK_ALREADY_BOUND: "This task is already bound. Refresh to inspect its existing session.",
      TASK_BINDING_REQUIRED: "Bind the intended Task ID before syncing work.",
      TASK_BINDING_ACTOR_REQUIRED: "Authorize a Local client on the task page before binding.",
      TASK_BINDING_ACTOR_MISMATCH: "This client is not authorized to bind the selected task.",
      TASK_BINDING_ACTOR_UNAVAILABLE: "The selected client has no active sync authorization for this Project. Refresh the client list or arrange its authorization first.",
      SESSION_ALREADY_HAS_TASK: "This session already has a task. Reuse that task instead of claiming another one.",
      TASK_ID_REQUIRED: "Specify the bound Task ID before syncing.",
      TASK_ID_MISMATCH: "The Task ID does not match this session's binding.",
      TASK_BINDING_DELETED: "Restore the task and its Project before binding.",
      TASK_OPERATION_KEY_CONFLICT: "This request key belongs to different input. Query the original key before continuing.",
      TASK_CREATION_RECEIPT_NOT_FOUND: "The original creation receipt was not found. Continue querying the original key; this does not permit another POST.",
      LOCAL_TASK_CREATION_RECEIPT_MISMATCH: "The creation receipt did not match the frozen request. Query the original key instead of creating another task.",
      COLLABORATION_KEY_CONFLICT: "The original key belongs to different input. Keep the pending request and query its original key.",
      COLLABORATION_RECEIPT_NOT_FOUND_NO_REPLAY: "No receipt was found for the original key. Keep querying that key; this does not permit another submission.",
      COLLABORATION_PARTICIPANT_EXISTS: "This session is already authorized or active. Refresh the participant list before continuing.",
      COLLABORATION_PRIMARY_GENERATION_CONFLICT: "The primary role changed. Your input is preserved; refresh and review the current primary generation.",
      COLLABORATION_HANDOFF_REQUIRES_ACTIVE_MEMBER: "The target session must complete JOIN before it can become primary.",
      COLLABORATION_ACTOR_MISMATCH: "Only the task's existing owner client can participate in this version of collaboration.",
      COLLABORATION_ALREADY_REVOKED: "This participant was already revoked. Refresh the session list.",
      COLLABORATION_ALREADY_PRIMARY: "This session is already primary. Refresh the session list.",
      COLLABORATION_ALREADY_ENABLED: "Collaboration is already enabled. Refresh the task before making another change.",
      COLLABORATION_NOT_ENABLED: "Enable collaboration on this task first.",
      COLLABORATION_TASK_DELETED: "Restore the task and its Project before changing collaboration.",
      LOCAL_COLLABORATION_READBACK_PENDING: "The complete accepted version has not been confirmed. Query the original request; the change will not be resubmitted.",
    };
    return bindingProblems[detail] || detail || "Something went wrong. Please try again.";
  }
  if (error instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(detail)) {
    return "无法连接服务。请确认已连接获准访问的网络，再重试。";
  }
  if (detail.includes("repository origin must not contain embedded credentials")) {
    return "仓库源地址不能包含 token、用户名密码等内嵌凭据。请使用不含凭据的 origin 地址，并在 Worker 主机配置 Git 访问授权。";
  }
  if (detail.includes("repository origin is not a valid credential-free Git address")) {
    return "仓库源地址格式无效。请检查 origin 地址，并在 Worker 主机配置 Git 访问授权。";
  }
  if (/^Project cannot be deleted:/i.test(detail)) {
    return "此项目仍有关联数据，无法删除。有未删除任务时，请先在任务列表删除；有受管或原生测试运行历史时，请改为归档项目。";
  }
  if (/version is stale/i.test(detail)) {
    return "记录已被其他操作更新，当前输入已保留。请刷新记录并核对最新版本，再重新打开编辑窗口。";
  }
  const known: Record<string, string> = {
    "TASK_VERSION_CONFLICT": "任务版本已变化，当前输入已保留。请刷新记录，核对后重新开始本次操作。",
    "TASK_ALREADY_BOUND": "任务已经绑定会话，不能修改绑定授权。请刷新任务查看已有会话。",
    "TASK_BINDING_REQUIRED": "此客户端需要先显式绑定任务 ID，再同步测试产物。",
    "TASK_BINDING_ACTOR_REQUIRED": "此任务尚未授权本地客户端，请在任务页选择获准绑定的客户端。",
    "TASK_BINDING_ACTOR_MISMATCH": "当前客户端不是此任务获准的绑定客户端，请核对任务授权。",
    "TASK_BINDING_ACTOR_UNAVAILABLE": "所选客户端没有本项目的有效同步授权。请刷新客户端列表，或先完成本地接入。",
    "SESSION_ALREADY_HAS_TASK": "当前真实会话已有任务，请查看并复用已有任务，不能另绑或重复创建。",
    "TASK_ID_REQUIRED": "请明确指定已绑定的任务 ID，不能按标题或会话猜测目标。",
    "TASK_ID_MISMATCH": "任务 ID 与当前绑定不一致，请核对原任务和真实会话后再同步。",
    "TASK_BINDING_DELETED": "任务或项目已删除。请先在回收站恢复，再进行绑定。",
    "TASK_OPERATION_KEY_CONFLICT": "此请求标识已用于另一组输入。请保留原标识，先按原请求查询对账。",
    "TASK_CREATION_RECEIPT_NOT_FOUND": "尚未找到原创建请求回执。请继续查询原 key，不代表可以再次提交创建请求。",
    "LOCAL_TASK_CREATION_RECEIPT_MISMATCH": "创建回执与固定请求不一致。请按原 key 查询，不要另建任务。",
    "COLLABORATION_KEY_CONFLICT": "原 key 已用于不同输入。请保留未决请求，继续查询原 key。",
    "COLLABORATION_RECEIPT_NOT_FOUND_NO_REPLAY": "尚未找到原 key 的回执。请继续查询原 key，不能据此重新提交。",
    "COLLABORATION_PARTICIPANT_EXISTS": "该会话已经获准加入或正在参与。请刷新参与会话列表后再操作。",
    "COLLABORATION_PRIMARY_GENERATION_CONFLICT": "主会话责任已变化，当前输入已保留。请刷新后核对最新主会话代次。",
    "COLLABORATION_HANDOFF_REQUIRES_ACTIVE_MEMBER": "目标会话须先完成 JOIN，才能成为主会话。",
    "COLLABORATION_ACTOR_MISMATCH": "当前协作版本只允许任务原有 owner 客户端参与。",
    "COLLABORATION_ALREADY_REVOKED": "该参与会话已经被撤销权限。请刷新会话列表。",
    "COLLABORATION_ALREADY_PRIMARY": "该会话已经是当前主会话。请刷新会话列表。",
    "COLLABORATION_ALREADY_ENABLED": "此任务已经启用协作。请刷新任务后再进行新变更。",
    "COLLABORATION_NOT_ENABLED": "请先在此任务中启用多会话协作。",
    "COLLABORATION_TASK_DELETED": "请先恢复任务及所属项目，再修改协作状态。",
    "LOCAL_COLLABORATION_READBACK_PENDING": "尚未完整确认固定接受版本。请查询原请求，系统不会重新提交此变更。",
    "controlled environment unavailable; build the configured profile on this host": "受控环境当前不可用。请在执行主机准备与所选配置匹配的可信镜像，再刷新环境可用性；当前草稿会保留。",
    "ASGI application module must be tracked in the pinned source": "ASGI 应用模块必须是固定源码中已跟踪的文件。请核对应用对象路径与提交 SHA。",
    "controlled environments require the Docker runner": "固定受控环境必须通过 Docker Runner 执行，不能改用本机进程。",
    "report artifact unavailable or checksum mismatch": "报告文件不可用或完整性校验失败。请检查服务端产物存储后重试，不能将未校验内容当作已保存报告。",
    "implementation artifact unavailable or checksum mismatch": "测试源码文件不可用或完整性校验失败。请检查服务端产物存储后重试。",
    "implementation source belongs to the pinned repository": "此实现引用固定仓库内的已有测试，没有平台保存的生成源码文件。请在固定提交中查看对应文件。",
    "implementation not found in this run": "此实现不属于当前运行的项目与固定源码快照。请刷新正式测试产物后重试。",
    "binding recovery state changed; refresh before trying again": "会话恢复状态已变化。请刷新当前状态后再操作，避免重复接管。",
    "persistent or queued missions are controlled by their background task; use task controls": "此运行的阶段由后台任务统一控制。请在后台任务中操作，或检查持续会话状态。",
    "persistent missions are controlled by their background task; use task controls": "此运行使用持续会话。请通过后台任务继续，避免单独启动新的阶段会话。",
    "project not found": "项目不存在，请返回项目列表刷新后重试。",
    "Project not found": "项目不存在或已删除，请返回项目列表或回收站核对后重试。",
    "Project is not deleted": "此项目已经恢复或尚未删除。请刷新查看当前状态。",
    "Session task is not deleted": "此任务已经恢复或尚未删除。请刷新查看当前状态。",
    "Session task is deleted; restore it explicitly before synchronization": "此任务已删除。请先从项目的任务回收站恢复，再继续同步。",
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
      : error.status >= 500 ? "服务暂时不可用。请确认访问网络和服务运行状态后重试。"
      : "请求未完成，请检查输入后重试。";
    return detail ? `${hint} 服务端详情：${detail}` : hint;
  }
  return detail ? `操作未完成：${detail}` : "操作未完成，请重试。";
}

async function responseError(response: Response, fallback?: string): Promise<ApiError> {
  const body = await response.text();
  let detail = fallback || "";
  let existingTaskId: string | undefined;
  try {
    const problem = JSON.parse(body) as { detail?: unknown };
    if (typeof problem.detail === "string") detail = problem.detail;
    else if (Array.isArray(problem.detail)) {
      detail = problem.detail.map((issue) => `${issue.loc?.slice(1).join(".") || "Input"}: ${issue.msg}`).join("; ");
    } else if (problem.detail && typeof problem.detail === "object") {
      const issue = problem.detail as { code?: unknown; existing_task_id?: unknown };
      if (typeof issue.code === "string") detail = issue.code;
      if (typeof issue.existing_task_id === "string") existingTaskId = issue.existing_task_id;
    }
  } catch {
    // Proxy HTML is not a useful form error. Retain safe text diagnostics only.
    if (!response.headers.get("content-type")?.includes("text/html")) detail ||= body.slice(0, 2000);
  }
  return new ApiError(response.status, detail, existingTaskId);
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

export const getProjects = (includeDeleted = false) => api<Project[]>(`/projects${includeDeleted ? "?include_deleted=true" : ""}`);
export const createProject = (payload: ProjectCreate) =>
  api<Project>("/projects", { method: "POST", body: JSON.stringify(payload) });
export const updateProject = (projectId: string, payload: ProjectUpdate) =>
  api<Project>(`/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteProject = (projectId: string, expectedVersion: number) =>
  api<Project>(`/projects/${encodeURIComponent(projectId)}?expected_version=${expectedVersion}`, { method: "DELETE" });
export const restoreProject = (projectId: string, expectedVersion: number) =>
  api<Project>(`/projects/${encodeURIComponent(projectId)}/restore`, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
export const createRun = (projectId: string, payload: RunCreate) =>
  api<TestRun>(`/projects/${projectId}/runs/bootstrap`, { method: "POST", body: JSON.stringify(payload) });
export const resolveSource = (payload: { repository_url: string; revision: string }) =>
  api<SourceResolution>("/sources/resolve", { method: "POST", body: JSON.stringify(payload) });
export const getProject = (projectId: string, includeDeleted = false) => api<Project>(`/projects/${encodeURIComponent(projectId)}${includeDeleted ? "?include_deleted=true" : ""}`);
export const getProjectRuns = (projectId: string) =>
  api<TestRun[]>(`/projects/${projectId}/test-runs`);
export const getProjectTasks = (projectId: string, offset = 0, limit = 20, includeDeleted = false) =>
  api<SessionTaskList>(`/tasks?project_id=${encodeURIComponent(projectId)}&limit=${limit}&offset=${offset}${includeDeleted ? "&include_deleted=true" : ""}`);
export const getLocalTaskActors = (projectId: string) =>
  api<LocalTaskActorList>(`/projects/${encodeURIComponent(projectId)}/local-task-actors`);
export const createLocalTask = (projectId: string, payload: LocalTaskCreate) =>
  api<SessionTaskDetail>(`/projects/${encodeURIComponent(projectId)}/local-tasks`, { method: "POST", body: JSON.stringify(payload) });
export const getLocalTaskCreation = (projectId: string, idempotencyKey: string) =>
  api<SessionTaskDetail>(`/projects/${encodeURIComponent(projectId)}/local-tasks/by-key?idempotency_key=${encodeURIComponent(idempotencyKey)}`);
export const updateTaskBindingAuthorization = (taskId: string, payload: TaskBindingAuthorization) =>
  api<SessionTaskDetail>(`/tasks/${encodeURIComponent(taskId)}/binding-authorization`, { method: "PATCH", body: JSON.stringify(payload) });
export const getSessionTask = (taskId: string, version?: number, includeDeleted = false) => {
  const query = [version === undefined ? "" : `version=${version}`, includeDeleted ? "include_deleted=true" : ""].filter(Boolean).join("&");
  return api<SessionTaskDetail>(`/tasks/${encodeURIComponent(taskId)}${query ? `?${query}` : ""}`);
};
export const getTaskCollaboration = (taskId: string, version?: number) =>
  api<CollaborationDocument>(`/tasks/${encodeURIComponent(taskId)}/collaboration?include_deleted=true${version === undefined ? "" : `&version=${version}`}`);
export const changeTaskCollaboration = (taskId: string, payload: CollaborationRequest) =>
  api<CollaborationReceipt>(`/tasks/${encodeURIComponent(taskId)}/collaboration`, { method: "POST", body: JSON.stringify(payload) });
export const getTaskCollaborationReceipt = (taskId: string, key: string) =>
  api<CollaborationReceipt>(`/tasks/${encodeURIComponent(taskId)}/collaboration/receipts/by-key?idempotency_key=${encodeURIComponent(key)}`);
export const updateSessionTask = (taskId: string, payload: SessionTaskUpdate) =>
  api<SessionTaskDetail>(`/tasks/${encodeURIComponent(taskId)}`, { method: "PATCH", body: JSON.stringify(payload) });
export const deleteSessionTask = (taskId: string, expectedVersion: number) =>
  api<SessionTaskDetail>(`/tasks/${encodeURIComponent(taskId)}?expected_version=${expectedVersion}`, { method: "DELETE" });
export const restoreSessionTask = (taskId: string, expectedVersion: number) =>
  api<SessionTaskDetail>(`/tasks/${encodeURIComponent(taskId)}/restore`, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
export const getSessionReport = (taskId: string, revisionId: string) =>
  api<SessionReportRevision>(`/tasks/${encodeURIComponent(taskId)}/reports/${encodeURIComponent(revisionId)}`);
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
export const getImplementationContent = async (runId: string, implementationId: string) => {
  const response = await fetch(`${API_PREFIX}/test-runs/${runId}/implementations/${implementationId}/content`);
  if (!response.ok) throw await responseError(response, "The saved test source is unavailable or failed integrity verification.");
  return response.text();
};
export const getExecutions = (runId: string) => api<TestExecution[]>(`/test-runs/${runId}/executions`);
export const getExecution = (executionId: string) => api<ExecutionDetail>(`/executions/${executionId}`);
export const getEvidence = (runId: string) => api<Evidence[]>(`/test-runs/${runId}/evidence`);
export const getEvidenceContent = async (evidenceId: string) => {
  const response = await fetch(`${API_PREFIX}/evidence/${evidenceId}/content`);
  if (!response.ok) throw await responseError(response, "Unable to load evidence content");
  return response.text();
};
export const getFindings = (runId: string) => api<Finding[]>(`/test-runs/${runId}/findings`);
export const getFindingHistory = (findingId: string) => api<FindingHistory>(`/findings/${findingId}/history?limit=50`);
export const transitionFinding = (findingId: string, payload: FindingTransition) =>
  api<Finding>(`/findings/${findingId}/transition`, { method: "POST", body: JSON.stringify(payload) });
export const getCapabilities = () => api<Capabilities>("/capabilities");
export const getExecutionEnvironments = () => api<EnvironmentCatalog>("/execution-environments");
export const getSourceSnapshot = (snapshotId: string) => api<SourceSnapshot>(`/source-snapshots/${snapshotId}`);
export const getPolicySnapshot = (snapshotId: string) => api<PolicySnapshot>(`/policy-snapshots/${snapshotId}`);
export const getPrdContent = async (snapshotId: string) => {
  const response = await fetch(`${API_PREFIX}/source-snapshots/${snapshotId}/prd`);
  if (!response.ok) throw await responseError(response, "The saved requirements are unavailable or failed integrity verification.");
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await response.arrayBuffer());
};
export const getConfigurationContent = async (snapshotId: string) => {
  const response = await fetch(`${API_PREFIX}/source-snapshots/${snapshotId}/configuration`);
  if (!response.ok) throw await responseError(response, "The saved configuration is unavailable or failed integrity verification.");
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await response.arrayBuffer());
};
export const getVerdicts = (runId: string) => api<Verdict[]>(`/test-runs/${runId}/verdicts`);
export const getJobs = (runId: string) => api<BackgroundJob[]>(`/test-runs/${runId}/jobs`);
export const getJob = (jobId: string) => api<BackgroundJob>(`/jobs/${jobId}`);
export const getJobActivity = (jobId: string, before?: string, signal?: AbortSignal) => {
  const query = new URLSearchParams({ limit: "30" });
  if (before) query.set("before", before);
  return api<JobActivity>(`/jobs/${jobId}/activity?${query}`, { signal });
};
export const createJob = (runId: string, payload: JobCreate) =>
  api<BackgroundJob>(`/test-runs/${runId}/jobs`, { method: "POST", body: JSON.stringify(payload) });
export const cancelJob = (jobId: string) => api<BackgroundJob>(`/jobs/${jobId}/cancel`, { method: "POST" });
export const retryJob = (jobId: string, idempotencyKey: string) =>
  api<BackgroundJob>(`/jobs/${jobId}/retry`, { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey }) });

export const getRunHarness = (runId: string) => api<RunHarness>(`/test-runs/${runId}/harness`);
export const getRunReports = (runId: string) => api<RunReport[]>(`/test-runs/${runId}/reports`);
export const getRunReportContent = async (reportId: string) => {
  const response = await fetch(`${API_PREFIX}/reports/${reportId}/content`);
  if (!response.ok) throw await responseError(response, "The saved report is unavailable or failed integrity verification.");
  return response.text();
};
export const recoverRunBinding = (binding: RunBinding) => api<unknown>(`/bindings/${binding.id}/recover`, {
  method: "POST", body: JSON.stringify({ expected_epoch: binding.binding_epoch, expected_row_version: binding.row_version }),
});
