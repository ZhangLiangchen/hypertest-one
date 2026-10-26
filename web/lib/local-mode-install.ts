/** Public Local assets are pinned; reviewed source setup remains a separate fallback. */
export const LOCAL_CANDIDATE_VERSION = "local-v0.1.0-candidate";
export const LOCAL_RELEASE_STATE = "PUBLISHED";
export const LOCAL_HARNESSES = ["codex", "claude-code", "deepseek-harness"] as const;
export type LocalHarness = (typeof LOCAL_HARNESSES)[number];

export type LocalUpdateChannel = "stable" | "candidate";
export type LocalUpdater = { url: string; sha256: string };

/** Pinned updater trust anchor; its release discovery cannot replace this code digest. */
export const LOCAL_UPDATER: LocalUpdater = {
  url: "https://github.com/ZhangLiangchen/hypertest-one/releases/download/local-v0.1.1-rc.2/update-local.py",
  sha256: "daec79d1e65c1fc455dc12b40faa502ecb74713c7af264bdb7a7771276dc3da7",
};

export type LocalSetupOptions = {
  projectId?: string;
  harness: LocalHarness;
  channel: LocalUpdateChannel;
  directory?: string;
  clientConfig?: string;
  hostConfig?: string;
  locale?: "en" | "zh";
};

/** One updater handles an owned installation or a fresh, already authorized private profile. */
export function buildLocalUpdateCommand(options: LocalSetupOptions, updater: LocalUpdater = LOCAL_UPDATER): string {
  const allowed = new Set(["projectId", "harness", "channel", "directory", "clientConfig", "hostConfig", "locale"]);
  if (Object.keys(options).some((key) => !allowed.has(key))) throw new Error("public-context-only");
  if (options.projectId) assertContext(options.projectId, options.harness);
  else if (!LOCAL_HARNESSES.includes(options.harness)) throw new Error("harness");
  if (!["stable", "candidate"].includes(options.channel)) throw new Error("channel");
  if (!/^https:\/\/github\.com\/ZhangLiangchen\/hypertest-one\/releases\/download\/local-v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?\/update-local\.py$/.test(updater.url)
    || !/^[a-f0-9]{64}$/.test(updater.sha256)) throw new Error("pinned-updater-required");
  const code = "import hashlib,sys,urllib.request; "
    + `r=urllib.request.urlopen('${updater.url}',timeout=45); `
    + "u=urllib.parse.urlsplit(r.url); "
    + "(u.scheme=='https' and u.hostname in {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}) or sys.exit('BLOCKED: updater redirect'); "
    + "b=r.read(1048577); r.close(); "
    + `(len(b)<=1048576 and hashlib.sha256(b).hexdigest()=='${updater.sha256}') or sys.exit('BLOCKED: updater digest'); `
    + "exec(compile(b,'<verified HyperTest Local updater>','exec'))";
  const args = ["python3", "-I", "-c", quote(code), "--harness", options.harness, "--channel", options.channel];
  for (const [key, flag] of [["directory", "--directory"], ["clientConfig", "--client-config"], ["hostConfig", "--host-config"]] as const) {
    if (options[key]) args.push(flag, quote(privatePath(options[key])));
  }
  return args.join(" ");
}

