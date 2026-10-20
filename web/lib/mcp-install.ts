export const MCP_RELEASE_VERSION = "mcp-v0.1.0";
export const MCP_RELEASE_MANIFEST = `https://github.com/ZhangLiangchen/hypertest-one/releases/download/${MCP_RELEASE_VERSION}/release-manifest.json`;

type InstallPromptOptions = {
  apiUrl: string;
  projectId: string;
  locale: "zh" | "en";
  host: "generic" | "codex-desktop";
};

/** The install prompt carries public context only; credentials must stay outside chat. */
export function buildMcpInstallPrompt(options: InstallPromptOptions): string {
  const allowed = new Set(["apiUrl", "projectId", "locale", "host"]);
  if (Object.keys(options).some((key) => !allowed.has(key))) throw new Error("public-context-only");
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(options.projectId)) throw new Error("project-id");
  if (options.locale !== "zh" && options.locale !== "en") throw new Error("locale");
  if (options.host !== "generic" && options.host !== "codex-desktop") throw new Error("host");
  let url: URL;
  try { url = new URL(options.apiUrl); } catch { throw new Error("api-url"); }
  if (options.apiUrl !== options.apiUrl.trim() || /[\s\\$`"';&|<>(){}]/.test(options.apiUrl)
    || url.protocol !== "https:" || url.username || url.password || url.search || url.hash
    || url.pathname !== "/api/v1"
    || !/^(?:\[[a-f\d:.]+\]|[a-z\d](?:[a-z\d.-]*[a-z\d])?)$/i.test(url.hostname)) throw new Error("api-url");
  const apiUrl = JSON.stringify(url.href);
  const projectId = JSON.stringify(options.projectId.toLowerCase());
  const host = options.host;
  if (options.locale === "zh") return [
    `请为当前 Agent 安装并配置 HyperTest One MCP，平台 API 为 ${apiUrl}，项目 ID 为 ${projectId}，host 为 ${host}。`,
    `仅从固定发行 ${MCP_RELEASE_VERSION} 的官方清单 ${MCP_RELEASE_MANIFEST} 下载对应 wheel，先校验清单中的 SHA-256，再在本机用户拥有、权限 0700 的绝对路径目录内创建私有 Python 3.12+ 虚拟环境并安装该 wheel 的 [interactive] 依赖；发行不存在或校验失败时停止并提示联系管理员，不得改用 latest、main、其他镜像或未校验包。`,
    "先检查本机 macOS/Linux、Python 和当前 Agent 的 stdio MCP 配置能力。设备管理密钥由部署管理员从受保护的 platform.env 中提供给本机权限 0600 的文件，或由用户直接在独立 CLI 的隐藏 TTY 提示中输入；不要要求用户在聊天中发送密钥，不要读取、回显、复制、记录或把密钥作为命令行参数传递；它不是 Git、glab 或模型 API 密钥，也不能由普通用户从平台下载。",
    `使用私有虚拟环境中的 Python 运行 python -m hypertest.interactive_client setup --api-url ${apiUrl} --project-id ${projectId} --directory <本机私有绝对路径> --host ${host}；若用户已自行准备密钥文件，只添加 --operator-key-file <0600文件的绝对路径>，否则让独立 CLI 在 TTY 中隐藏读取，Agent 不得代填；私有 CA 仅通过 --ca-file <CA文件路径> 提供，禁止关闭 TLS 校验。`,
    "setup 会配对新设备、为此项目授予 MCP 权限并写入受保护配置；确认 setup 结果后，仅把生成的 stdio 命令及配置文件路径合并进当前 Agent 的 MCP 配置，保留其他 MCP 服务，配置中不得嵌入任何令牌。运行 python -m hypertest.interactive_client doctor --config <生成的配置文件绝对路径>，提醒我重新加载或重启 Agent 后查询该项目以验证连接；不要宣称当前聊天已热加载插件。",
    "通用 Agent 首版支持 macOS/Linux stdio 安装、提交、查询及 CLOUD 执行；只有受控的 Codex Desktop 原生适配器可绑定当前 Agent 进行 LOCAL 执行。不要伪造会话标识，不要把 Windows 或任意 Agent 的 LOCAL 执行描述为已支持。此次仅安装和配对，不提交测试运行、不传源码、不操作问题单；后续由我在当前 Agent 中通过 MCP 发起新运行。安装不会改变网页创建表单的受管 Connector 模式。",
  ].join(" ");
  return [
    `Install and configure the HyperTest One MCP for this Agent with API ${apiUrl}, project ID ${projectId}, and host ${host}.`,
    `Download only the wheel identified by the official fixed ${MCP_RELEASE_VERSION} manifest at ${MCP_RELEASE_MANIFEST}, verify its SHA-256 before installation, and install that wheel with its [interactive] extra in a private Python 3.12+ virtual environment inside a user-owned absolute directory with mode 0700. If the release is unavailable or verification fails, stop and contact the administrator; do not substitute latest, main, another mirror, or an unverified package.`,
    "Check macOS/Linux, Python, and this Agent's stdio MCP configuration support first. A deployment administrator must provide the device management key from protected platform.env into a local mode-0600 file, or the user must enter it directly at the standalone CLI's hidden TTY prompt. Never ask for the key in chat, read, echo, copy, log, or pass it as a command-line value. This is not a Git, glab, or model API key and ordinary users cannot download it from the platform.",
    `Using the private environment's Python, run python -m hypertest.interactive_client setup --api-url ${apiUrl} --project-id ${projectId} --directory <private absolute local directory> --host ${host}. Add --operator-key-file <absolute path to the mode-0600 file> only if the user has prepared it; otherwise let the standalone CLI read it privately from a TTY without Agent autofill. Supply a private CA only via --ca-file <CA file path>; never disable TLS verification.`,
    "setup pairs a new device, grants MCP access to this project, and writes protected configuration. After checking its result, merge only the generated stdio command and configuration-file path into this Agent's MCP configuration, preserving every other MCP server and embedding no tokens. Run python -m hypertest.interactive_client doctor --config <absolute generated configuration path>, then ask me to reload or restart the Agent and query this project to verify connectivity. Do not claim this conversation has hot-loaded the plugin.",
    "The first release supports macOS/Linux stdio installation, submission, reads, and CLOUD execution for generic Agents; only the controlled Codex Desktop native adapter can bind this Agent for LOCAL execution. Never fabricate session IDs or claim Windows or arbitrary-Agent LOCAL support. This request authorizes installation and pairing only, with no test-run submission, source transfer, or issue operations. I will create a new run through MCP in this Agent afterward. Installation does not change the web form's managed Connector mode.",
  ].join(" ");
}
