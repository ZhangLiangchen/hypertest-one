"use client";

import { useEffect, useRef, useState } from "react";
import { Alert, Button, Col, Divider, Form, Input, InputNumber, Row, Select, Table, Tag, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { cloudSelector, credentialFreeUrl } from "@/lib/cloud";
import type { CloudConfiguration, CloudConfigRevision, CloudCredential, CloudCredentialVersion, CloudSelector } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";

type ResourceValues = { sut_url: string; sut_ref: string; sut_kind: CloudSelector["kind"]; sut_strategy: CloudSelector["checkout_strategy"]; sut_base?: string; sut_credential?: string;
  framework_url: string; framework_ref: string; framework_kind: CloudSelector["kind"]; framework_strategy: CloudSelector["checkout_strategy"]; framework_base?: string; framework_credential?: string;
  environment_name: string; connection: "NONE" | "HTTPS" | "SSH"; host?: string; port?: number; user?: string; host_key?: string; environment_credential?: string; network_requirements?: string; expected_deployment?: string };
type CredentialValues = { credential_id?: string; kind: string; label: string; purpose: string; targets: string; actions: string[]; expires_at?: string; secret: string };

export function CloudResources({ latest, credentials, versions, operation, enabled, onSaved }: {
  latest?: CloudConfigRevision; credentials: CloudCredential[]; versions: CloudCredentialVersion[];
  operation: ReturnType<typeof useCloudOperation>; enabled: boolean; onSaved: () => void;
}) {
  const { t, formatDate } = useI18n();
  const [form] = Form.useForm<ResourceValues>(); const [credentialForm] = Form.useForm<CredentialValues>();
  const [resourceIssue, setResourceIssue] = useState<string | null>(null);
  const [fileIssue, setFileIssue] = useState(false);
  const [fileName, setFileName] = useState("");
  const fileGeneration = useRef(0);
  const connection = Form.useWatch("connection", form) || "NONE";
  const kind = Form.useWatch("kind", credentialForm) || "GIT_TOKEN";
  const rotationId = Form.useWatch("credential_id", credentialForm);
  const selectedCredential = credentials.find((row) => row.id === rotationId);
  const [rotationBaseline, setRotationBaseline] = useState<{ id: string; version: number } | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [baseVersion, setBaseVersion] = useState(0);
  const [draftTouched, setDraftTouched] = useState(false);
  const [baseConfiguration, setBaseConfiguration] = useState<CloudConfiguration | null>(null);
  const sutKind = Form.useWatch("sut_kind", form) || "BRANCH";
  const frameworkKind = Form.useWatch("framework_kind", form) || "BRANCH";
  useEffect(() => () => { fileGeneration.current++; }, []);

  useEffect(() => {
    if (!rotationId) setRotationBaseline(null);
    else if (selectedCredential && rotationBaseline?.id !== rotationId) setRotationBaseline({ id: rotationId, version: selectedCredential.version });
  }, [rotationId, selectedCredential, rotationBaseline?.id]);

  useEffect(() => {
    const accepted = operation.receipt;
    // Original-key reconciliation may finish after saveCredential returned UNKNOWN.
    // A receipt alone is insufficient: the pending stream clears only after full readback.
    if (rotationId && rotationBaseline && !operation.pending && !operation.busy && !operation.issue && accepted?.operation === "STORE_CREDENTIAL"
      && accepted.credential_id === rotationId && rotationBaseline.id === rotationId && accepted.version > rotationBaseline.version) {
      setRotationBaseline({ id: rotationId, version: accepted.version }); onSaved();
    }
  }, [operation.receipt, operation.pending, operation.busy, operation.issue, rotationId, rotationBaseline, onSaved]);

  useEffect(() => {
    if (!latest || loaded !== null || draftTouched) return;
    const config = latest.configuration;
    form.setFieldsValue({ sut_url: config.sut.url, sut_ref: config.sut.default_selector.value, sut_kind: config.sut.default_selector.kind,
      sut_strategy: config.sut.default_selector.checkout_strategy, sut_base: config.sut.default_selector.base_ref, sut_credential: config.sut.credential_version_id || undefined,
      framework_url: config.framework.url, framework_ref: config.framework.default_selector.value, framework_kind: config.framework.default_selector.kind,
      framework_strategy: config.framework.default_selector.checkout_strategy, framework_base: config.framework.default_selector.base_ref, framework_credential: config.framework.credential_version_id || undefined,
      environment_name: config.environment.name, connection: config.environment.connection, host: config.environment.host || undefined,
      port: config.environment.port || undefined, user: config.environment.user || undefined, host_key: config.environment.host_key || undefined,
      environment_credential: config.environment.credential_version_id || undefined, network_requirements: config.environment.network_requirements,
      expected_deployment: config.environment.expected_deployment });
    setLoaded(latest.id); setBaseVersion(latest.revision); setBaseConfiguration(config);
  }, [latest, loaded, form, draftTouched]);

  const credentialOptions = (types: string[]) => versions.flatMap((version) => {
    const credential = credentials.find((row) => row.id === version.credential_id && row.status === "ACTIVE" && types.includes(row.kind));
    return credential ? [{ value: version.id, label: `${credential.label} · v${version.version}` }] : [];
  });
  const blocked = !enabled || operation.blocked;

  async function configure(values: ResourceValues) {
    if (blocked) return;
    setResourceIssue(null);
    try {
      const configuration: CloudConfiguration = {
        sut: { url: values.sut_url.trim(), default_selector: cloudSelector(values.sut_kind, values.sut_ref, values.sut_strategy, values.sut_base), credential_version_id: values.sut_credential || null },
        framework: { url: values.framework_url.trim(), default_selector: cloudSelector(values.framework_kind, values.framework_ref, values.framework_strategy, values.framework_base), credential_version_id: values.framework_credential || null },
        environment: { ...baseConfiguration?.environment, name: values.environment_name.trim(), connection: values.connection,
          host: values.host?.trim() || null, port: values.port || null, user: values.user?.trim() || null,
          host_key: values.host_key?.trim() || null, credential_version_id: values.environment_credential || null,
          network_requirements: values.network_requirements || "", expected_deployment: values.expected_deployment?.trim() || "UNKNOWN", require_matching_deployment: baseConfiguration?.environment.require_matching_deployment ?? false },
      };
      const result = await operation.submit({ operation: "CONFIGURE", expected_version: baseVersion, configuration });
      if (result) { setLoaded(result.config_id || null); setBaseVersion(result.version); setBaseConfiguration(configuration); onSaved(); }
    } catch { setResourceIssue(t("Review both repository references before saving.", "请先核对两个仓库的分支引用。")); }
  }

  async function saveCredential(values: CredentialValues) {
    if (blocked) return;
    const credential = credentials.find((row) => row.id === values.credential_id);
    const request = { operation: "STORE_CREDENTIAL", expected_version: credential ? rotationBaseline?.version ?? credential.version : 0,
      credential_id: credential?.id || null, kind: credential?.kind || values.kind, label: credential?.label || values.label,
      purpose: credential?.purpose || values.purpose, allowed_targets: credential?.allowed_targets || values.targets.split("\n").map((line) => line.trim()).filter(Boolean),
      allowed_actions: credential?.allowed_actions || values.actions, expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
      secret: values.secret };
    // Clear raw material from the form on first send, including uncertain writes.
    fileGeneration.current++; credentialForm.setFieldValue("secret", ""); setFileName("");
    const result = await operation.submit(request);
    if (result) {
      // submit resolves only after the matching ACK and complete accepted readback.
      // Advance this local intention, never an unrelated externally refreshed version.
      if (credential && result.credential_id === credential.id) setRotationBaseline({ id: credential.id, version: result.version });
      onSaved();
    }
  }

  return <div className="workspace-section-stack">
    <section className="overview-section workspace-panel" aria-labelledby="cloud-resources-title">
      <Typography.Title id="cloud-resources-title" level={2}>{t("Project repositories and environment", "项目仓库与测试环境")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Save reusable resources once. Each dispatched task freezes its own exact versions and authorization.", "资源可保存复用；每个下发任务分别冻结确切版本和授权。")}</Typography.Paragraph>
      {resourceIssue ? <Alert showIcon type="error" message={resourceIssue} style={{ marginBottom: 20 }} /> : null}
      {latest && latest.revision !== baseVersion ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("A newer resource revision is available", "存在更新的资源修订")}
        description={t("Your draft still uses its original version. Read the saved revision before replacing your draft; it will not be rebased automatically.", "草稿仍使用原版本。替换草稿前请核对已保存修订，系统不会自动改变提交基线。 ")}
        action={<Button disabled={operation.blocked} onClick={() => { setDraftTouched(false); setLoaded(null); }}>{t("Load latest saved resources", "载入最新已保存资源")}</Button>} /> : null}
      {baseConfiguration?.environment.cloud_access_policy ? <Alert showIcon type="info" style={{ marginBottom: 20 }} message={t("Saved environment routing is retained", "保留已保存的环境路由限制")} description={baseConfiguration.environment.cloud_access_policy} /> : null}
      {baseConfiguration?.environment.ssh_access ? <Alert showIcon type="info" style={{ marginBottom: 20 }} message={t("Fixed SSH diagnostic bindings are read-only here", "固定 SSH 诊断绑定在此只读")} description={t("The approved profile and connection identity are preserved. This form does not create or expand diagnostic access.", "保留受权配置和连接身份；此表单不会创建或扩展诊断访问。 ")} /> : null}
      <Form form={form} className="workspace-form" layout="vertical" onValuesChange={() => setDraftTouched(true)} initialValues={{ sut_ref: "main", sut_kind: "BRANCH", sut_strategy: "HEAD", framework_ref: "main", framework_kind: "BRANCH", framework_strategy: "HEAD", connection: "NONE", environment_name: "Workspace test fixtures", expected_deployment: "UNKNOWN" }} onFinish={(values) => void configure(values)} scrollToFirstError>
        <div className="form-grid">{(["sut", "framework"] as const).map((role) => <section className="form-section" key={role}>
          <Typography.Title level={3}>{role === "sut" ? t("System under test", "被测对象") : t("Test framework", "测试框架")}</Typography.Title>
          <Form.Item name={`${role}_url`} label={t("Git repository URL", "Git 仓库地址")} rules={[{ required: true }, { validator: (_, value) => !value || credentialFreeUrl(value) ? Promise.resolve() : Promise.reject(new Error(t("Use a credential-free HTTPS or SSH URL.", "请使用不含凭据的 HTTPS 或 SSH 地址。"))) }]}><Input autoComplete="off" placeholder="https://git.example.com/team/repository.git" /></Form.Item>
          <Form.Item name={`${role}_kind`} label={t("Default version selector", "默认版本选择")}><Select options={[{ value: "BRANCH", label: t("Branch", "分支") }, { value: "SHA", label: t("Full SHA", "完整 SHA") }, { value: "MR", label: "MR" }]} /></Form.Item>
          <Form.Item name={`${role}_ref`} label={t("Default branch, SHA or MR number", "默认分支、SHA 或 MR 编号")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
          {(role === "sut" ? sutKind : frameworkKind) === "MR" ? <><Form.Item name={`${role}_base`} label={t("MR base ref", "MR base 引用")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item><Form.Item name={`${role}_strategy`} label={t("Checkout strategy", "检出方式")}><Select options={[{ value: "HEAD", label: "HEAD" }, { value: "MERGE", label: "MERGE" }]} /></Form.Item></> : null}
          <Form.Item name={`${role}_credential`} label={t("Repository credential version", "仓库凭据版本")}><Select allowClear options={credentialOptions(["GIT_TOKEN", "GIT_SSH_KEY"])} placeholder={t("Public repository / select saved credential", "公开仓库 / 选择已保存凭据")} /></Form.Item>
        </section>)}</div>
        <section className="form-section" aria-labelledby="cloud-environment-title">
        <Typography.Title id="cloud-environment-title" level={3}>{t("Test environment", "测试环境")}</Typography.Title>
        <Row gutter={[24, 0]}><Col xs={24} md={12}><Form.Item name="environment_name" label={t("Environment name", "环境名称")} rules={[{ required: true }]}><Input maxLength={128} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="connection" label={t("Connection method", "访问方式")}><Select disabled={!!baseConfiguration?.environment.ssh_access} options={[{ value: "NONE", label: t("Workspace-local fixtures", "工作区内测试") }, { value: "HTTPS", label: t("HTTPS · configuration only", "HTTPS · 仅保存配置") }, { value: "SSH", label: t("SSH · configuration only", "SSH · 仅保存配置") }]} /></Form.Item></Col></Row>
        {connection !== "NONE" ? <><Alert showIcon type="warning" message={t("General remote execution is unavailable in this form", "此表单不提供通用远端执行")} description={t("You may save connection resources. Existing fixed diagnostic bindings remain read-only; they do not enable general remote shell or staging access.", "可以保存连接资源；已有固定诊断绑定在此只读，不开放通用远端 Shell 或 staging 访问。 ")} style={{ marginBottom: 20 }} />
          <Row gutter={[24, 0]}><Col xs={24} md={16}><Form.Item name="host" label={t("Host", "主机")} rules={[{ required: true }]}><Input disabled={!!baseConfiguration?.environment.ssh_access} maxLength={255} /></Form.Item></Col><Col xs={24} md={8}><Form.Item name="port" label={t("Port", "端口")}><InputNumber disabled={!!baseConfiguration?.environment.ssh_access} min={1} max={65535} style={{ width: "100%" }} /></Form.Item></Col></Row>
          {connection === "SSH" ? <><Form.Item name="user" label={t("SSH user", "SSH 用户")} rules={[{ required: true }]}><Input disabled={!!baseConfiguration?.environment.ssh_access} autoComplete="off" maxLength={128} /></Form.Item><Form.Item name="host_key" label={t("Pinned SSH host key", "已核验的 SSH 主机公钥")} rules={[{ required: true }]}><Input.TextArea disabled={!!baseConfiguration?.environment.ssh_access} rows={2} maxLength={4096} /></Form.Item></> : null}
          <Form.Item name="environment_credential" label={t("Environment credential version", "环境凭据版本")}><Select disabled={!!baseConfiguration?.environment.ssh_access} allowClear options={credentialOptions(["SSH_KEY", "APPLICATION_PRIVATE_KEY"])} /></Form.Item>
          <Form.Item name="network_requirements" label={t("Network / jump host requirements", "网络与跳板要求")}><Input.TextArea disabled={!!baseConfiguration?.environment.ssh_access} rows={2} maxLength={4096} /></Form.Item></> : null}
        <Form.Item name="expected_deployment" label={t("Expected deployment identity", "预期部署版本")} extra={t("A source SHA does not prove the environment runs that version.", "源码 SHA 不证明环境已部署对应版本。 ")}><Input maxLength={512} /></Form.Item>
        </section>
        <div className="form-actions">
          <Button type="primary" htmlType="submit" disabled={blocked} loading={operation.busy}>{t("Save resource revision", "保存资源修订")}</Button>
          <Typography.Text type="secondary">{t("Draft baseline revision", "草稿基线修订")}: {baseVersion}</Typography.Text>
        </div>
      </Form>
    </section>
    <section className="overview-section workspace-panel" aria-labelledby="cloud-credentials-title">
      <Typography.Title id="cloud-credentials-title" level={2}>{t("Reusable credentials", "可复用凭据")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Secret values are encrypted by the API and never read back. They are cleared from this form on submission and never saved to browser storage.", "秘密由 API 加密保存，不提供原文读回；提交时清空输入，不写入浏览器存储。 ")}</Typography.Paragraph>
      <Form form={credentialForm} className="workspace-form" layout="vertical" onFinish={(values) => void saveCredential(values)} onValuesChange={(changed) => { if ("credential_id" in changed || "kind" in changed) { fileGeneration.current++; credentialForm.setFieldValue("secret", ""); setFileName(""); } }} initialValues={{ kind: "GIT_TOKEN", actions: ["git:read"] }} scrollToFirstError>
        <Form.Item name="credential_id" label={t("Create or rotate", "新增或轮换")}><Select allowClear placeholder={t("New credential", "新增凭据")} options={credentials.filter((row) => row.status === "ACTIVE").map((row) => ({ value: row.id, label: `${row.label} · v${row.version}` }))} /></Form.Item>
        {!selectedCredential ? <><Row gutter={[24, 0]}><Col xs={24} md={12}><Form.Item name="label" label={t("Credential name", "凭据名称")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item></Col><Col xs={24} md={12}><Form.Item name="kind" label={t("Type", "类型")}><Select options={[{ value: "GIT_TOKEN", label: "Git token" }, { value: "GIT_SSH_KEY", label: "Git SSH key" }, { value: "SSH_KEY", label: "SSH key" }, { value: "APPLICATION_PRIVATE_KEY", label: t("Application private key", "应用鉴权私钥") }]} /></Form.Item></Col></Row>
          <Form.Item name="purpose" label={t("Purpose", "用途")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
          <Form.Item name="targets" label={t("Exact allowed repository URLs / hosts, one per line", "允许的完整仓库地址或主机，每行一个")} rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="actions" label={t("Allowed actions", "允许的操作")} rules={[{ required: true }]}><Select mode="multiple" options={["git:read", "git:write", "environment:read", "environment:write"].map((value) => ({ value, label: value }))} /></Form.Item></> : <Typography.Paragraph>{t("Rotation retains the original purpose and target scope.", "轮换保留原用途和目标范围。 ")}</Typography.Paragraph>}
        <Form.Item name="expires_at" label={t("Expiry (optional)", "到期时间（可选）")} rules={[{ validator: (_, value) => !value || Number.isFinite(new Date(value).getTime()) ? Promise.resolve() : Promise.reject(new Error(t("Enter a valid date and time.", "请输入有效日期和时间。"))) }]}><Input type="datetime-local" /></Form.Item>
        <Form.Item name="secret" label={kind === "GIT_TOKEN" && !selectedCredential ? "Token" : t("Secret value / private key", "秘密值 / 私钥")} rules={[{ required: true }]}><Input.Password visibilityToggle={false} autoComplete="new-password" maxLength={65536} /></Form.Item>
        <label className="credential-file-field">{t("Or load a private key file (up to 64 KiB)", "或读取私钥文件（最大 64 KiB）")}<input type="file" style={{ display: "block", margin: "8px 0 16px" }} onChange={(event) => {
          const file = event.target.files?.[0]; const generation = ++fileGeneration.current; event.target.value = ""; setFileIssue(false);
          if (!file) return;
          credentialForm.setFieldValue("secret", ""); setFileName("");
          if (file.size > 65536) { setFileIssue(true); return; }
          void file.text().then((value) => { if (fileGeneration.current === generation) { credentialForm.setFieldValue("secret", value); setFileName(file.name); } }).catch(() => { if (fileGeneration.current === generation) setFileIssue(true); });
        }} /></label>
        {fileIssue ? <Alert type="error" showIcon message={t("The key file could not be read or exceeds 64 KiB.", "无法读取密钥文件，或文件超过 64 KiB。 ")} style={{ marginBottom: 16 }} /> : null}
        {fileName ? <Typography.Paragraph>{t("Private file loaded", "已读取私有文件")}: {fileName}</Typography.Paragraph> : null}
        <Button type="primary" htmlType="submit" disabled={blocked} loading={operation.busy}>{selectedCredential ? t("Rotate credential", "轮换凭据") : t("Encrypt and save credential", "加密保存凭据")}</Button>
      </Form>
      <Divider />
      <Table rowKey="id" size="small" scroll={{ x: 700 }} dataSource={credentials} pagination={false} columns={[
        { title: t("Name", "名称"), dataIndex: "label" }, { title: t("Type", "类型"), dataIndex: "kind" },
        { title: t("Version", "版本"), dataIndex: "version" }, { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Tag>{value}</Tag> },
        { title: t("Latest expiry", "最新到期时间"), key: "expiry", render: (_, row) => { const version = versions.filter((item) => item.credential_id === row.id).sort((a, b) => b.version - a.version)[0]; return version?.expires_at ? formatDate(version.expires_at) : "—"; } },
        { title: t("Action", "操作"), key: "action", render: (_, row) => <Button danger disabled={blocked || row.status !== "ACTIVE"} onClick={() => void operation.submit({ operation: "REVOKE_CREDENTIAL", credential_id: row.id, expected_version: row.version, reason: "Revoked from Cloud project resources" }).then((receipt) => { if (receipt) onSaved(); })}>{t("Revoke", "撤销")}</Button> },
      ]} locale={{ emptyText: t("No saved credentials. Public repositories need no token.", "尚无已保存凭据。公开仓库无需 token。 ") }} />
    </section>
  </div>;
}