/** The Agent resolves private files locally; the browser stores no credentials. */
export function buildLocalSetupPrompt(options: LocalSetupOptions, updater: LocalUpdater = LOCAL_UPDATER): string {
  const command = buildLocalUpdateCommand(options, updater);
  const zh = options.locale !== "en";
  const target = options.projectId ? (zh ? `目标 Project：${options.projectId.toLowerCase()}。` : `Target Project: ${options.projectId.toLowerCase()}.`) : "";
  const instructions = zh ? [
    `请在当前机器为 ${options.harness} 安装或升级 HyperTest One Local，使用 ${options.channel} 通道。${target}请直接执行下方固定摘要的官方 updater，完成本地诊断，不要让我手动执行多条命令。`,
    "先读取 ~/.local/share/hypertest-local/<宿主>/host-installation 的受管收据，或我提供的原安装目录；只检查已知收据及其引用配置。已有安装自动复用授权、Hooks、工作区策略和私有账本。若收据版本是已识别的 local-v*-source.<完整SHA>，用 --replace-source 明确允许替换为候选包并在结果中说明。原安装不在标准目录时追加 --directory；首次安装需复用此 Project 已有的私有 task:sync 配置，以 --client-config 和 --host-config 传入绝对路径，DeepSeek 还需原 --dsh-home/--profile。仅在配置或旧路径确实缺失时问我，不新建凭据、申请 Operator key 或复制模型登录。",
    "按实际 Python、OS/架构选择已发布目标；缺 Python 时优先复用兼容环境或已有工具管理器，只在已授权范围内做用户级安装，不修改系统 Python。使用 --skills-directory 将包内接入指南安装到所选宿主的标准技能目录；自定义同名文件发生冲突时保留并报告。",
    "保留 token、CA、原产物、账本、未决 key 和其他宿主配置。UNKNOWN 只按原 key 查询，不重放 POST；首次不自动启用未核验 Hooks。升级后核对实际 daemon 的运行时版本和能力，报告实际版本、通道、本地诊断及仍需的宿主重载/信任操作。",
    "candidate 是候选发行，安装成功不代表真实宿主验收。旧 stable local-v0.1.0 缺少新绑定/协作能力，不可自动降级替代。新绑定及协作写入当前仅支持 Codex CLI 0.144.6 原生 caller。此安装范围不启动模型或 SUT 测试，也不创建或绑定平台任务。",
    command,
  ] : [
    `Install or upgrade HyperTest One Local for ${options.harness} on this machine using the ${options.channel} channel. ${target} Run the digest-pinned official updater below and finish local diagnostics; do not ask me to run several commands manually.`.trim(),
    "Read the owned receipt at ~/.local/share/hypertest-local/<host>/host-installation or my supplied legacy directory first; inspect only known receipts and referenced configuration. Preserve its authorization, Hooks, workspace policy and journals. For a recognized local-v*-source.<full-SHA> receipt add --replace-source to explicitly replace it with the candidate and report that replacement. Append --directory for a nonstandard legacy installation. A fresh install must reuse this Project's existing private task:sync profile via absolute --client-config and --host-config paths; DeepSeek also needs its existing --dsh-home/--profile. Ask only for genuinely missing configuration or legacy paths. Do not create credentials, request Operator keys or copy model logins.",
    "Select a published target matching the actual Python, OS and architecture. If Python is missing, reuse a compatible environment or existing tool manager; perform user-level installation only within existing authorization, without changing system Python. Use --skills-directory to install the bundled onboarding guide in the selected host's standard skills directory; preserve customized same-name files and report conflicts.",
    "Preserve tokens, CA files, artifacts, journals, pending keys and unrelated host settings. Reconcile UNKNOWN only by its original key; never replay a POST. Do not automatically enable unverified Hooks on a fresh install. Check the actual daemon runtime version and capabilities after updating; report the installed version, channel, diagnostics and remaining host reload/trust actions.",
    "Candidate installation is not native-host acceptance. Old stable local-v0.1.0 lacks new binding/collaboration capabilities; do not silently downgrade to it. New binding and collaboration writes currently require the native Codex CLI 0.144.6 caller. This setup does not start models or SUT tests, or create/bind platform tasks.",
    command,
  ];
  return instructions.join("\n\n");
}

/** Populate only after immutable assets exist at the selected public release. */
export type PublishedLocalTarget = {
  targetId: string;
  python: "3.12" | "3.13";
  releaseTag: string;
  sourceCommit: string;
  bootstrapSha256: string;
  manifestSha256: string;
  bundleSha256: string;
  hosts: Partial<Record<LocalHarness, { automaticTrigger: "ACCEPTED" | "NOT_ACCEPTED"; versions: string[] }>>;
};
export const LOCAL_PUBLISHED_TARGETS: PublishedLocalTarget[] = [{
  targetId: "darwin-arm64-py313", python: "3.13", releaseTag: "local-v0.1.0",
  sourceCommit: "874569fa566a137eba77ac4852caa6052cb04a17",
  bootstrapSha256: "cd8a2757e3019d6945f697dc1c8db8b650c2744a6e421bae5ba420b7ef25927a",
  manifestSha256: "ba132292c57c740f0409728e3aa23ce93ecde39b5fa40a6d435dad03fb4531da",
  bundleSha256: "e3c7ac8c5966e086c02e3d4b50abc8cd32787bc276d37c271c9949379255979f",
  hosts: {
    "claude-code": { automaticTrigger: "ACCEPTED", versions: ["2.1.218"] },
    codex: { automaticTrigger: "ACCEPTED", versions: ["0.144.6"] },
    "deepseek-harness": { automaticTrigger: "ACCEPTED", versions: ["0.1.5-rc.1"] },
  },
}];

