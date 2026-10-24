"use client";

import { ArrowRightOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Form, Input, Popconfirm, Radio, Space, Steps, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { createRun, errorText, getConfigurationContent, getExecutionEnvironments, getPolicySnapshot, getPrdContent, getRun, getSourceSnapshot, resolveSource } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";
import { EnvironmentFields, EnvironmentRequestSummary } from "@/app/execution-environment";
import { buildEnvironmentRequest, canUseEnvironment, defaultEnvironmentValues, environmentInputIssue, runInputSignature, selectedEnvironmentProfile } from "@/lib/execution-environment";
import type { EnvironmentFormValues } from "@/lib/execution-environment";
import { useI18n } from "@/lib/i18n";
import { decodePrdBytes, MAX_PRD_CHARACTERS } from "@/lib/prd-import";
import type { PrdDecodeError } from "@/lib/prd-import";
import { createUuid } from "@/lib/uuid";
import { loadRunDraft, RunDraftError } from "@/lib/run-draft";
import type { CopiedRunDraft } from "@/lib/run-draft";
import type { Project, RunCreate, SourceResolution } from "@/lib/types";
import { compileFormPolicy, defaultPolicyValues, PolicyFields, PolicyReview } from "./policy-fields";
import type { PolicyFormValues } from "./policy-fields";
import { HarnessFields } from "./harness-fields";

type RunFormValues = PolicyFormValues & EnvironmentFormValues & {
  harness_mode?: "SERVER_HOST" | "LOCAL_CONNECTOR";
  harness_node_id?: string;
  source_bundle_transfer_id?: string;
  repository_url: string;
  source_mode: "revision" | "sha";
  revision: string;
  commit_sha: string;
  branch?: string;
  prd_text: string;
  configuration_text: string;
  policy_mode: "edit" | "reuse";
};

type SourceLookup = { repository_url: string; revision: string; generation: number };

function supportsSourceResolution(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return /^https:\/\/github\.com\//i.test(value.trim()) && url.protocol === "https:" && url.hostname === "github.com" && !url.port
      && !url.username && !url.password && !url.search && !url.hash
      && /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/.test(url.pathname);
  } catch { return false; }
}

type ImportError = "type" | "size" | PrdDecodeError | "read";
const MAX_CONFIGURATION_CHARACTERS = 100_000;
const MAX_PRD_FILE_BYTES = 8 * 1024 * 1024;
const MAX_REQUEST_BYTES = 10 * 1024 * 1024;

function buildRunInput(values: RunFormValues, copied: CopiedRunDraft | null): Omit<RunCreate, "idempotency_key"> {
  return {
    ...(values.harness_mode === "LOCAL_CONNECTOR" ? { harness_mode: values.harness_mode,
      harness_node_id: values.harness_node_id, source_bundle_transfer_id: values.source_bundle_transfer_id } : {}),
    repository_url: values.repository_url.trim(),
    commit_sha: values.commit_sha.trim().toLowerCase(),
    branch: values.branch?.trim() || undefined,
    prd_text: values.prd_text,
    configuration_text: values.configuration_text,
    policy: values.policy_mode === "reuse" && copied ? copied.policy.compiled_policy : compileFormPolicy(values),
    environment: buildEnvironmentRequest(values),
  };
}

type RunCreateDialogProps = {
  project: Project;
  fromRun: string | null;
  createOpen: boolean;
  setCreateOpen: (open: boolean) => void;
  onDraftChange: (hasDraft: boolean) => void;
};

