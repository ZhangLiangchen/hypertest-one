/** Source-candidate setup only. No published Local bootstrap exists yet. */
export const LOCAL_CANDIDATE_VERSION = "local-v0.1.0-candidate";
export const LOCAL_RELEASE_STATE = "UNPUBLISHED_SOURCE_CANDIDATE";
export const LOCAL_HARNESSES = ["codex", "claude-code", "deepseek-harness"] as const;
export type LocalHarness = (typeof LOCAL_HARNESSES)[number];

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
export const LOCAL_PUBLISHED_TARGETS: PublishedLocalTarget[] = [];

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
