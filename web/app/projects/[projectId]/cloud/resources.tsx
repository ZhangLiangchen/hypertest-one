"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Col, Divider, Form, Input, InputNumber, Row, Select, Space, Table, Tag, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { cloudSelector, credentialFreeUrl } from "@/lib/cloud";
import type { CloudConfiguration, CloudConfigRevision, CloudCredential, CloudCredentialVersion } from "@/lib/cloud";
import type { useCloudOperation } from "@/lib/cloud-operation";

type ResourceValues = { sut_url: string; sut_ref: string; sut_credential?: string; framework_url: string; framework_ref: string; framework_credential?: string; environment_name: string; connection: "NONE" | "HTTPS" | "SSH"; host?: string; port?: number; user?: string; host_key?: string; environment_credential?: string; network_requirements?: string; expected_deployment?: string };
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
  const connection = Form.useWatch("connection", form) || "NONE";
  const kind = Form.useWatch("kind", credentialForm) || "GIT_TOKEN";
  const rotationId = Form.useWatch("credential_id", credentialForm);
  const selectedCredential = credentials.find((row) => row.id === rotationId);
  const [rotationBaseline, setRotationBaseline] = useState<{ id: string; version: number } | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const [baseVersion, setBaseVersion] = useState(0);
  const [draftTouched, setDraftTouched] = useState(false);

  useEffect(() => {
    if (!rotationId) setRotationBaseline(null);
    else if (selectedCredential && rotationBaseline?.id !== rotationId) setRotationBaseline({ id: rotationId, version: selectedCredential.version });
  }, [rotationId, selectedCredential, rotationBaseline?.id]);

  useEffect(() => {
    if (!latest || loaded !== null || draftTouched) return;
    const config = latest.configuration;
    form.setFieldsValue({ sut_url: config.sut.url, sut_ref: config.sut.default_selector.value, sut_credential: config.sut.credential_version_id || undefined,
      framework_url: config.framework.url, framework_ref: config.framework.default_selector.value, framework_credential: config.framework.credential_version_id || undefined,
      environment_name: config.environment.name, connection: config.environment.connection, host: config.environment.host || undefined,
      port: config.environment.port || undefined, user: config.environment.user || undefined, host_key: config.environment.host_key || undefined,
      environment_credential: config.environment.credential_version_id || undefined, network_requirements: config.environment.network_requirements,
      expected_deployment: config.environment.expected_deployment });
    setLoaded(latest.id); setBaseVersion(latest.revision);
  }, [latest, loaded, form, draftTouched]);

  const credentialOptions = (types: string[]) => versions.flatMap((version) => {
    const credential = credentials.find((row) => row.id === version.credential_id && row.status === "ACTIVE" && types.includes(row.kind));
    return credential ? [{ value: version.id, label: `${credential.label} · v${version.version}` }] : [];
  });
  const blocked = !enabled || operation.blocked;

  async function configure(values: ResourceValues) {
    setResourceIssue(null);
    try {
      const configuration: CloudConfiguration = {
        sut: { url: values.sut_url.trim(), default_selector: cloudSelector("BRANCH", values.sut_ref), credential_version_id: values.sut_credential || null },
        framework: { url: values.framework_url.trim(), default_selector: cloudSelector("BRANCH", values.framework_ref), credential_version_id: values.framework_credential || null },
        environment: { name: values.environment_name.trim(), connection: values.connection,
          host: values.host?.trim() || null, port: values.port || null, user: values.user?.trim() || null,
          host_key: values.host_key?.trim() || null, credential_version_id: values.environment_credential || null,
          network_requirements: values.network_requirements || "", expected_deployment: values.expected_deployment?.trim() || "UNKNOWN", require_matching_deployment: false },
      };
      const result = await operation.submit({ operation: "CONFIGURE", expected_version: baseVersion, configuration });
      if (result) { setLoaded(result.config_id || null); setBaseVersion(result.version); onSaved(); }
    } catch { setResourceIssue(t("Review both repository references before saving.", "请先核对两个仓库的分支引用。")); }
  }

  async function saveCredential(values: CredentialValues) {
    const credential = credentials.find((row) => row.id === values.credential_id);
    const request = { operation: "STORE_CREDENTIAL", expected_version: credential ? rotationBaseline?.version ?? credential.version : 0,
      credential_id: credential?.id || null, kind: credential?.kind || values.kind, label: credential?.label || values.label,
      purpose: credential?.purpose || values.purpose, allowed_targets: credential?.allowed_targets || values.targets.split("\n").map((line) => line.trim()).filter(Boolean),
      allowed_actions: credential?.allowed_actions || values.actions, expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
      secret: values.secret };
    // Clear raw material from the form on first send, including uncertain writes.
    credentialForm.setFieldValue("secret", ""); setFileName("");
    const result = await operation.submit(request);
    if (result) onSaved();
  }

  return <Space direction="vertical" size={28} style={{ width: "100%" }}>
    <section className="overview-section" aria-labelledby="cloud-resources-title">
      <Typography.Title id="cloud-resources-title" level={2}>{t("Project repositories and environment", "项目仓库与测试环境")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Save reusable resources once. Each dispatched task freezes its own exact versions and authorization.", "资源可保存复用；每个下发任务分别冻结确切版本和授权。")}</Typography.Paragraph>
      {resourceIssue ? <Alert showIcon type="error" message={resourceIssue} style={{ marginBottom: 20 }} /> : null}
      {latest && latest.revision !== baseVersion ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("A newer resource revision is available", "存在更新的资源修订")}
        description={t("Your draft still uses its original version. Read the saved revision before replacing your draft; it will not be rebased automatically.", "草稿仍使用原版本。替换草稿前请核对已保存修订，系统不会自动改变提交基线。 ")}
        action={<Button disabled={operation.blocked} onClick={() => { setDraftTouched(false); setLoaded(null); }}>{t("Load latest saved resources", "载入最新已保存资源")}</Button>} /> : null}
      <Form form={form} layout="vertical" onValuesChange={() => setDraftTouched(true)} initialValues={{ sut_ref: "main", framework_ref: "main", connection: "NONE", environment_name: "Workspace test fixtures", expected_deployment: "UNKNOWN" }} onFinish={(values) => void configure(values)} scrollToFirstError>
        <Row gutter={[24, 0]}>{(["sut", "framework"] as const).map((role) => <Col xs={24} lg={12} key={role}>
          <Typography.Title level={3}>{role === "sut" ? t("System under test", "被测对象") : t("Test framework", "测试框架")}</Typography.Title>
          <Form.Item name={`${role}_url`} label={t("Git repository URL", "Git 仓库地址")} rules={[{ required: true }, { validator: (_, value) => !value || credentialFreeUrl(value) ? Promise.resolve() : Promise.reject(new Error(t("Use a credential-free HTTPS or SSH URL.", "请使用不含凭据的 HTTPS 或 SSH 地址。"))) }]}><Input autoComplete="off" placeholder="https://git.example.com/team/repository.git" /></Form.Item>
          <Form.Item name={`${role}_ref`} label={t("Default branch", "默认分支")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
          <Form.Item name={`${role}_credential`} label={t("Repository credential version", "仓库凭据版本")}><Select allowClear options={credentialOptions(["GIT_TOKEN", "GIT_SSH_KEY"])} placeholder={t("Public repository / select saved credential", "公开仓库 / 选择已保存凭据")} /></Form.Item>
        </Col>)}</Row>
        <Divider />
        <Row gutter={[24, 0]}><Col xs={24} md={12}><Form.Item name="environment_name" label={t("Environment name", "环境名称")} rules={[{ required: true }]}><Input maxLength={128} /></Form.Item></Col>
          <Col xs={24} md={12}><Form.Item name="connection" label={t("Connection method", "访问方式")}><Select options={[{ value: "NONE", label: t("Workspace-local fixtures", "工作区内测试") }, { value: "HTTPS", label: t("HTTPS · configuration only", "HTTPS · 仅保存配置") }, { value: "SSH", label: t("SSH · configuration only", "SSH · 仅保存配置") }]} /></Form.Item></Col></Row>
        {connection !== "NONE" ? <><Alert showIcon type="warning" message={t("Remote connection is not executable yet", "远端访问尚不可执行")} description={t("You may save these resources. This runtime will block dispatch to remote environments until an enforced adapter is available.", "可以保存资源；具备受控访问适配器前，当前运行配置会阻止远端环境执行。 ")} style={{ marginBottom: 20 }} />
          <Row gutter={[24, 0]}><Col xs={24} md={16}><Form.Item name="host" label={t("Host", "主机")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item></Col><Col xs={24} md={8}><Form.Item name="port" label={t("Port", "端口")}><InputNumber min={1} max={65535} style={{ width: "100%" }} /></Form.Item></Col></Row>
          {connection === "SSH" ? <><Form.Item name="user" label={t("SSH user", "SSH 用户")} rules={[{ required: true }]}><Input autoComplete="off" maxLength={128} /></Form.Item><Form.Item name="host_key" label={t("Pinned SSH host key", "已核验的 SSH 主机公钥")} rules={[{ required: true }]}><Input.TextArea rows={2} maxLength={4096} /></Form.Item></> : null}
          <Form.Item name="environment_credential" label={t("Environment credential version", "环境凭据版本")}><Select allowClear options={credentialOptions(["SSH_KEY", "APPLICATION_PRIVATE_KEY"])} /></Form.Item>
          <Form.Item name="network_requirements" label={t("Network / jump host requirements", "网络与跳板要求")}><Input.TextArea rows={2} maxLength={4096} /></Form.Item></> : null}
        <Form.Item name="expected_deployment" label={t("Expected deployment identity", "预期部署版本")} extra={t("A source SHA does not prove the environment runs that version.", "源码 SHA 不证明环境已部署对应版本。 ")}><Input maxLength={512} /></Form.Item>
        <Button type="primary" htmlType="submit" disabled={blocked} loading={operation.busy}>{t("Save resource revision", "保存资源修订")}</Button>
        <Typography.Text type="secondary" style={{ marginLeft: 16 }}>{t("Draft baseline revision", "草稿基线修订")}: {baseVersion}</Typography.Text>
      </Form>
    </section>
    <section className="overview-section" aria-labelledby="cloud-credentials-title">
      <Typography.Title id="cloud-credentials-title" level={2}>{t("Reusable credentials", "可复用凭据")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Secret values are encrypted by the API and never read back. They are cleared from this form on submission and never saved to browser storage.", "秘密由 API 加密保存，不提供原文读回；提交时清空输入，不写入浏览器存储。 ")}</Typography.Paragraph>
      <Form form={credentialForm} layout="vertical" onFinish={(values) => void saveCredential(values)} initialValues={{ kind: "GIT_TOKEN", actions: ["git:read"] }} scrollToFirstError>
        <Form.Item name="credential_id" label={t("Create or rotate", "新增或轮换")}><Select allowClear placeholder={t("New credential", "新增凭据")} options={credentials.filter((row) => row.status === "ACTIVE").map((row) => ({ value: row.id, label: `${row.label} · v${row.version}` }))} /></Form.Item>
        {!selectedCredential ? <><Row gutter={[24, 0]}><Col xs={24} md={12}><Form.Item name="label" label={t("Credential name", "凭据名称")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item></Col><Col xs={24} md={12}><Form.Item name="kind" label={t("Type", "类型")}><Select options={[{ value: "GIT_TOKEN", label: "Git token" }, { value: "GIT_SSH_KEY", label: "Git SSH key" }, { value: "SSH_KEY", label: "SSH key" }, { value: "APPLICATION_PRIVATE_KEY", label: t("Application private key", "应用鉴权私钥") }]} /></Form.Item></Col></Row>
          <Form.Item name="purpose" label={t("Purpose", "用途")} rules={[{ required: true }]}><Input maxLength={255} /></Form.Item>
          <Form.Item name="targets" label={t("Exact allowed repository URLs / hosts, one per line", "允许的完整仓库地址或主机，每行一个")} rules={[{ required: true }]}><Input.TextArea rows={3} /></Form.Item>
          <Form.Item name="actions" label={t("Allowed actions", "允许的操作")} rules={[{ required: true }]}><Select mode="multiple" options={["git:read", "git:write", "environment:read", "environment:write"].map((value) => ({ value, label: value }))} /></Form.Item></> : <Typography.Paragraph>{t("Rotation retains the original purpose and target scope.", "轮换保留原用途和目标范围。 ")}</Typography.Paragraph>}
        <Form.Item name="expires_at" label={t("Expiry (optional)", "到期时间（可选）")}><Input type="datetime-local" /></Form.Item>
        <Form.Item name="secret" label={kind === "GIT_TOKEN" && !selectedCredential ? "Token" : t("Secret value / private key", "秘密值 / 私钥")} rules={[{ required: true }]}><Input.Password visibilityToggle={false} autoComplete="new-password" maxLength={65536} /></Form.Item>
        <label>{t("Or load a private key file (up to 64 KiB)", "或读取私钥文件（最大 64 KiB）")}<input type="file" style={{ display: "block", margin: "8px 0 16px" }} onChange={(event) => {
          const file = event.target.files?.[0]; event.target.value = ""; setFileIssue(false);
          if (!file) return;
          if (file.size > 65536) { setFileIssue(true); return; }
          void file.text().then((value) => { credentialForm.setFieldValue("secret", value); setFileName(file.name); }).catch(() => setFileIssue(true));
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
  </Space>;
}
