"use client";

import { ArrowLeftOutlined, ArrowRightOutlined, BranchesOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Empty, Form, Input, Row, Space, Spin, Steps, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { createRun, errorText, getProject, getProjectRuns } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";
import { useI18n } from "@/lib/i18n";
import type { RunCreate } from "@/lib/types";
import { compileFormPolicy, defaultPolicyValues, PolicyFields, PolicyReview } from "./policy-fields";
import type { PolicyFormValues } from "./policy-fields";

type RunFormValues = PolicyFormValues & {
  repository_url: string;
  commit_sha: string;
  branch?: string;
  prd_text: string;
  configuration_text: string;
};

type ImportError = "type" | "size" | "encoding" | "length" | "read";
const MAX_PRD_CHARACTERS = 2_000_000;
const MAX_CONFIGURATION_CHARACTERS = 100_000;
const MAX_PRD_FILE_BYTES = 8 * 1024 * 1024;
const MAX_REQUEST_BYTES = 10 * 1024 * 1024;

function buildRunInput(values: RunFormValues): Omit<RunCreate, "idempotency_key"> {
  return {
    repository_url: values.repository_url.trim(),
    commit_sha: values.commit_sha.trim().toLowerCase(),
    branch: values.branch?.trim() || undefined,
    prd_text: values.prd_text,
    configuration_text: values.configuration_text || "{}",
    policy: compileFormPolicy(values),
  };
}

export default function ProjectPage() {
  const { t, label, locale, formatDate } = useI18n();
  const params = useParams<{ projectId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [hasDraft, setHasDraft] = useState(false);
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<RunFormValues>({
    repository_url: "", commit_sha: "", branch: "main", prd_text: "", configuration_text: "{}",
    ...defaultPolicyValues(),
  });
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<ImportError | null>(null);
  const [importedFileName, setImportedFileName] = useState("");
  const [requestTooLarge, setRequestTooLarge] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const draftProjectId = useRef<string | null>(null);
  const requestIdentity = useRef<{ signature: string; key: string } | null>(null);
  const [form] = Form.useForm<RunFormValues>();
  useEffect(() => {
    if (!createOpen) return;
    const invalid = form.getFieldsError().filter((field) => field.errors.length).map((field) => field.name);
    if (invalid.length) void form.validateFields(invalid, { recursive: true }).catch(() => undefined);
  }, [locale, form, createOpen]);
  const project = useQuery({
    queryKey: ["project", params.projectId],
    queryFn: () => getProject(params.projectId),
  });
  const runs = useQuery({
    queryKey: ["project-runs", params.projectId],
    queryFn: () => getProjectRuns(params.projectId),
  });
  const creation = useMutation({
    mutationFn: (payload: RunCreate) => createRun(params.projectId, payload),
    onSuccess: (run) => {
      queryClient.setQueryData(["run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["project-runs", params.projectId] });
      router.push(`/runs/${run.id}`);
    },
  });

  const openCreate = () => {
    if (!hasDraft || draftProjectId.current !== params.projectId) {
      const initialValues: RunFormValues = {
        repository_url: project.data?.repository_url || "",
        commit_sha: "",
        branch: project.data?.default_branch || "main",
        prd_text: "",
        configuration_text: "{}",
        ...defaultPolicyValues(),
      };
      form.resetFields();
      form.setFieldsValue(initialValues);
      setDraft(initialValues);
      creation.reset();
      requestIdentity.current = null;
      draftProjectId.current = params.projectId;
      setImportedFileName("");
      setImportError(null);
      setRequestTooLarge(false);
      setStep(0);
      setHasDraft(true);
    }
    setCreateOpen(true);
  };

  const submitStep = () => {
    const values = form.getFieldsValue(true) as RunFormValues;
    setDraft(values);
    if (step < 3) {
      setStep(step + 1);
      return;
    }
    const input = buildRunInput(values);
    const signature = JSON.stringify({ project_id: params.projectId, ...input });
    // Retry identical inputs with the same key. Edited inputs must never reopen an older run.
    if (requestIdentity.current?.signature !== signature) {
      requestIdentity.current = { signature, key: `web:${crypto.randomUUID()}` };
    }
    const payload = { ...input, idempotency_key: requestIdentity.current.key };
    if (new TextEncoder().encode(JSON.stringify(payload)).length > MAX_REQUEST_BYTES) {
      setRequestTooLarge(true);
      setStep(1);
      return;
    }
    setRequestTooLarge(false);
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
      try { new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
      catch { setImportError("encoding"); return; }
      const text = await file.text();
      if (text.length > MAX_PRD_CHARACTERS) { setImportError("length"); return; }
      if (text.includes("\0")) { setImportError("encoding"); return; }
      form.setFieldsValue({ prd_text: text });
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
    : t("Unable to read the file. Choose it again or paste its contents below.", "无法读取文件，请重新选择，或直接粘贴下方文本。");

  if (project.isLoading) return <Spin size="large" />;
  if (!project.data) {
    return (
      <main>
        <Link href="/"><ArrowLeftOutlined aria-hidden /> {t("Projects", "项目")}</Link>
        <Alert
          type="error"
          showIcon
          message={t("Unable to load project", "无法加载项目")}
          description={project.error ? errorText(project.error, locale) : t("Project not found.", "项目不存在。")}
          action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>}
          style={{ marginTop: 20 }}
        />
      </main>
    );
  }

  const createLabel = hasDraft && draftProjectId.current === params.projectId ? t("Continue draft", "继续创建草稿") : t("Create test run", "创建测试运行");

  return (
    <main>
      <div className="page-heading">
        <Link href="/"><ArrowLeftOutlined aria-hidden /> {t("Projects", "项目")}</Link>
        <div className="eyebrow" style={{ marginTop: 18 }}>{project.data.key}</div>
        <Typography.Title level={1} style={{ margin: 0 }}>{project.data.name}</Typography.Title>
        <Typography.Paragraph className="muted" style={{ marginTop: 8 }}>
          {project.data.description || t("Project testing workspace", "项目测试工作台")}
        </Typography.Paragraph>
        <Space wrap>
          <Tag color="blue">{label(project.data.status)}</Tag>
          <Tag icon={<BranchesOutlined aria-hidden />}>{project.data.default_branch}</Tag>
          {project.data.repository_url ? <Tag style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{project.data.repository_url}</Tag> : null}
        </Space>
      </div>

      {project.error ? <Alert type="warning" showIcon message={t("Project refresh failed", "项目刷新失败")} description={t("Previously loaded project details and your draft remain available. Retry to get the latest state.", "已加载的项目资料和草稿仍会保留，请重试获取最新状态。")} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}

      <Space wrap style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>{t("Test runs", "测试运行")}</Typography.Title>
          <Typography.Text className="muted">{t("Each run fixes the source, requirements and policy for a reproducible test cycle.", "每次运行固定代码版本、需求和策略，形成可复现的完整测试周期。")}</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{createLabel}</Button>
      </Space>
      {runs.isLoading ? (
        <Spin />
      ) : runs.isError ? (
        <Alert
          type="error"
          showIcon
          message={t("Unable to load test runs", "无法加载测试运行")}
          description={errorText(runs.error, locale)}
          action={<Button onClick={() => void runs.refetch()} loading={runs.isFetching}>{t("Retry", "重试")}</Button>}
        />
      ) : runs.data?.length ? (
        <Row gutter={[18, 18]}>
          {runs.data.map((run) => (
            <Col xs={24} md={12} xl={8} key={run.id}>
              <Link href={`/runs/${run.id}`} style={{ textDecoration: "none" }}>
                <Card className="run-card" hoverable>
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    <Space style={{ width: "100%", justifyContent: "space-between" }}>
                      <Tag color={run.status === "COMPLETED" ? "green" : run.status === "BLOCKED" ? "red" : "geekblue"}>{label(run.status)}</Tag>
                      <ArrowRightOutlined aria-hidden />
                    </Space>
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>{run.key}</Typography.Title>
                      <div className="muted" style={{ marginTop: 4 }}>{t("Source snapshot", "源码快照")}</div>
                      <div className="entity-key" style={{ overflowWrap: "anywhere" }}>{run.source_snapshot_id}</div>
                    </div>
                    <Typography.Text className="muted">{t("Trigger: ", "触发方式：")}{label(run.trigger_type)}</Typography.Text>
                    <Typography.Text className="muted">{t("Created: ", "创建时间：")}{formatDate(run.created_at)}</Typography.Text>
                  </Space>
                </Card>
              </Link>
            </Col>
          ))}
        </Row>
      ) : (
        <Card className="section-card">
          <Empty description={t("Create a test run to analyze requirements and build test coverage.", "创建测试运行，开始分析需求并建立测试覆盖。")}>
            <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{createLabel}</Button>
          </Empty>
        </Card>
      )}

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
          items={[{ title: t("Source", "源码") }, { title: t("Requirements", "需求") }, { title: t("Policy", "策略") }, { title: t("Review", "确认") }]}
          style={{ margin: "24px 0" }}
        />
        {creation.isError ? (
          <Alert type="error" showIcon message={t("Test run could not be created", "测试运行创建失败")} description={errorText(creation.error, locale)} style={{ marginBottom: 20 }} />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message={t("Test run created. Opening the workbench…", "测试运行已创建，正在打开工作台…")} description={<Link href={`/runs/${creation.data.id}`}>{t("Open test run", "打开测试运行")}</Link>} style={{ marginBottom: 20 }} />
        ) : null}
        {requestTooLarge ? (
          <Alert type="error" showIcon message={t("The inputs exceed the 10 MiB request limit.", "输入超出 10 MiB 请求上限。")} description={t("Shorten the requirements or configuration, then review and submit again. Your draft is preserved.", "请精简需求或测试配置，再确认提交。当前草稿已保留。")} style={{ marginBottom: 20 }} />
        ) : null}
        <Form
          name="create-test-run"
          form={form}
          layout="vertical"
          preserve
          disabled={creation.isPending || creation.isSuccess || importing}
          requiredMark="optional"
          onFinish={submitStep}
          onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}
          onValuesChange={() => { if (creation.isError) creation.reset(); setRequestTooLarge(false); }}
        >
          {step === 0 ? (
            <>
              <Typography.Paragraph className="muted">
                {t("Choose the exact source revision to test. The full commit SHA keeps this run tied to an immutable version.", "选择需要测试的确切代码版本。完整提交 SHA 将本次运行固定到不可变版本。")}
              </Typography.Paragraph>
              <Alert
                type="info"
                showIcon
                message={t("Where will the source code be read?", "源码从哪里读取？")}
                description={t("Credential-free GitHub HTTPS repositories support automatic checkout. Other repository addresses or paths require an existing matching Git checkout on the Worker host. A path on your browser's computer does not upload the repository to the server.", "无需凭据的 GitHub HTTPS 仓库支持自动检出。其他仓库地址或路径，需要 Worker 所在主机已有对应的 Git 检出。填写浏览器所在电脑的路径，不会将仓库上传到服务器。")}
                style={{ marginBottom: 20 }}
              />
              <Form.Item
                name="repository_url"
                label={t("Repository URL or server path", "仓库地址或服务器路径")}
                normalize={(value: string) => value.trim()}
                rules={[
                  { required: true, whitespace: true, message: t("Enter the repository URL or Worker host path.", "请输入仓库地址，或 Worker 主机上的仓库路径。") },
                  { max: 2048, message: t("Use at most 2,048 characters.", "最多输入 2,048 个字符。") },
                ]}
              >
                <Input placeholder="https://github.com/your-team/your-repository" maxLength={2048} />
              </Form.Item>
              <Form.Item
                name="commit_sha"
                label={t("Commit SHA", "提交 SHA")}
                normalize={(value: string) => value.trim().toLowerCase()}
                extra={<>{t("Paste the full 40- or 64-character commit SHA. In your Git repository, run: ", "粘贴完整的 40 位或 64 位提交 SHA。在 Git 仓库中执行：")}<Typography.Text code copyable>git rev-parse HEAD</Typography.Text></>}
                rules={[
                  { required: true, message: t("Enter the full commit SHA.", "请输入完整提交 SHA。") },
                  { pattern: /^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/, message: t("Enter a full 40-character or 64-character hexadecimal commit SHA.", "请输入完整的 40 位或 64 位十六进制提交 SHA。") },
                ]}
              >
                <Input placeholder={t("Full commit SHA", "完整提交 SHA")} autoComplete="off" style={{ fontFamily: "monospace" }} />
              </Form.Item>
              <Form.Item name="branch" label={t("Branch", "分支")} extra={t("Optional reference label. The commit SHA fixes the tested version.", "可选参考标签；实际测试版本以提交 SHA 为准。")}>
                <Input placeholder={project.data.default_branch} />
              </Form.Item>
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
                label={t("Testing configuration", "测试配置")}
                extra={t("Optional text or JSON, up to 100,000 characters. Saved with this run's immutable inputs. Leave empty to use {}.", "可选纯文本或 JSON，最多 100,000 个字符；与本次运行的不可变输入一并保存。留空使用 {}。")}
                rules={[{ max: MAX_CONFIGURATION_CHARACTERS, message: t("Configuration must contain at most 100,000 characters.", "测试配置最多 100,000 个字符。") }]}
              >
                <Input.TextArea rows={4} showCount maxLength={MAX_CONFIGURATION_CHARACTERS} placeholder="{}" style={{ fontFamily: "monospace" }} />
              </Form.Item>
            </>
          ) : step === 2 ? <PolicyFields /> : (
            <Space direction="vertical" size={18} style={{ width: "100%", marginBottom: 24 }}>
              <Alert
                type="info"
                showIcon
                message={t("Ready to create your test run", "确认并创建测试运行")}
                description={t("These inputs will be fixed in immutable source and policy snapshots. After creation, start the testing workflow from the workbench. Changed inputs require a new run.", "输入将固定为不可变源码与策略快照。创建后，请在工作台启动测试流程；需要更换输入时应创建新的运行。")}
              />
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label={t("Project", "项目")}>{project.data.name}</Descriptions.Item>
                <Descriptions.Item label={t("Repository", "仓库")}><span style={{ overflowWrap: "anywhere" }}>{draft.repository_url}</span></Descriptions.Item>
                <Descriptions.Item label={t("Commit", "提交")}><Typography.Text code copyable style={{ overflowWrap: "anywhere", wordBreak: "break-all" }}>{draft.commit_sha}</Typography.Text></Descriptions.Item>
                <Descriptions.Item label={t("Branch", "分支")}>{draft.branch?.trim() || t("Not specified", "未指定")}</Descriptions.Item>
                <Descriptions.Item label={t("Policy", "策略")}><PolicyReview values={draft} /></Descriptions.Item>
              </Descriptions>
              <div style={{ width: "100%" }}>
                <Typography.Title level={5} style={{ marginTop: 0 }}>{t("Product requirements", "产品需求")}</Typography.Title>
                {importedFileName ? <Typography.Paragraph className="muted">{t("Imported from: ", "导入来源：")}{importedFileName}{t(" · Text shown below is the submitted content.", " · 以下正文为实际提交内容。")}</Typography.Paragraph> : null}
                <div className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 220, overflowY: "auto", padding: 12, borderRadius: 6 }}>{draft.prd_text}</div>
              </div>
              <details style={{ width: "100%" }}>
                <summary style={{ cursor: "pointer" }}>{t("Testing configuration", "测试配置")}</summary>
                <pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 180, overflowY: "auto" }}>{draft.configuration_text || "{}"}</pre>
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
                aria-label={step < 3 ? t("Continue to next step", "继续下一步") : t("Create test run", "创建测试运行")}
                loading={creation.isPending || creation.isSuccess}
              >
                {step < 3 ? <>{t("Continue", "下一步")} <ArrowRightOutlined aria-hidden /></> : t("Create test run", "创建测试运行")}
              </Button>
            </Space>
          </Space>
        </Form>
      </Modal>
    </main>
  );
}