export const LOCAL_PROVIDERS: Record<LocalHarness, string> = {
  codex: "codex", "claude-code": "claude_code", "deepseek-harness": "deepseek_harness",
};

type LocalInstallOptions = {
  projectId: string;
  harness: LocalHarness;
  directory: string;
  clientConfig: string;
  hostConfig?: string;
  dshHome?: string;
  profile?: string;
};

function assertContext(projectId: string, harness: LocalHarness) {
  if (!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(projectId)) throw new Error("project-id");
  if (!LOCAL_HARNESSES.includes(harness)) throw new Error("harness");
}

function privatePath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value !== value.trim() || value.length > 2048 || /[\u0000-\u001f\u007f]/.test(value)) throw new Error("absolute-path");
  return value;
}

/** POSIX quoting also preserves spaces, quotes, backticks and dollar signs. */
function quote(value: string): string {
  return "'" + value.replace(/'/g, "'\"'\"'") + "'";
}

export function buildLocalModeCommands(options: LocalInstallOptions) {
  const allowed = new Set(["projectId", "harness", "directory", "clientConfig", "hostConfig", "dshHome", "profile"]);
  if (Object.keys(options).some((key) => !allowed.has(key))) throw new Error("public-context-only");
  assertContext(options.projectId, options.harness);
  const directory = privatePath(options.directory);
  const clientConfig = privatePath(options.clientConfig);
  let hostConfig: string;
  const extra: string[] = [];
  if (options.harness === "deepseek-harness") {
    const home = privatePath(options.dshHome);
    if (!options.profile || !/^[A-Za-z0-9_-]+$/.test(options.profile)) throw new Error("profile");
    hostConfig = `${home.replace(/\/$/, "")}/profiles/${options.profile}/cordis.patch.yml`;
    if (options.hostConfig && options.hostConfig !== hostConfig) throw new Error("profile-target");
    extra.push("--dsh-home", quote(home), "--profile", quote(options.profile));
  } else {
    if (options.dshHome || options.profile) throw new Error("profile-target");
    hostConfig = privatePath(options.hostConfig);
  }
  if (hostConfig === clientConfig || directory === "/") throw new Error("distinct-private-paths");
  const python = ".venv-local/bin/python";
  const common = ["--directory", quote(directory), "--harness", options.harness];
  return {
    prepare: "python3 -m venv .venv-local\n.venv-local/bin/python -m pip install -e '.[interactive]'",
    install: [`# Project: ${options.projectId.toLowerCase()} — verify the existing private authorization.`,
      [python, "-m hypertest.local_sync install", ...common, "--host-config", quote(hostConfig),
        "--client-config", quote(clientConfig), "--version", LOCAL_CANDIDATE_VERSION, ...extra].join(" ")].join("\n"),
    doctor: [python, "-m hypertest.local_sync doctor", ...common].join(" "),
    daemon: [python, "-m hypertest.interactive_client daemon", "--config", quote(clientConfig)].join(" "),
    stopDaemon: [python, "-m hypertest.interactive_client stop", "--config", quote(clientConfig)].join(" "),
    submit: [python, "-m hypertest.local_sync submit-manifest", "--config", quote(clientConfig)].join(" "),
  };
}

