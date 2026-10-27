import { CLI_RELEASE, cliInstallCommand, type CliRelease } from "./cli-release";

type Options = { locale?: "zh" | "en"; server?: string; projectId?: string };
const quote = (value: string) => `'${value.replace(/'/g, `'"'"'`)}'`;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

function project(value?: string) {
  if (value === undefined) return undefined;
  if (!uuid.test(value)) throw new Error("CLI_INSTALL_PROJECT_INVALID");
  return value.toLowerCase();
}

function origin(value: string) {
  let parsed: URL;
  try { parsed = new URL(value); } catch { throw new Error("CLI_INSTALL_SERVER_INVALID"); }
  if (/\s/.test(value) || parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash
    || !/^(?:[a-z0-9.-]+|\[[a-f0-9:]+\])$/i.test(parsed.hostname)
    || (value !== parsed.origin && value !== `${parsed.origin}/`)) throw new Error("CLI_INSTALL_SERVER_INVALID");
  return parsed.origin;
}

/** Public context only. Project is a pairing hint, never an authorization. */
export function cliBindCommand(server: string, projectId?: string): string {
  const selected = project(projectId);
  return `hypertest auth bind --server ${quote(origin(server))} --profile default${selected ? ` --project-id ${quote(selected)}` : ""} --wait-seconds 0 --json`;
}

