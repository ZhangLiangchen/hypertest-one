"use client";

import { LaptopOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, Form, Input, Radio, Select, Space, Tag, Typography } from "antd";
import { useId, useMemo, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { buildLocalModeCommands, buildPublishedLocalCommand, LOCAL_CANDIDATE_VERSION, LOCAL_PUBLISHED_TARGETS, localConfigTemplate, localManifestTemplate } from "@/lib/local-mode-install";
import type { LocalHarness } from "@/lib/local-mode-install";

function Command({ label, text }: { label: string; text: string }) {
  return <div>
    <Typography.Paragraph strong copyable={{ text }} style={{ marginBottom: 6 }}>{label}</Typography.Paragraph>
    <pre className="artifact-content" aria-label={label}>{text}</pre>
  </div>;
}

/** Installs no software in the browser and reads no local profile or credentials. */
export function LocalModeGuide({ projectId, initiallyOpen = false }: { projectId: string; initiallyOpen?: boolean }) {
  const { t } = useI18n();
  const id = useId();
  const [open, setOpen] = useState(initiallyOpen);
  const [harness, setHarness] = useState<LocalHarness>("codex");
  const [clientConfig, setClientConfig] = useState("");
  const [directory, setDirectory] = useState("");
  const [hostConfig, setHostConfig] = useState("");
  const [dshHome, setDshHome] = useState("");
  const [profile, setProfile] = useState("");
  const [hasPrivateConfig, setHasPrivateConfig] = useState(false);
  const [selectedTarget, setSelectedTarget] = useState(LOCAL_PUBLISHED_TARGETS[0]?.targetId);
  const [automaticHooks, setAutomaticHooks] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const [hookConfig, setHookConfig] = useState("");
  const publishedTarget = LOCAL_PUBLISHED_TARGETS.find((target) => target.targetId === selectedTarget);
  const publishedCommand = useMemo(() => {
    if (!publishedTarget || !hasPrivateConfig) return null;
    try {
      return buildPublishedLocalCommand({ projectId, harness, clientConfig, directory,
        ...(harness === "deepseek-harness" ? { dshHome, profile } : { hostConfig }) }, publishedTarget,
      automaticHooks ? { workspace, hookConfig, harnessVersion: publishedTarget.hosts[harness]?.versions[0] ?? "" } : undefined);
    } catch { return null; }
  }, [publishedTarget, hasPrivateConfig, projectId, harness, clientConfig, directory, dshHome, profile, hostConfig, automaticHooks, workspace, hookConfig]);
  const commands = useMemo(() => {
    if (!hasPrivateConfig) return null;
    try {
      return buildLocalModeCommands({ projectId, harness, clientConfig, directory,
        ...(harness === "deepseek-harness" ? { dshHome, profile } : { hostConfig }) });
    } catch { return null; }
  }, [projectId, harness, clientConfig, directory, hostConfig, dshHome, profile, hasPrivateConfig]);
  const templates = useMemo(() => {
    try { return { config: localConfigTemplate(projectId, harness), manifest: localManifestTemplate(projectId, harness) }; }
    catch { return null; }
  }, [projectId, harness]);
  const deepseek = harness === "deepseek-harness";

  return <div style={{ marginBlock: 16 }}>
    <Button icon={<LaptopOutlined aria-hidden />} aria-expanded={open} aria-controls={`${id}-guide`} onClick={() => setOpen((value) => !value)}>
      {open ? t("Hide local mode setup", "收起本地模式接入") : t("Set up local mode", "接入本地模式")}
    </Button>
    {open ? <section id={`${id}-guide`} aria-labelledby={`${id}-heading`} className="data-surface" style={{ marginTop: 12, padding: 24 }}>
      <Typography.Title id={`${id}-heading`} level={3} style={{ marginTop: 0 }}>{t("Connect this project's local Agent", "接入此项目的本地 Agent")}</Typography.Title>
      <Typography.Paragraph>{t("Keep testing in your Agent and sync selected plans, cases and reports to this project. This setup does not start a model or a test.", "继续在当前 Agent 中开展测试，将选定的计划、用例和报告同步到此项目。此接入流程不启动模型或测试。")}</Typography.Paragraph>
      {LOCAL_PUBLISHED_TARGETS.length ? <Alert showIcon type="info" message={t("Pinned Local release installation", "固定版本 Local 发行安装")} description={t("Choose the exact OS, architecture and Python minor version below. The command verifies the pinned bootstrap before execution, then verifies the target bundle, manifest and offline dependencies. Your existing private Project authorization is required.", "选择准确 OS、架构与 Python 小版本。命令先校验固定摘要的 bootstrap，再核验目标 bundle、manifest 及离线依赖。继续使用已有私有项目授权。") } /> : <Alert showIcon type="warning" message={t("Local release is not published", "Local 发行尚未发布")} description={t("The steps below use a reviewed source checkout on macOS/Linux with Python 3.12+. The candidate label identifies configuration only; it is not a verified release. No download or one-click bootstrap is available yet.", "以下是 macOS/Linux、Python 3.12+ 的已审阅源码候选流程。候选版本标识只记录配置，不代表通过发行校验；当前没有下载地址或一键 bootstrap。") } />}
      <Space wrap style={{ marginTop: 12, marginBottom: 16 }}>
        <Tag>{publishedTarget?.releaseTag ?? LOCAL_CANDIDATE_VERSION}</Tag><Tag>{automaticHooks ? t("Hooks explicitly selected", "Hooks 已明确选择") : t("Hooks disabled", "Hooks 默认关闭")}</Tag><Tag>{publishedTarget ? t("This machine's session needs verification", "本机真实会话待核验") : t("Native session not verified", "真实宿主会话未验收")}</Tag>
      </Space>
      <ol style={{ paddingInlineStart: 22, lineHeight: 1.8, marginBottom: 0 }}>
        <li style={{ paddingInlineStart: 4, marginBottom: 24 }}>
          <Typography.Text strong>{t("Choose your existing Agent and private authorization", "选择已安装的 Agent 与私有授权配置")}</Typography.Text>
          <Form layout="vertical" style={{ marginTop: 12 }}>
            <Form.Item label={t("Agent host", "Agent 宿主")}>
              <Radio.Group aria-label={t("Local Agent host", "本地 Agent 宿主")} value={harness} onChange={(event) => setHarness(event.target.value)}>
                <Space wrap><Radio value="codex">Codex</Radio><Radio value="claude-code">Claude Code</Radio><Radio value="deepseek-harness">DeepSeek harness</Radio></Space>
              </Radio.Group>
            </Form.Item>
            <Typography.Paragraph className="muted">{publishedTarget
              ? deepseek
                ? t("DeepSeek requires an existing home/profile, CLI 0.1.5-rc.1 and components 0.1.5-rc.2. The same published adapter has passed SDK and official headless CLI synchronization; persisted-session resume uses the official Registry API in a new process, not a CLI or SDK-wire resume flag. The command derives --host-config as <DSH_HOME>/profiles/<profile>/cordis.patch.yml.", "DeepSeek 需使用已有 home/profile、CLI 0.1.5-rc.1 与组件 0.1.5-rc.2。同一正式 adapter 已通过 SDK 和官方 headless CLI 同步；持久会话恢复使用新进程的官方 Registry API，不是 CLI 或 SDK wire 的 resume 参数。命令将 --host-config 固定为 <DSH_HOME>/profiles/<profile>/cordis.patch.yml。")
                : t("The published bundle configures MCP and optionally the exact accepted Hooks version. Reload the selected host, then verify this machine's real parent session, automatic events and accepted-version readback.", "正式包配置 MCP，并可明确选择已验收的确切 Hooks 版本。重载选定宿主后，仍需核验本机真实父会话、自动事件与接受版本完整读回。")
              : deepseek
              ? t("DeepSeek uses an existing home/profile. Only MCP configuration is available in this candidate; automatic triggers are blocked pending bridge acceptance.", "DeepSeek 必须选择已有 home/profile。此候选版本仅配置 MCP；自动触发在 bridge 验收前保持受阻。")
              : t("The candidate writes MCP configuration. Host reload, real parent identity and automatic events still require independent acceptance; no host is marked ready here.", "候选版本可写入 MCP 配置。宿主重载、真实父会话身份与自动事件仍需独立验收；本页不将任何宿主标为就绪。")}</Typography.Paragraph>
            <Typography.Paragraph>{t("Target Project", "目标项目")}: <Typography.Text code>{projectId}</Typography.Text></Typography.Paragraph>
            <Form.Item label={t("Existing private client configuration path", "已有私有客户端配置路径")} help={t("Use an absolute path to a mode-0600 profile with an existing task:sync grant for this Project. Its API must use HTTPS. Enter the path only, never the file content or token.", "填写已持有此项目 task:sync 授权、权限 0600 的配置绝对路径；配置中的 API 使用 HTTPS。仅填路径，不填文件内容或 token。") }>
              <Input aria-label={t("Private client configuration path", "私有客户端配置路径")} value={clientConfig} onChange={(event) => setClientConfig(event.target.value)} placeholder="/absolute/private/hypertest-local/config.json" autoComplete="off" spellCheck={false} />
            </Form.Item>
            <Form.Item label={t("Private installation record directory", "私有安装记录目录")}>
              <Input aria-label={t("Private installation record directory", "私有安装记录目录")} value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="/absolute/private/hypertest-local/install" autoComplete="off" spellCheck={false} />
            </Form.Item>
            {deepseek ? <>
              <Form.Item label="DSH_HOME"><Input aria-label="DSH_HOME" value={dshHome} onChange={(event) => setDshHome(event.target.value)} placeholder="/absolute/private/dsh" autoComplete="off" spellCheck={false} /></Form.Item>
              <Form.Item label={t("Existing profile name", "已有 profile 名称")} help={t("The installer targets profiles/<name>/cordis.patch.yml in this home and requires an existing profile/package.json. It does not create or install a Harness profile.", "安装器仅操作此 home 下 profiles/<名称>/cordis.patch.yml，要求已有 profile/package.json；不创建 profile 或安装 Harness。") }><Input aria-label={t("Existing DeepSeek profile name", "已有 DeepSeek profile 名称")} value={profile} onChange={(event) => setProfile(event.target.value)} autoComplete="off" spellCheck={false} /></Form.Item>
            </> : <Form.Item label={t("Explicit MCP host configuration file", "明确选择的宿主 MCP 配置文件")} help={t("Choose the intended configuration scope. Existing unrelated MCP entries are preserved; an ownership conflict stops installation.", "请明确选择配置作用域。安装保留其他 MCP 条目；所有权冲突时停止覆盖。") }>
              <Input aria-label={t("MCP host configuration file", "宿主 MCP 配置文件")} value={hostConfig} onChange={(event) => setHostConfig(event.target.value)} placeholder={harness === "codex" ? "/absolute/path/to/.codex/config.toml" : "/absolute/path/to/.mcp.json"} autoComplete="off" spellCheck={false} />
            </Form.Item>}
            <Checkbox checked={hasPrivateConfig} onChange={(event) => setHasPrivateConfig(event.target.checked)}>{t("I already have a private task:sync profile authorized for this Project.", "我已有获准访问此项目的私有 task:sync 配置。")}</Checkbox>
          </Form>
          {!hasPrivateConfig ? <Alert style={{ marginTop: 12 }} type="info" showIcon message={t("Waiting for existing Project authorization", "等待已有项目授权")} description={t("Ask the Project administrator to arrange a private scoped profile through the existing registration process. This page cannot inspect local files, issue a grant or verify authorization. No credential is entered here.", "请项目管理员通过现有注册流程安排私有 scoped 配置。本页不读取本机文件、不签发 grant，也不能验证授权；此处无需填写任何凭据。") } /> : !commands ? <Typography.Paragraph type="warning" role="status" style={{ marginTop: 12 }}>{t("Enter the absolute private paths and, for DeepSeek, a valid existing profile name to generate installation commands.", "填写私有绝对路径；DeepSeek 还需有效的已有 profile 名称，才能生成安装命令。")}</Typography.Paragraph> : null}
        </li>
        <li style={{ paddingInlineStart: 4, marginBottom: 24 }}>
          {LOCAL_PUBLISHED_TARGETS.length ? <>
            <Typography.Text strong>{t("Install the exact published Local bundle", "安装确切已发布的 Local 包")}</Typography.Text>
            <Typography.Paragraph className="muted">{t("local-v0.1.0 is published for macOS arm64 / Python 3.13 only. Accepted hosts: Claude Code 2.1.218, Codex 0.144.6, and DeepSeek CLI 0.1.5-rc.1 with components 0.1.5-rc.2 (SDK/headless; Registry API resume). Linux remains candidate-only. Downloaded LOCAL_INSTALL.md provides MCP-only and Hooks commands for each host; replace its absolute paths and selected profile, retaining all release digests and version arguments.", "local-v0.1.0 仅正式发布 macOS arm64 / Python 3.13。已验宿主：Claude Code 2.1.218、Codex 0.144.6、DeepSeek CLI 0.1.5-rc.1 与组件 0.1.5-rc.2（SDK/headless；Registry API 恢复）。Linux 仍为候选。下载的 LOCAL_INSTALL.md 为每个宿主分别提供 MCP-only 与 Hooks 命令；仅替换绝对路径和所选 profile，保留全部发行摘要与版本参数。")}</Typography.Paragraph>
            <Form layout="vertical" style={{ marginTop: 12 }}>
              <Form.Item label={t("Published OS / architecture / Python target", "已发布 OS／架构／Python 目标")}>
                <Select aria-label={t("Published Local target", "已发布 Local 目标")} value={selectedTarget} onChange={setSelectedTarget} options={LOCAL_PUBLISHED_TARGETS.map((target) => ({ value: target.targetId, label: `${target.releaseTag} — ${target.targetId}` }))} />
              </Form.Item>
              <Checkbox checked={automaticHooks} onChange={(event) => setAutomaticHooks(event.target.checked)} disabled={publishedTarget?.hosts[harness]?.automaticTrigger !== "ACCEPTED"}>{t("Enable the accepted Hooks version with an explicitly selected workspace policy", "使用已验收 Hooks 版本并明确选择工作区产物策略")}</Checkbox>
              {automaticHooks ? <>
                <Typography.Paragraph className="muted">{t("Verify that your installed host version matches the accepted version shown in the command. The policy publishes the selected workspace's analysis.md as an initial DRAFT / NOT_RUN; it never reads chats or infers PASS from a Stop event. Select cases and raw reports separately through explicit MCP or a reviewed private artifact policy.", "核对已安装宿主与命令中的验收版本一致。此策略仅选择该工作区 analysis.md，初始为 DRAFT／NOT_RUN；不读取聊天或从 Stop 推导 PASS。用例和原始报告须另外通过显式 MCP 或审核过的私有产物策略选择。")}</Typography.Paragraph>
                <Form.Item label={t("Approved test workspace", "获准测试工作区")}><Input aria-label={t("Approved test workspace", "获准测试工作区")} value={workspace} onChange={(event) => setWorkspace(event.target.value)} autoComplete="off" spellCheck={false} /></Form.Item>
                {!deepseek ? <Form.Item label={t("Selected host Hook configuration file", "选定的宿主 Hook 配置文件")}><Input aria-label={t("Selected host Hook configuration file", "选定的宿主 Hook 配置文件")} value={hookConfig} onChange={(event) => setHookConfig(event.target.value)} autoComplete="off" spellCheck={false} /></Form.Item> : null}
              </> : null}
            </Form>
            {publishedCommand ? <Command label={t("Verify and install in one command", "一条命令完成校验与安装")} text={publishedCommand} /> : <Typography.Paragraph className="muted">{t("Complete the existing private authorization paths and selected workspace policy before generating the command.", "先填写已有私有授权路径与选定工作区策略，再生成命令。")}</Typography.Paragraph>}
            <Typography.Paragraph>{t("Reload the selected host and verify an actual parent session's ACK plus complete accepted-version readback. Installation does not establish native acceptance on this machine.", "重新加载选定宿主，并核验真实父会话 ACK 与接受版本完整读回。安装完成不代表本机真实接入已经通过。")}</Typography.Paragraph>
          </> : <>
          <Typography.Text strong>{t("Install the source candidate and check configuration", "安装源码候选并检查配置")}</Typography.Text>
          <Typography.Paragraph className="muted">{t("Run from a reviewed HyperTest One checkout containing the Local modules. Keep its exact source revision for review. The installer does not download a release, install model CLIs, sign in, or grant access.", "在包含 Local 模块的已审阅 HyperTest One 源码目录执行，并记录准确源码版本供复核。安装器不下载发行、不安装模型 CLI、不登录，也不授予权限。")}</Typography.Paragraph>
          {commands ? <>
            <Command label={t("Prepare a private Python environment", "准备私有 Python 环境")} text={commands.prepare} />
            <Command label={t("Merge only the selected host configuration", "仅合并选定宿主的配置")} text={commands.install} />
            <Command label={t("Read-only installation doctor", "只读安装诊断")} text={commands.doctor} />
          </> : <Typography.Paragraph className="muted">{t("Candidate commands appear after the private paths and existing authorization are confirmed above.", "确认上方私有路径与已有授权后，显示源码候选命令。")}</Typography.Paragraph>}
          <Typography.Paragraph>{t("Doctor checks local configuration and credential-file presence. It does not verify the grant on the server, a running host, or a successful sync. Reload the selected Agent yourself; current sessions are not forced to close.", "doctor 检查本机配置和凭据文件是否存在，不证明服务端 grant、运行中的宿主或同步成功。请自行重新加载选定 Agent；安装器不会强退当前会话。")}</Typography.Paragraph>
          </>}
        </li>
        {!LOCAL_PUBLISHED_TARGETS.length ? <><li style={{ paddingInlineStart: 4, marginBottom: 24 }}>
          <Typography.Text strong>{t("Select the real parent session and approved testing assets", "明确真实父会话与获准测试产物")}</Typography.Text>
          <Typography.Paragraph>{t("Use the actual parent session ID from the selected host and this Project's authorized profile. Read the complete current task version with hypertest_get_task; use 0 only for a genuinely new source. Child Agents contribute to this parent and do not create their own task.", "从选定宿主取得真实父 session ID，使用此项目已有授权配置。通过 hypertest_get_task 完整读取当前任务版本；只有真实新来源才用 0。子 Agent 向该父任务交付产物，不另建任务。")}</Typography.Paragraph>
          {templates ? <details><summary>{t("Review incomplete private config and manifest templates", "查看待填写的私有配置与 manifest 模板")}</summary>
            <Typography.Paragraph className="muted">{t("Merge local_sync into the existing private config. Replace every placeholder with an approved source, actual version, absolute selected artifact path and its digest. These templates cannot be submitted as shown. Review content for secrets before selecting it; do not select chats, reasoning, authentication directories or whole workspaces.", "将 local_sync 合并到已有私有配置。用获准来源、真实版本、明确产物绝对路径及摘要替换全部占位内容；下列模板不能直接提交。选取前检查内容中的秘密，不选择聊天、推理、认证目录或整个工作区。")}</Typography.Paragraph>
            <pre className="artifact-content" aria-label={t("Private config additions template", "私有配置追加模板")}>{templates.config}</pre>
            <pre className="artifact-content" aria-label={t("Incomplete approved manifest template", "待填写的正式产物 manifest 模板")}>{templates.manifest}</pre>
          </details> : null}
          <Typography.Paragraph className="muted">{t("Keep the private config and manifest mode 0600, directories mode 0700. A TEST_PLAN file supplies plan_markdown for first creation. Keep reported results explicit; Stop, tool success or an upload does not mean COMPLETED or PASS.", "私有配置、manifest 使用 0600，目录使用 0700。首次创建时 TEST_PLAN 文件提供 plan_markdown。报告结果必须明确；Stop、工具成功或上传完成不代表 COMPLETED 或 PASS。")}</Typography.Paragraph>
        </li>
        <li style={{ paddingInlineStart: 4 }}>
          <Typography.Text strong>{t("Submit explicitly and verify the accepted version", "显式提交并核验接受版本")}</Typography.Text>
          <Typography.Paragraph>{t("Existing hypertest_sync_task / hypertest_get_task MCP calls remain available. To submit the selected private manifest without Hooks, start the private daemon after saving the config above, then run the explicit command below. MCP's existing autostart can start a daemon when none is running. Submission uses only manifest_file from the private config and does not read stdin events or start a model.", "原有 hypertest_sync_task / hypertest_get_task MCP 调用继续保留。无需 Hooks 即可显式提交所选私有 manifest：保存上方配置后启动私有 daemon，再运行下方命令。尚无 daemon 时可由 MCP 既有 autostart 启动。提交只使用私有配置选定的 manifest_file，不读取 stdin 事件或启动模型。")}</Typography.Paragraph>
          {commands ? <Command label={t("Submit the approved manifest", "提交选定的正式产物 manifest")} text={commands.submit} /> : null}
          {commands ? <details><summary>{t("Start or reload the private daemon", "启动或重新加载私有 daemon")}</summary><Typography.Paragraph className="muted">{t("Start it explicitly in a separate terminal with the same private profile. If it was already running when the config changed, host reload alone will not reload that daemon. First finish in-flight work and preserve unresolved keys and journals, then explicitly stop this profile's daemon and start it again. Submission does not silently launch or restart a process.", "在独立终端使用同一私有配置显式启动。若修改配置前 daemon 已运行，单独重载宿主不会重载该 daemon。先完成在途处理、保留未决 key 与账本，再显式停止该配置的 daemon 并重新启动。提交命令不会静默启动或重启进程。")}</Typography.Paragraph><Command label={t("Stop the existing private daemon only when safe", "确认无在途请求后停止原私有 daemon")} text={commands.stopDaemon} /><Command label={t("Start the private daemon explicitly", "显式启动私有 daemon")} text={commands.daemon} /></details> : null}
          <Typography.Paragraph>{t("Only a valid ACK plus complete readback of its fixed accepted version confirms sync. SENT / UNKNOWN or a lost answer must be reconciled by the original key; NOT_FOUND does not permit another POST. Preserve private journals and snapshots. Task progress, reported results and delivery state remain separate.", "只有有效 ACK 加该固定接受版本的完整读回，才能确认同步。SENT / UNKNOWN 或失答只按原 key 查询；NOT_FOUND 不允许再次 POST。保留私有账本与快照。任务进度、报告结果和交付状态分别保留。")}</Typography.Paragraph>
        </li>
        </> : <li style={{ paddingInlineStart: 4 }}>
          <Typography.Text strong>{t("Verify the actual parent session and accepted assets", "核验真实父会话与接受产物")}</Typography.Text>
          <Typography.Paragraph>{t("With Hooks selected, start a real new session in the approved workspace using the installed host version. Only the explicit artifact policy's selected files enter synchronization. Child Agents contribute to the real parent. Existing hypertest_sync_task / hypertest_get_task MCP tools remain available.", "已选择 Hooks 时，使用对应已安装版本在获准工作区开始真实新会话。同步仅选择明确产物策略内的文件；子 Agent 贡献回到真实父会话。原 hypertest_sync_task／hypertest_get_task MCP 工具继续可用。")}</Typography.Paragraph>
          <Typography.Paragraph>{t("Confirm valid ACK and complete readback of that fixed accepted version. SENT / UNKNOWN, a lost answer or NOT_FOUND permits only original-key reconciliation; do not submit again or replace the client identity. Preserve private journals and snapshots. Stop, upload success and Hook delivery do not establish COMPLETED or PASS.", "确认有效 ACK 与该固定接受版本的完整读回。SENT／UNKNOWN、失答或 NOT_FOUND 只按原 key 对账，不重发或替换 client 身份。保留私有账本与快照。Stop、上传成功或 Hook 送达不代表 COMPLETED 或 PASS。")}</Typography.Paragraph>
        </li>}
      </ol>
    </section> : null}
  </div>;
}