// The project page mounts this module only after opening creation or following a
// fromRun link. Keep it mounted after closing to preserve form, step and request key.
export default function RunCreateDialog({ project, fromRun, createOpen, setCreateOpen, onDraftChange }: RunCreateDialogProps) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [hasDraft, setHasDraft] = useState(false);
  const submitting = useRef(false);
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<RunFormValues>({
    repository_url: "", source_mode: "revision", revision: "main", commit_sha: "", branch: "main", prd_text: "", configuration_text: "{}", policy_mode: "edit",
    ...defaultPolicyValues(),
    ...defaultEnvironmentValues(),
  });
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<ImportError | null>(null);
  const [importedFileName, setImportedFileName] = useState("");
  const [requestTooLarge, setRequestTooLarge] = useState(false);
  const [copied, setCopied] = useState<CopiedRunDraft | null>(null);
  const [resolvedSource, setResolvedSource] = useState<SourceResolution | null>(null);
  const [sourceLookupError, setSourceLookupError] = useState<unknown>(null);
  const lookupGeneration = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const draftProjectId = useRef<string | null>(null);
  const requestIdentity = useRef<{ signature: string; key: string } | null>(null);
  const [form] = Form.useForm<RunFormValues>();
  const sourceMode = Form.useWatch("source_mode", { form, preserve: true }) || "revision";
  const localHarness = Form.useWatch("harness_mode", { form, preserve: true }) === "LOCAL_CONNECTOR";
  const repositoryOrigin = Form.useWatch("repository_url", { form, preserve: true }) || "";
  const environmentProfile = Form.useWatch("environment_profile_id", { form, preserve: true }) || "python-pytest-v1";
  const policyMode = Form.useWatch("policy_mode", { form, preserve: true }) || "edit";
  const previousInputs = useQuery({
    queryKey: ["copy-run-inputs", project.id, fromRun],
    queryFn: () => loadRunDraft(project.id, fromRun!, {
      run: getRun, source: getSourceSnapshot, policy: getPolicySnapshot,
      prd: getPrdContent, configuration: getConfigurationContent,
    }),
    enabled: Boolean(fromRun), retry: false,
  });
  const environments = useQuery({ queryKey: ["execution-environments"], queryFn: getExecutionEnvironments, enabled: createOpen, retry: false });
  const environmentAvailable = canUseEnvironment(environments.data, environmentProfile, environments.isError);
  const sourceResolver = useMutation({
    mutationFn: ({ repository_url, revision }: SourceLookup) => resolveSource({ repository_url, revision }),
    onSuccess: (result, request) => {
      if (request.generation !== lookupGeneration.current || form.getFieldValue("source_mode") !== "revision") return;
      setResolvedSource(result);
      setSourceLookupError(null);
      if (creation.isError) creation.reset();
      form.setFieldsValue({ repository_url: result.repository_url, revision: result.revision, commit_sha: result.commit_sha, branch: result.revision });
      form.setFields([{ name: "commit_sha", errors: [] }]);
    },
    onError: (error, request) => {
      if (request.generation === lookupGeneration.current) setSourceLookupError(error);
    },
  });

  const resolveRevision = async () => {
    try {
      await form.validateFields(["repository_url", "revision"]);
      if (form.getFieldValue("source_mode") !== "revision") return;
      const repository_url = String(form.getFieldValue("repository_url")).trim();
      const revision = String(form.getFieldValue("revision")).trim();
      const generation = ++lookupGeneration.current;
      setResolvedSource(null);
      setSourceLookupError(null);
      form.setFieldValue("commit_sha", "");
      sourceResolver.mutate({ repository_url, revision, generation });
    } catch {
      const firstInvalid = form.getFieldsError().find((field) => field.errors.length);
      if (firstInvalid) form.scrollToField(firstInvalid.name, { focus: true });
    }
  };
  useEffect(() => {
    if (!createOpen) return;
    const invalid = form.getFieldsError().filter((field) => field.errors.length).map((field) => field.name);
    if (invalid.length) void form.validateFields(invalid, { recursive: true }).catch(() => undefined);
  }, [locale, form, createOpen]);
  const creation = useMutation({
    mutationFn: (payload: RunCreate) => createRun(project.id, payload),
    onSuccess: (run) => {
      queryClient.setQueryData(["run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["project-runs", project.id] });
      router.push(`/runs/${run.id}`);
    },
    onSettled: () => { submitting.current = false; },
  });

  const openCreate = () => {
    if (!hasDraft || draftProjectId.current !== project.id) {
      const initialValues: RunFormValues = {
        repository_url: project.repository_url || "",
        source_mode: !project.repository_url || supportsSourceResolution(project.repository_url) ? "revision" : "sha",
        revision: project.default_branch || "main",
        commit_sha: "",
        branch: project.default_branch || "main",
        prd_text: "",
        configuration_text: "{}",
        policy_mode: "edit",
        ...defaultPolicyValues(),
        ...defaultEnvironmentValues(),
      };
      form.resetFields();
      form.setFieldsValue(initialValues);
      setDraft(initialValues);
      setCopied(null);
      creation.reset();
      requestIdentity.current = null;
      lookupGeneration.current += 1;
      setResolvedSource(null);
      setSourceLookupError(null);
      sourceResolver.reset();
      draftProjectId.current = project.id;
      setImportedFileName("");
      setImportError(null);
      setRequestTooLarge(false);
      setStep(0);
      setHasDraft(true);
    }
    setCreateOpen(true);
  };

  const copyPreviousInputs = () => {
    const previous = previousInputs.data;
    if (!previous || importing || submitting.current || creation.isPending || creation.isSuccess) return;
    const initialValues: RunFormValues = {
      repository_url: previous.source.repository_url, source_mode: "sha",
      revision: previous.source.branch || project.default_branch || "main",
      commit_sha: previous.source.commit_sha, branch: previous.source.branch || "",
      prd_text: previous.prd, configuration_text: previous.configuration,
      ...defaultPolicyValues(), ...previous.environment, policy_mode: "reuse",
    };
    form.resetFields();
    form.setFieldsValue(initialValues);
    setDraft(initialValues);
    setCopied(previous);
    setHasDraft(true);
    draftProjectId.current = project.id;
    requestIdentity.current = null;
    lookupGeneration.current += 1;
    setResolvedSource(null);
    setSourceLookupError(null);
    sourceResolver.reset();
    creation.reset();
    setImportedFileName("");
    setImportError(null);
    setRequestTooLarge(false);
    setStep(0);
    setCreateOpen(true);
  };

  const submitStep = () => {
    if (submitting.current || creation.isPending || creation.isSuccess || importing) return;
    const values = form.getFieldsValue(true) as RunFormValues;
    setDraft(values);
    if (step >= 2 && (!canUseEnvironment(environments.data, values.environment_profile_id, environments.isError) || environmentInputIssue(values))) {
      setStep(2);
      return;
    }
    if (step < 4) {
      setStep(step + 1);
      return;
    }
    const input = buildRunInput(values, copied);
    // Reference labels do not change the canonical SourceSnapshot identity.
    const signature = runInputSignature(project.id, input);
    // Retry identical inputs with the same key. Edited inputs must never reopen an older run.
    if (requestIdentity.current?.signature !== signature) {
      requestIdentity.current = { signature, key: `web:${createUuid()}` };
    }
    const payload = { ...input, idempotency_key: requestIdentity.current.key };
    if (new TextEncoder().encode(JSON.stringify(payload)).length > MAX_REQUEST_BYTES) {
      setRequestTooLarge(true);
      setStep(1);
      return;
    }
    setRequestTooLarge(false);
    submitting.current = true;
    creation.mutate(payload);
  };

  const previousStep = () => {
    setDraft(form.getFieldsValue(true) as RunFormValues);
    setStep(step - 1);
  };

  const importPrd = async (file: File) => {
    setImportError(null);
    if (!/\.(md|txt)$/i.test(file.name)) { setImportError("type"); return; }
    if (file.size > MAX_PRD_FILE_BYTES) { setImportError("size"); return; }
    setImporting(true);
    try {
      const bytes = await file.arrayBuffer();
      const decoded = decodePrdBytes(bytes);
      if (!decoded.ok) { setImportError(decoded.error); return; }
      form.setFieldsValue({ prd_text: decoded.text });
      form.setFields([{ name: "prd_text", errors: [] }]);
      setImportedFileName(file.name);
      setRequestTooLarge(false);
      if (creation.isError) creation.reset();
    } catch {
      setImportError("read");
    } finally {
      setImporting(false);
    }
  };

  const importErrorMessage = importError === "type" ? t("Choose a Markdown (.md) or plain text (.txt) file.", "请选择 Markdown（.md）或纯文本（.txt）文件。")
    : importError === "size" ? t("The file exceeds 8 MiB. Use a smaller UTF-8 text file or paste a shorter requirements document.", "文件超过 8 MiB，请选择较小的 UTF-8 文本文件，或粘贴精简后的需求。")
    : importError === "encoding" ? t("This is not a valid UTF-8 text file. Save it as UTF-8 and try again.", "文件不是有效的 UTF-8 纯文本。请另存为 UTF-8 编码后重试。")
    : importError === "length" ? t("Requirements exceed 2,000,000 characters. Shorten the document before importing.", "需求超过 2,000,000 个字符，请精简后再导入。")
    : importError === "empty" ? t("The file contains no requirements text. Choose a non-empty UTF-8 file or enter requirements below. Your current draft is preserved.", "文件没有需求正文，请选择非空 UTF-8 文件或在下方填写需求。当前草稿已保留。")
    : t("Unable to read the file. Choose it again or paste its contents below.", "无法读取文件，请重新选择，或直接粘贴下方文本。");

  useEffect(() => {
    if (createOpen && !hasDraft) openCreate();
  }, [createOpen, hasDraft]);
  useEffect(() => { onDraftChange(hasDraft); }, [hasDraft, onDraftChange]);

  const copyError = previousInputs.error instanceof RunDraftError
    ? previousInputs.error.code === "project" ? t("This run belongs to a different project. Open its project to create the next round.", "此运行属于其他项目，请在原项目中创建新轮次。")
      : previousInputs.error.code === "environment" ? t("The previous run uses an unbound or archived environment. Create a fresh draft and explicitly configure a supported environment.", "原运行没有绑定受控环境，或使用已归档环境。请新建草稿并明确配置当前支持的执行环境。")
      : t("The previous run or its snapshots could not be verified. Your current draft is preserved.", "无法核验原运行及其快照，当前草稿已保留。")
    : errorText(previousInputs.error, locale);

  return (
    <>
      {fromRun ? <Alert
        className="copy-run-notice"
        type={previousInputs.isError ? "error" : "info"} showIcon
        message={t("Create a new round from saved inputs", "沿用已保存输入创建新轮次")}
        description={previousInputs.isPending ? t("Loading and verifying the saved inputs…", "正在读取并核验已保存输入…") : previousInputs.isError ? copyError : <>{t("Requirements, context and the full policy can be reused. Review the pinned SHA, choose a repaired version if needed, and confirm the environment. The previous run and results remain in history.", "可沿用需求、上下文和完整策略。请核对固定 SHA，需要时选择修复版本，并确认执行环境；原运行和结果保留在历史中。")}{previousInputs.data ? <><br /><Link href={`/runs/${previousInputs.data.run.id}`}>{previousInputs.data.run.key}</Link></> : null}</>}
        action={previousInputs.isError ? <Button onClick={() => void previousInputs.refetch()} loading={previousInputs.isFetching || importing || creation.isPending || creation.isSuccess}>{t("Retry loading inputs", "重试读取输入")}</Button>
          : hasDraft ? <Popconfirm title={t("Replace the current draft with the saved inputs?", "用已保存输入替换当前草稿？")} description={t("Only the draft on this page will be replaced.", "只会替换当前页面的草稿。")} onConfirm={copyPreviousInputs} okText={t("Replace draft", "替换草稿")} cancelText={t("Keep draft", "保留草稿")}><Button disabled={!previousInputs.data || previousInputs.isFetching || importing || creation.isPending || creation.isSuccess}>{t("Use saved inputs", "沿用已保存输入")}</Button></Popconfirm>
            : <Button onClick={copyPreviousInputs} disabled={!previousInputs.data || previousInputs.isFetching || importing || creation.isPending || creation.isSuccess}>{t("Review copied inputs", "核对沿用的输入")}</Button>}
        style={{ marginBottom: 20 }}
      /> : null}

      <Modal
        title={t("Create test run", "创建测试运行")}
        open={createOpen}
        forceRender
        onCancel={() => { if (!importing) setCreateOpen(false); }}
        footer={null}
        width={760}
        closable={!creation.isPending && !importing}
        maskClosable={!creation.isPending && !importing}
        keyboard={!creation.isPending && !importing}
      >
        <Steps
          current={step}
          size="small"
          items={[{ title: t("Source", "源码") }, { title: t("Requirements", "需求") }, { title: t("Environment", "执行环境") }, { title: t("Policy", "策略") }, { title: t("Review", "确认") }]}
          style={{ margin: "24px 0" }}
        />
        {copied ? <Alert type="info" showIcon message={t("New round with copied inputs", "使用原输入的新轮次")} description={<>{t("Original run: ", "原运行：")}<Link href={`/runs/${copied.run.id}`}>{copied.run.key}</Link>{t(". The original SHA is prefilled. Keep it for an explicit retest, or choose the repaired SHA in Source. Current trusted images are resolved again when you create the run.", "。已预填原 SHA；可保留以显式复测，或在源码步骤选择修复 SHA。创建时将重新核验当前可信镜像。")}</>} style={{ marginBottom: 20 }} /> : null}
        {creation.isError ? (
          <Alert type="error" showIcon message={t("Test run could not be created", "测试运行创建失败")} description={errorText(creation.error, locale)} style={{ marginBottom: 20 }} />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message={t("Test run created. Opening the workbench…", "测试运行已创建，正在打开工作台…")} description={<Link href={`/runs/${creation.data.id}`}>{t("Open test run", "打开测试运行")}</Link>} style={{ marginBottom: 20 }} />
        ) : null}
        {requestTooLarge ? (
          <Alert type="error" showIcon message={t("The inputs exceed the 10 MiB request limit.", "输入超出 10 MiB 请求上限。")} description={t("Shorten the requirements or configuration, then review and submit again. Your draft is preserved.", "请精简需求或测试配置，再确认提交。当前草稿已保留。")} style={{ marginBottom: 20 }} />
        ) : null}
        {step >= 3 && !environmentAvailable && <Alert type="warning" showIcon message={t("Review environment availability before continuing", "请先核对环境可用性再继续")} description={t("The selected image is unavailable or its catalog could not be refreshed. Your draft is preserved.", "所选镜像不可用，或环境目录未能刷新。当前草稿已保留。") } action={<Button onClick={() => { setDraft(form.getFieldsValue(true) as RunFormValues); setStep(2); }}>{t("Review environment", "核对环境")}</Button>} style={{ marginBottom: 20 }} />}
        <Form
          name="create-test-run"
          form={form}
          layout="vertical"
          preserve
          disabled={creation.isPending || creation.isSuccess || importing}
          requiredMark="optional"
          onFinish={submitStep}
          onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}
          onValuesChange={(changed: Partial<RunFormValues>) => {
            if (creation.isError) creation.reset();
            setRequestTooLarge(false);
            if ("repository_url" in changed || "revision" in changed || "source_mode" in changed) {
              lookupGeneration.current += 1;
              setResolvedSource(null);
              setSourceLookupError(null);
              sourceResolver.reset();
              if (form.getFieldValue("source_mode") === "revision") form.setFields([{ name: "commit_sha", value: "", errors: [] }]);
            }
          }}
        >
          {step === 0 ? (
            <>
              <HarnessFields form={form} projectId={project.id} />
              <Typography.Paragraph className="muted">
                {t("Choose the repository origin and exact version to test. Resolve a branch or tag to a fixed commit, or enter the full SHA yourself.", "填写仓库源地址及需要测试的版本。可以将分支或标签解析为固定提交，也可以手工输入完整 SHA。")}
              </Typography.Paragraph>
              {!localHarness && <Alert
                type="info"
                showIcon
                message={t("Origin address and checkout folder are different", "仓库源地址与检出目录不同")}
                description={<>{t("Use the origin address reported by ", "请填写以下命令输出的 origin 地址：")}<Typography.Text code copyable>git remote get-url origin</Typography.Text>{t(". Do not enter an arbitrary checkout directory here. A local Git source path is supported only when it is the origin value itself. Choose an existing Worker checkout directory after run creation; a browser-computer path does not upload source to the server.", "。此处不能用任意 Git 检出目录替代源地址。本地 Git 源路径只有与 origin 输出本身一致时才有效。已有 Worker 检出目录将在创建运行后选择；填写浏览器电脑上的路径不会把源码上传到服务器。")}</>}
                style={{ marginBottom: 20 }}
              />}
              <Form.Item
                name="repository_url"
                label={t("Repository origin", "仓库源地址（origin）")}
                normalize={(value: string) => value.trim()}
                extra={localHarness ? t("Use the credential-free origin accessible to the selected device. Enter the full SHA, then authorize and receive the pinned source.", "填写所选设备可访问的不含凭据的仓库地址。输入完整 SHA 后，点击授权并接收源码。") : t("GitHub HTTPS sources without embedded credentials support reference resolution and managed checkout. Other Git origins use a manual SHA and a matching checkout on the Worker host.", "不含内嵌凭据的 GitHub HTTPS 源支持版本解析及托管检出。其他 Git 源需手工输入 SHA，并在 Worker 主机提供匹配的检出。")}
                rules={[
                  { required: true, whitespace: true, message: t("Enter the repository's origin address.", "请输入仓库的 origin 源地址。") },
                  { max: 2048, message: t("Use at most 2,048 characters.", "最多输入 2,048 个字符。") },
                ]}
              >
                <Input placeholder="https://github.com/your-team/your-repository" maxLength={2048} />
              </Form.Item>
              <Form.Item name="source_mode" label={t("Choose a version", "选择源码版本")}>
                <Radio.Group options={[{ value: "revision", label: t("Resolve branch or tag", "解析分支或标签") }, { value: "sha", label: t("Enter full commit SHA", "手工输入完整 SHA") }]} />
              </Form.Item>
              {sourceMode === "revision" ? <>
                <Form.Item
                  name="revision"
                  label={t("Branch, tag or full SHA", "分支、标签或完整 SHA")}
                  normalize={(value: string) => value.trim()}
                  rules={[{ required: true, whitespace: true, message: t("Enter a branch, tag or full commit SHA to resolve.", "请输入需要解析的分支、标签或完整提交 SHA。") }]}
                >
                  <Input placeholder={project.default_branch || "main"} autoComplete="off" />
                </Form.Item>
                {repositoryOrigin && !supportsSourceResolution(repositoryOrigin) ? <Alert type="info" showIcon message={t("Use manual SHA for this Git origin", "此 Git 源请使用手工 SHA 模式")} description={t("Reference resolution supports credential-free HTTPS github.com/owner/repository URLs. For another host, SSH origin or local Git origin, enter its full commit SHA and provide a matching Worker checkout later.", "版本解析仅支持不含凭据的 HTTPS github.com/组织/仓库 地址。其他主机、SSH 源或本地 Git 源，请手工输入完整提交 SHA，并在后续提供匹配的 Worker 检出。")} style={{ marginBottom: 16 }} /> : null}
                <Button loading={sourceResolver.isPending} disabled={!supportsSourceResolution(repositoryOrigin)} onClick={() => void resolveRevision()} style={{ marginBottom: 16 }}>{t("Resolve and pin commit", "解析并固定提交")}</Button>
                {sourceLookupError ? <Alert type="error" showIcon message={t("Unable to resolve the source version", "无法解析源码版本")} description={<>{errorText(sourceLookupError, locale)} {t("Check the origin and reference, then retry; you can also use manual SHA.", "请检查源地址和参考版本后重试，也可以切换为手工 SHA。")}</>} style={{ marginBottom: 16 }} /> : null}
                {resolvedSource ? <Alert type="success" showIcon message={t("Source commit pinned", "已固定源码提交")} description={<Space direction="vertical" size={4}><Typography.Text>{t("Resolved reference: ", "解析版本：")}{resolvedSource.revision}</Typography.Text><Typography.Text code copyable style={{ overflowWrap: "anywhere" }}>{resolvedSource.commit_sha}</Typography.Text><Typography.Text>{t("The run will keep this commit even if the branch or tag moves. Editing the origin or reference requires resolving again.", "分支或标签后续移动不会改变本次运行的固定提交。修改源地址或参考版本后，需要重新解析。")}</Typography.Text></Space>} style={{ marginBottom: 16 }} /> : null}
              </> : null}
              <Form.Item
                name="commit_sha"
                label={sourceMode === "revision" ? t("Pinned commit SHA", "固定提交 SHA") : t("Full commit SHA", "完整提交 SHA")}
                normalize={(value: string) => value.trim().toLowerCase()}
                extra={sourceMode === "revision" ? t("Filled by resolution. No branch or tag name is submitted as the tested commit.", "解析成功后自动填入；正式测试使用完整 SHA，不会用分支或标签名替代提交。") : <>{t("Paste the full 40- or 64-character commit SHA. In your matching checkout, run: ", "粘贴完整的 40 位或 64 位提交 SHA。在匹配的 Git 检出中执行：")}<Typography.Text code copyable>git rev-parse HEAD</Typography.Text></>}
                rules={[
                  { required: true, message: sourceMode === "revision" ? t("Resolve the selected source version first.", "请先解析所选源码版本。") : t("Enter the full commit SHA.", "请输入完整提交 SHA。") },
                  { pattern: /^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/, message: t("Enter a full 40-character or 64-character hexadecimal commit SHA.", "请输入完整的 40 位或 64 位十六进制提交 SHA。") },
                  { validator: async (_, value: string) => {
                    if (form.getFieldValue("source_mode") === "revision" && (!resolvedSource || resolvedSource.commit_sha !== value)) throw new Error(t("Resolve the current origin and reference before continuing, or use manual SHA.", "请先解析当前源地址和参考版本，再继续；也可以切换为手工 SHA。"));
                  } },
                ]}
              >
                <Input readOnly={sourceMode === "revision"} placeholder={sourceMode === "revision" ? t("Resolve a version to fill the commit SHA", "解析版本后填入固定 SHA") : t("Full commit SHA", "完整提交 SHA")} autoComplete="off" style={{ fontFamily: "monospace" }} />
              </Form.Item>
              {sourceMode === "sha" ? <Form.Item name="branch" label={t("Reference label", "参考版本标签")} extra={t("Optional label for a branch or tag. The full commit SHA fixes the tested version.", "可选的分支或标签说明；实际测试版本以完整提交 SHA 为准。")}>
                <Input placeholder={project.default_branch} />
              </Form.Item> : null}
            </>
          ) : step === 1 ? (
            <>
              <Typography.Paragraph className="muted">
                {t("Provide the product requirements for this run. HyperTest uses them to identify requirements, analyze risks and design tests. Your original text is preserved.", "提供本轮产品需求，用于提取需求、分析风险并设计测试。需求正文按原文保存。")}
              </Typography.Paragraph>
              <Space direction="vertical" size={8} style={{ width: "100%", marginBottom: 18 }}>
                <input
                  ref={fileInput}
                  type="file"
                  accept=".md,.txt,text/plain,text/markdown"
                  style={{ display: "none" }}
                  aria-label={t("Import a requirements text file", "导入需求文本文件")}
                  disabled={creation.isPending || creation.isSuccess || importing}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void importPrd(file);
                  }}
                />
                <Button icon={<UploadOutlined aria-hidden />} loading={importing} onClick={() => fileInput.current?.click()}>{t("Import .md / .txt", "导入 .md / .txt")}</Button>
                <Typography.Text className="muted">{t("UTF-8 text, up to 8 MiB and 2,000,000 characters. Import replaces the text below; you can edit it before submitting.", "支持 UTF-8 文本，最多 8 MiB、2,000,000 个字符。导入会替换下方正文，提交前仍可编辑。")}</Typography.Text>
                {importedFileName ? <Typography.Text>{t("Imported file: ", "已导入文件：")}{importedFileName}{t(" (current text remains editable)", "（正文仍可编辑）")}</Typography.Text> : null}
                {importError ? <Alert type="error" showIcon message={t("File was not imported", "文件未导入")} description={importErrorMessage} /> : null}
              </Space>
              <Form.Item
                name="prd_text"
                label={t("Product requirements (PRD)", "产品需求（PRD）")}
                rules={[
                  { required: true, whitespace: true, message: t("Add the requirements to test.", "请填写需要测试的产品需求。") },
                  { max: MAX_PRD_CHARACTERS, message: t("Requirements must contain at most 2,000,000 characters.", "产品需求最多 2,000,000 个字符。") },
                ]}
              >
                <Input.TextArea rows={9} showCount maxLength={MAX_PRD_CHARACTERS} placeholder={t("Describe expected behavior, constraints, acceptance criteria and important edge cases…", "描述预期行为、约束、验收标准与重要边界情况…")} />
              </Form.Item>
              <Form.Item
                name="configuration_text"
                label={t("Testing context (optional)", "测试上下文（可选）")}
                extra={t("Original text or JSON, up to 100,000 characters, saved unchanged. It does not install dependencies or configure services; choose the controlled environment in the next step. Blank context is saved as empty text.", "原始文字或 JSON，最多 100,000 个字符，原样保存。此文字不会安装依赖或配置服务；受控执行环境请在下一步选择。留空按空文本保存。")}
                rules={[{ max: MAX_CONFIGURATION_CHARACTERS, message: t("Configuration must contain at most 100,000 characters.", "测试配置最多 100,000 个字符。") }]}
              >
                <Input.TextArea rows={4} showCount maxLength={MAX_CONFIGURATION_CHARACTERS} placeholder="{}" style={{ fontFamily: "monospace" }} />
              </Form.Item>
            </>
          ) : step === 2 ? <EnvironmentFields catalog={environments.data} loading={environments.isPending} failed={environments.isError} refreshing={environments.isFetching} refresh={() => void environments.refetch()} /> : step === 3 ? <>
            {copied ? <Form.Item name="policy_mode" label={t("Policy for this round", "本轮使用的策略")}><Radio.Group options={[{ value: "reuse", label: t("Keep the full original policy", "沿用完整原策略") }, { value: "edit", label: t("Replace with a new Web policy", "重新配置并替换策略") }]} /></Form.Item> : null}
            {copied && policyMode === "reuse" ? <><Typography.Paragraph>{t("Every original policy field is preserved, including rules outside this form. Select replacement only if you intend to configure a different policy.", "保留原策略的全部字段，包括此表单未覆盖的规则。需要修改策略时，请明确选择重新配置。")}</Typography.Paragraph><pre className="artifact-content">{JSON.stringify(copied.policy.compiled_policy, null, 2)}</pre></> : <PolicyFields />}
          </> : (
            <Space direction="vertical" size={18} style={{ width: "100%", marginBottom: 24 }}>
              <Alert
                type="info"
                showIcon
                message={t("Ready to create your test run", "确认并创建测试运行")}
                description={t("These inputs will be fixed in immutable source and policy snapshots. After creation, start the testing workflow from the workbench. Changed inputs require a new run.", "输入将固定为不可变源码与策略快照。创建后，请在工作台启动测试流程；需要更换输入时应创建新的运行。")}
              />
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label={t("Project", "项目")}>{project.name}</Descriptions.Item>
                <Descriptions.Item label={t("Repository origin", "仓库源地址")}><span style={{ overflowWrap: "anywhere" }}>{draft.repository_url}</span></Descriptions.Item>
                <Descriptions.Item label={t("Commit", "提交")}><Typography.Text code copyable style={{ overflowWrap: "anywhere", wordBreak: "break-all" }}>{draft.commit_sha}</Typography.Text></Descriptions.Item>
                <Descriptions.Item label={t("Reference label", "参考版本标签")}>{draft.branch?.trim() || t("Not specified", "未指定")}</Descriptions.Item>
                <Descriptions.Item label={t("Policy", "策略")}>{copied && draft.policy_mode === "reuse" ? <><Typography.Text>{t("Full original policy preserved", "沿用完整原策略")}</Typography.Text><pre className="artifact-content">{JSON.stringify(copied.policy.compiled_policy, null, 2)}</pre></> : <PolicyReview values={draft} />}</Descriptions.Item>
                <Descriptions.Item label={t("Execution environment", "执行环境")}><EnvironmentRequestSummary request={buildEnvironmentRequest(draft)} profile={selectedEnvironmentProfile(environments.data, draft.environment_profile_id)} /></Descriptions.Item>
              </Descriptions>
              <div style={{ width: "100%" }}>
                <Typography.Title level={5} style={{ marginTop: 0 }}>{t("Product requirements", "产品需求")}</Typography.Title>
                {importedFileName ? <Typography.Paragraph className="muted">{t("Imported from: ", "导入来源：")}{importedFileName}{t(" · Text shown below is the submitted content.", " · 以下正文为实际提交内容。")}</Typography.Paragraph> : null}
                <div className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 220, overflowY: "auto", padding: 12, borderRadius: 6 }}>{draft.prd_text}</div>
              </div>
              <details style={{ width: "100%" }}>
                <summary style={{ cursor: "pointer" }}>{t("Original testing context", "原始测试上下文")}</summary>
                <pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 180, overflowY: "auto" }}>{draft.configuration_text}</pre>
              </details>
            </Space>
          )}
          <Typography.Paragraph className="muted">{t("Closing keeps your draft while you stay on this page.", "关闭窗口会保留当前页面内的草稿。")}</Typography.Paragraph>
          <Space wrap style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
            <Button onClick={() => setCreateOpen(false)}>{t("Close", "关闭")}</Button>
            <Space>
              {step > 0 ? <Button onClick={previousStep}>{t("Back", "上一步")}</Button> : null}
              <Button
                type="primary"
                htmlType="submit"
                aria-label={step < 4 ? t("Continue to next step", "继续下一步") : t("Create test run", "创建测试运行")}
                loading={creation.isPending || creation.isSuccess}
                disabled={(step === 0 && sourceMode === "revision" && sourceResolver.isPending) || (step >= 2 && !environmentAvailable)}
              >
                {step < 4 ? <>{t("Continue", "下一步")} <ArrowRightOutlined aria-hidden /></> : t("Create test run", "创建测试运行")}
              </Button>
            </Space>
          </Space>
        </Form>
      </Modal>
    </>
  );
}