/** One text source for the PC copy action, repository guide, and Release assets. */
export function cliInstallPrompt(options: Options = {}, release: CliRelease = CLI_RELEASE): string | null {
  if (!release.published) return null;
  cliInstallCommand(release); // Reuse pinned release/version/digest validation.
  for (const address of [release.releaseUrl, release.installerUrl, release.artifactUrl]) {
    if (/\s/.test(address) || new URL(address).href !== address) throw new Error("CLI_RELEASE_METADATA_INVALID");
  }
  const server = options.server === undefined ? undefined : origin(options.server);
  const projectId = project(options.projectId);
  const bind = server ? cliBindCommand(server, projectId) : null;
  const install = `PYTHON -I install-cli-release.py --artifact ./hypertest-cli-${release.version}.pyz --sha256 ${release.artifactSha256} --version ${release.version}`;
  const artifacts = [
    `Release: ${release.releaseUrl}`,
    `Source commit: ${release.sourceCommit}`,
    `Installer: ${release.installerUrl}`,
    `Installer SHA-256: ${release.installerSha256}`,
    `CLI: ${release.artifactUrl}`,
    `CLI SHA-256: ${release.artifactSha256}`,
  ].join("\n");
  if (options.locale === "en") return `Please install HyperTest CLI ${release.version} and the explicit hypertest-archive Skill for my Agent's user account on the intended machine. Carry out the installation instead of only giving instructions. Routine user-level installation and PATH setup are authorized.

HyperTest One now uses explicit post-test archival: Skill → CLI → HTTPS. The old hypertest-local MCP/Hooks integration is retired. Install the pinned cli-v${release.version} package below; do not select a local-v*/mcp-v* release or the repository's global Latest.

${artifacts}

1. Confirm the execution machine and user account. If I asked for my computer but this session runs remotely, explain the mismatch before installing there. Detect Linux/macOS and an existing Python 3.12+ interpreter; reuse it. If missing, use an existing trusted local tool to install a user-level runtime when possible. Do not replace system Python; report a concrete prerequisite if administrator access or an unsupported OS blocks installation. Check an existing hypertest command and managed installation first; preserve customized/unmanaged commands and do not silently downgrade a newer version.
2. Download both pinned HTTPS files into a temporary directory. Compute their actual SHA-256 values with local tools and compare them against both values above before executing any downloaded Python. Stop on a mismatch or failed download. Keep TLS verification enabled; no curl | sh. Use only a trusted public CA certificate if the environment requires one.
3. Replace PYTHON below with the absolute path of the verified Python 3.12+ interpreter, then run from the download directory:
${install}
The default launcher is ~/.local/bin/hypertest. Make it available to the current Agent and future shells, updating the user's actual shell PATH configuration only if needed and without duplicate entries. Preserve existing profiles, credentials, CA, journals, pending requests, artifacts, and modified Skill files. Do not automatically remove old integration configuration as part of installation.
4. Run hypertest --version and hypertest profile show --json; do not open private credential files. Identify the current Agent host. For Codex, install the bundled Skill with:
hypertest skill install --global --host codex --json
For another host, use hypertest skill install --directory with its confirmed skills directory, or ask only for the missing directory. Keep implicit invocation disabled. Do not install MCP, Hooks, a native bridge, or a daemon.
5. ${server ? `The intended HyperTest One server is ${server}.${projectId ? ` Project hint: ${projectId}.` : ""} Reuse an existing matching authorized profile; with multiple profiles, have me select one. If a new binding is needed and the default profile name is available, run:\n${bind}\nIf default belongs to another server or identity, preserve it and use a name I select.` : `No HyperTest One server address is supplied.${projectId ? ` Project hint: ${projectId}.` : ""} Finish installation and Skill setup first. Reuse an existing profile only when I have selected it; otherwise ask for the HTTPS server address before binding. Never guess a server or project. Start a new binding with hypertest auth bind --server <confirmed HTTPS origin> --profile <selected name> --wait-seconds 0 --json, adding --project-id only for an explicitly supplied project.`}
Show the returned authorization URL and short code. I must approve the uploader identity, projects, permissions, and expiry on the Web page; do not approve for me or request an Operator key. --wait-seconds 0 can return PENDING/exit 4 normally. Preserve the original request_id. After my approval, use hypertest auth bind --resume --request-id <original ID> --wait-seconds 0 --json to advance only the unsent next phase. For UNKNOWN or lost responses, use hypertest auth reconcile --request-id <original ID> --json; never create another pairing to retry an uncertain request. Installation can be complete while authorization remains pending.
6. Once bound, run hypertest doctor with the selected profile (and supplied project, if any). Report the installed version/path, Skill location, authorization state, and any remaining action. Clean up only your disposable downloads after success. Do not create test tasks, run tests, or upload artifacts during installation. Later uploads require an explicit request with Project ID and Task ID; Subtask ID is optional.
`;
  return `请在我指定的 Agent 运行机器上，为当前用户安装 HyperTest CLI ${release.version} 和显式归档 Skill hypertest-archive。请实际完成操作，不要只返回安装说明。常规用户级安装和必要的 PATH 配置已获授权。

HyperTest One 现采用测试后显式归档：Skill → CLI → HTTPS。旧 hypertest-local MCP/Hooks 接入已弃用。请安装下方固定的 cli-v${release.version}，不要选择 local-v*/mcp-v* 或仓库全局 Latest。

${artifacts}

1. 确认实际执行机器与用户账号；如果我要求本机而当前会话连接远程机器，先说明差异，不要误装到远程。检测 Linux/macOS 及已有 Python 3.12+，优先复用。缺少时可通过本机已有可信工具安装用户级运行时，不替换系统 Python；确需管理员权限或操作系统不支持时，说明具体缺口。先检查已有 hypertest 命令与受管安装，保留被修改或非受管的命令，不静默降级较新版本。
2. 在临时目录下载上述两个固定 HTTPS 文件，用本地工具计算实际 SHA-256，分别与上面两个摘要核对一致后，才允许执行下载的 Python。下载失败或摘要不符立即停止。保持 TLS 校验，不使用 curl | sh；若需显式指定 CA，只使用可信 CA 的公开证书。
3. 将下列 PYTHON 替换成已核验的 Python 3.12+ 解释器绝对路径，在下载目录执行：
${install}
默认启动命令为 ~/.local/bin/hypertest。让当前 Agent 与后续终端可找到该命令，仅在需要时为实际使用的用户 shell 幂等补充 PATH。保留已有 profile、凭据、CA、journal、未决请求、产物与用户修改过的 Skill；安装不自动清理旧接入配置。
4. 执行 hypertest --version 和 hypertest profile show --json，不直接读取私有凭据文件。识别当前 Agent 宿主：Codex 使用：
hypertest skill install --global --host codex --json
其他宿主使用 hypertest skill install --directory 指向已确认的技能目录；无法确定时只询问缺少的目录。保持 Skill 禁止隐式调用，不安装 MCP、Hooks、native bridge 或 daemon。
5. ${server ? `目标 HyperTest One 服务器：${server}。${projectId ? `预选项目：${projectId}。` : ""}已有匹配且获准的 profile 时复用；存在多个 profile 时由我选择。需要新绑定且 default 名称可用时执行：\n${bind}\n若 default 已属于另一服务器或身份，保留它，改用我选择的名称。` : `此 Prompt 未提供 HyperTest One 服务地址。${projectId ? `预选项目：${projectId}。` : ""}先完成安装与 Skill 配置；已有 profile 只在我明确选择后复用，否则再询问 HTTPS 服务地址用于绑定，不猜测地址或项目。通过 hypertest auth bind --server <已确认HTTPS地址> --profile <选定名称> --wait-seconds 0 --json 发起配对，仅在明确提供项目时添加 --project-id。`}
将 CLI 返回的授权链接和短码交给我，由我在 Web 确认上传身份、项目、权限和有效期；不要代替我批准或索取 Operator key。--wait-seconds 0 返回 PENDING/退出码4属于正常待批准，保留原 request_id。我批准后，用 hypertest auth bind --resume --request-id <原ID> --wait-seconds 0 --json 仅推进尚未发送的下一阶段。UNKNOWN 或失答时用 hypertest auth reconcile --request-id <原ID> --json 查询，不能换请求重复配对。安装完成与授权待完成分别报告。
6. 已绑定后，用选定 profile（及明确提供的项目）执行 hypertest doctor。最后报告版本、实际命令路径、Skill 位置、授权状态和剩余操作；成功后仅清理本轮临时下载文件。安装过程中不创建测试任务、不执行测试、不上传产物。后续归档须显式请求，提供项目 ID、任务 ID；子任务 ID 可选。
`;
}
