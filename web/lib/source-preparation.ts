import type { Locale } from "./i18n";
import type { BackgroundJob } from "./types";

type Copy = [string, string];
const stages: Record<string, Copy> = {
  validate_input: ["Validate fixed source input", "校验固定源码输入"],
  create_workspace: ["Create managed workspace", "创建托管工作目录"],
  git_init: ["Initialize Git checkout", "初始化 Git 检出目录"],
  configure_remote: ["Configure repository origin", "配置源码仓库来源"],
  fetch_commit: ["Fetch fixed commit", "获取固定提交"],
  checkout_commit: ["Check out fixed commit", "检出固定提交"],
  validate_checkout: ["Verify checkout integrity", "校验检出内容完整性"],
  publish_workspace: ["Save prepared workspace", "保存已准备工作目录"],
};
const categories: Record<string, { label: Copy; summary: Copy; action: Copy }> = {
  authentication: {
    label: ["Git authentication", "Git 认证"],
    summary: ["Git could not authenticate when preparing this source.", "准备源码时，Git 无法完成认证。"],
    action: ["Check the worker host's Git credentials and repository permissions, then retry this recorded task. Keep credentials out of the repository URL.", "请检查 Worker 宿主的 Git 认证配置及仓库权限，再重试此已记录任务。请勿将凭据填入仓库地址。"],
  },
  access_or_missing_repository: {
    label: ["Repository access or availability", "仓库访问或可用性"],
    summary: ["The repository could not be accessed. It may be unavailable or the worker may lack permission.", "无法访问仓库；仓库可能不可用，或 Worker 没有访问权限。"],
    action: ["Check repository availability and the worker host's access. If the repository URL is wrong, create a new round with corrected input; otherwise retry this task after restoring access.", "请检查仓库是否存在，以及 Worker 宿主的访问权限。地址有误时，请创建新轮次修正输入；否则，恢复访问后重试此任务。"],
  },
  network: {
    label: ["Network or proxy", "网络或代理"],
    summary: ["Git could not reach the repository through the worker's network connection.", "Git 无法通过 Worker 的网络连接访问仓库。"],
    action: ["Check DNS, network reachability and Git proxy configuration on the worker host, then retry this task.", "请检查 Worker 宿主的 DNS、网络连通性及 Git 代理配置，再重试此任务。"],
  },
  tls: {
    label: ["TLS verification", "TLS 证书校验"],
    summary: ["Git could not establish a verified secure connection to the repository.", "Git 无法与仓库建立通过证书校验的安全连接。"],
    action: ["Check the worker host's certificate trust and proxy certificates, then retry this task. Preserve TLS verification.", "请检查 Worker 宿主的受信证书及代理证书，再重试此任务。请保留 TLS 证书校验。"],
  },
  revision_not_found: {
    label: ["Fixed commit unavailable", "固定提交不可用"],
    summary: ["The repository did not provide the fixed commit requested by this run.", "仓库未能提供本轮要求的固定提交。"],
    action: ["Check that the full commit is available to the worker. Retry after restoring access, or create a new round if the repository or commit must change.", "请确认 Worker 能够获取该完整提交。恢复访问后可重试；如需更换仓库或提交，请创建新轮次。"],
  },
  storage: {
    label: ["Workspace storage", "工作目录存储"],
    summary: ["Source preparation could not use the managed workspace storage.", "源码准备无法使用托管工作目录的存储。"],
    action: ["Check free space, filesystem availability and worker permissions, then retry this task. Preserve existing workspaces and testing history.", "请检查可用空间、文件系统及 Worker 的目录权限，再重试此任务。请保留已有工作目录和测试历史。"],
  },
  timeout: {
    label: ["Preparation timeout", "源码准备超时"],
    summary: ["Source preparation exceeded its allowed time.", "源码准备超过允许的时间。"],
    action: ["Check repository availability, network speed and worker load, then explicitly retry this task.", "请检查仓库可用性、网络速度及 Worker 负载，再显式重试此任务。"],
  },
  git_unavailable: {
    label: ["Git runtime unavailable", "Git 运行环境不可用"],
    summary: ["The worker could not start Git for source preparation.", "Worker 无法启动 Git 进行源码准备。"],
    action: ["Restore the worker's supported Git runtime and executable permissions, then retry this task.", "请恢复 Worker 支持的 Git 运行环境及执行权限，再重试此任务。"],
  },
  invalid_source: {
    label: ["Unsupported or invalid source input", "源码输入无效或不受支持"],
    summary: ["The fixed source input could not be used for automatic preparation.", "固定源码输入无法用于自动准备。"],
    action: ["Create a new round to review the repository, full commit and supported preparation mode. This run's fixed input cannot be edited.", "请创建新轮次，检查仓库、完整提交及支持的源码准备方式。本轮固定输入不可修改。"],
  },
  checkout_integrity: {
    label: ["Checkout integrity", "检出内容完整性"],
    summary: ["The managed checkout did not match the required fixed source.", "托管检出目录与要求的固定源码不一致。"],
    action: ["Have the operator inspect the original managed checkout without overwriting it. Use a new round for a replacement workspace or changed source input.", "请由操作者检查原托管检出目录，保留其内容。如需替换工作目录或修改源码输入，请创建新轮次。"],
  },
  unknown: {
    label: ["Unclassified preparation error", "未分类的源码准备错误"],
    summary: ["Source preparation failed without a recognized cause.", "源码准备失败，尚未识别具体原因。"],
    action: ["Check the worker's Git access and workspace environment before explicitly retrying this recorded task. This record does not establish a specific root cause.", "请先检查 Worker 的 Git 访问及工作目录环境，再显式重试此已记录任务。此记录不能确定具体根因。"],
  },
};