/** The fixed digest is trusted application data; no digest is fetched beside code. */
export function buildPublishedLocalCommand(options: LocalInstallOptions, target: PublishedLocalTarget,
  automatic?: { workspace: string; hookConfig?: string; harnessVersion: string }): string {
  // Reuse all source-command path and identity validation before producing shell text.
  buildLocalModeCommands(options);
  if (!/^local-v\d+\.\d+\.\d+$/.test(target.releaseTag) || !/^[a-f0-9]{40}$/.test(target.sourceCommit)
    || ![target.bootstrapSha256, target.manifestSha256, target.bundleSha256].every((value) => /^[a-f0-9]{64}$/.test(value))
    || !["3.12", "3.13"].includes(target.python)
    || !/^(darwin|linux)-(arm64|x86_64)-py3(12|13)$/.test(target.targetId)
    || !target.targetId.endsWith(`py${target.python.replace(".", "")}`)) throw new Error("fixed-published-release");
  const base = `https://github.com/ZhangLiangchen/hypertest-one/releases/download/${target.releaseTag}`;
  const code = "import hashlib,sys,urllib.request; "
    + `r=urllib.request.urlopen('${base}/install-local-release.py',timeout=45); `
    + "u=urllib.parse.urlsplit(r.url); "
    + "(u.scheme=='https' and u.hostname in {'github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}) or sys.exit('BLOCKED: bootstrap redirect'); "
    + "b=r.read(1048577); r.close(); "
    + `(len(b)<=1048576 and hashlib.sha256(b).hexdigest()=='${target.bootstrapSha256}') or sys.exit('BLOCKED: bootstrap digest'); `
    + "exec(compile(b,'<verified HyperTest Local bootstrap>','exec'))";
  const args = [`python${target.python}`, "-I", "-c", quote(code), "--bundle-url", quote(`${base}/hypertest-${target.releaseTag}-${target.targetId}.zip`),
    "--trusted-bundle-sha256", target.bundleSha256, "--trusted-manifest-sha256", target.manifestSha256,
    "--source-commit", target.sourceCommit, "--release-tag", target.releaseTag, "--install-root", quote(privatePath(options.directory)),
    "--harness", options.harness, "--client-config", quote(privatePath(options.clientConfig))];
  if (options.harness === "deepseek-harness") {
    const home = privatePath(options.dshHome);
    args.push("--host-config", quote(`${home.replace(/\/$/, "")}/profiles/${options.profile}/cordis.patch.yml`),
      "--dsh-home", quote(home), "--profile", quote(options.profile!));
  } else args.push("--host-config", quote(privatePath(options.hostConfig)));
  if (automatic) {
    const accepted = target.hosts[options.harness];
    if (accepted?.automaticTrigger !== "ACCEPTED" || !accepted.versions.includes(automatic.harnessVersion)) throw new Error("accepted-hooks-required");
    args.push("--enable-hooks", "--workspace", quote(privatePath(automatic.workspace)), "--harness-version", quote(automatic.harnessVersion));
    if (options.harness === "deepseek-harness") args.push("--event-bridge", "native-root");
    else args.push("--hook-config", quote(privatePath(automatic.hookConfig)));
  }
  return args.join(" ");
}

/** Deliberately incomplete: real parent identity, version and artifact digest are required. */
export function localManifestTemplate(projectId: string, harness: LocalHarness): string {
  assertContext(projectId, harness);
  return JSON.stringify({
    profile: "hypertest.local-manifest/v1alpha1",
    identity: { project_id: projectId.toLowerCase(), provider: LOCAL_PROVIDERS[harness], parent_session_id: "<ACTUAL_PARENT_SESSION_ID_FROM_HOST>" },
    base_version: "<VERSION_FROM_COMPLETE_READBACK_OR_0_FOR_NEW_SOURCE>",
    set: { title: "<ACTUAL_TEST_TASK_TITLE>", objective: "<AUTHORIZED_TEST_OBJECTIVE>", status: "IN_PROGRESS", reported_result: "NOT_RUN" },
    clear: [],
    artifacts: [{ kind: "TEST_PLAN", path: "/absolute/private/approved-artifacts/plan.md", sha256: "<SHA256_OF_APPROVED_PLAN_FILE>" }],
  }, null, 2);
}

export function localConfigTemplate(projectId: string, harness: LocalHarness): string {
  assertContext(projectId, harness);
  return JSON.stringify({ local_sync: {
    enabled: true, host: harness, hooks_enabled: false, project_id: projectId.toLowerCase(),
    manifest_file: "/absolute/private/hypertest-local/manifest.json", allowed_roots: ["/absolute/private/approved-artifacts"],
  } }, null, 2);
}