export type SourcePreparationDiagnostic = {
  stage: string; category: string; retryable: boolean; exit_code: number | null;
  timed_out: boolean; output_truncated: boolean;
};

export function sourcePreparationDiagnostic(job: BackgroundJob): SourcePreparationDiagnostic | null {
  const value = job.result?.source_preparation_diagnostic;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "hypertest.source-preparation-diagnostic/v1"
    || typeof record.stage !== "string" || !Object.hasOwn(stages, record.stage)
    || typeof record.category !== "string" || !Object.hasOwn(categories, record.category)
    || typeof record.retryable !== "boolean" || typeof record.timed_out !== "boolean"
    || typeof record.output_truncated !== "boolean"
    || !(record.exit_code === null || (typeof record.exit_code === "number" && Number.isInteger(record.exit_code) && record.exit_code >= -255 && record.exit_code <= 255))) return null;
  // Display only known enums and primitive metadata. Never render summary,
  // action or unexpected fields from a historical or incompatible API response.
  return { stage: record.stage, category: record.category,
    retryable: record.retryable && !["invalid_source", "checkout_integrity"].includes(record.category),
    exit_code: record.exit_code, timed_out: record.timed_out, output_truncated: record.output_truncated };
}

export function hasSourcePreparationFailure(job: BackgroundJob): boolean {
  const historicalGitFailure = job.error_code === "CONFLICTERROR"
    && job.error_message === "cannot prepare pinned source using configured Git access; verify repository access, commit SHA and network availability"
    && (job.job_type === "PREPARE_WORKSPACE" || job.job_type === "ADVANCE_RUN" && job.payload?.prepare_workspace === true);
  return !!job.result && Object.hasOwn(job.result, "source_preparation_diagnostic")
    || ["SOURCE_PREPARATION_FAILED", "WORKSPACE_PREPARATION_FAILED"].includes(job.error_code || "")
    || job.job_type === "PREPARE_WORKSPACE" && job.status === "FAILED" || historicalGitFailure;
}

export function sourcePreparationCopy(job: BackgroundJob, locale: Locale) {
  if (!hasSourcePreparationFailure(job)) return null;
  const index = locale === "zh" ? 1 : 0;
  const diagnostic = sourcePreparationDiagnostic(job);
  if (!diagnostic) return {
    diagnostic: null,
    stage: index ? "未记录" : "Not recorded",
    category: index ? "详细诊断不可用" : "Detailed diagnosis unavailable",
    summary: index ? "此任务未保存可用的源码准备诊断，无法追认具体原因。" : "No usable source-preparation diagnosis was saved for this task; its specific cause cannot be established.",
    action: index ? "请检查固定仓库及提交、Worker 的 Git 访问与工作目录环境，再查看此任务的关联重试操作。需要修改固定输入时，请创建新轮次。" : "Check the fixed repository and commit, the worker's Git access and workspace, then review this task's linked retry action. Create a new round if fixed input must change.",
  };
  const copy = categories[diagnostic.category];
  return { diagnostic, stage: stages[diagnostic.stage][index], category: copy.label[index], summary: copy.summary[index], action: copy.action[index] };
}

export function sourcePreparationSummary(job: BackgroundJob, locale: Locale): string | null {
  const copy = sourcePreparationCopy(job, locale);
  return copy ? copy.diagnostic ? `${copy.stage} · ${copy.summary}` : copy.summary : null;
}
