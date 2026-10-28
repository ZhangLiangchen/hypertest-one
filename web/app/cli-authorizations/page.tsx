"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircleFilled, ClockCircleOutlined, LaptopOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, Descriptions, Empty, Form, Input, Space, Tag, Typography } from "antd";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText, getProjects } from "@/lib/api";
import { cliAuthorizationApi, validateCliApproval, type CliGrant, type CliGlobalAuthorization, type CliRequest, type CliWebSetup } from "@/lib/cli-authorization";
import { useLocalWebOperation } from "@/lib/archive-operation";
import { CLI_RELEASE, cliInstallCommand } from "@/lib/cli-release";
import { cliBindCommand, cliServerOrigin } from "@/lib/cli-install-prompt";
import { useI18n } from "@/lib/i18n";
import { WorkspaceHeading } from "@/app/workspace-ui";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";
import { CliInstallPrompt } from "./cli-install-prompt";
import { AuthorizedCliClients, GlobalCliAuthorizations } from "./cli-client-tree";

const sendApproval = (path: string, payload: Record<string, unknown>) => cliAuthorizationApi<CliRequest>(path, { method: "POST", body: JSON.stringify(payload) });
const recoverApproval = (path: string) => cliAuthorizationApi<CliRequest>(path);
const validProjectId = (value?: string | null) => value && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value) ? value : null;

function PairingDetails({ request }: { request: CliRequest }) {
  const { t, formatDate } = useI18n();
  return <Descriptions column={2} items={[
    { key: "code", label: t("Match this code in your terminal", "与终端核对短码"), children: <Typography.Text className="cli-pairing-code">{request.short_code}</Typography.Text> }, { key: "state", label: t("State", "状态"), children: <Tag>{request.status}</Tag> },
    { key: "client", label: t("Client", "客户端"), children: request.client_name }, { key: "server", label: t("Server", "服务器"), children: request.server_url },
    { key: "fingerprint", label: t("Client credential fingerprint", "客户端凭据指纹"), children: <Typography.Text code>{request.credential_fingerprint}</Typography.Text> }, { key: "expires", label: t("Pairing expires", "配对有效期至"), children: formatDate(request.expires_at) },
  ]} />;
}

function CliRequestResult({ request }: { request: CliRequest }) {
  const { t, formatDate } = useI18n();
  const inactive = request.authorization?.status === "REVOKED" || request.authorization?.status === "EXPIRED";
  const status = request.authorization?.status === "REVOKED" ? t("Authorization revoked", "授权已撤销") : request.authorization?.status === "EXPIRED" ? t("Authorization expired", "授权已过期") : request.status === "BOUND" ? t("Bound", "已绑定") : request.status === "APPROVED" ? t("Approved · awaiting CLI", "已批准 · 等待 CLI 确认") : request.status === "EXPIRED" ? t("Pairing expired", "配对已过期") : t("Pairing denied", "配对已拒绝");
  return <div className="cli-request-result">
    <div className="cli-request-client"><LaptopOutlined aria-hidden /><strong>{request.client_name}</strong><span className={`cli-request-status${request.status === "BOUND" && !inactive ? " is-bound" : request.status === "APPROVED" ? " is-waiting" : ""}`} role="status">{request.status === "BOUND" && !inactive ? <CheckCircleFilled aria-hidden /> : request.status === "APPROVED" ? <ClockCircleOutlined aria-hidden /> : null}{status}</span></div>
    {request.approval ? <p className="cli-request-meta"><span>{(request.authorization?.all_projects || request.approval.all_projects) ? t("All current and future projects", "全部现有及未来项目") : `${request.approval.project_ids.length} ${t("projects approved in this request", "个项目获本次批准")}`}</span><span>{request.authorization?.all_projects ? (request.authorization.expires_at ? `${t("Grant valid until", "授权有效期至")} ${formatDate(request.authorization.expires_at)}` : t("Never expires", "永不过期")) : request.approval.expires_at ? `${t("Grant valid until", "授权有效期至")} ${formatDate(request.approval.expires_at)}` : t("Never expires", "永不过期")}</span></p> : null}
    {request.status === "APPROVED" ? <Typography.Paragraph className="muted">{t("Return to your local Agent to continue this request and save the authorization.", "请返回本地 Agent 继续原请求并保存授权。")}</Typography.Paragraph> : null}
    <details className="cli-pairing-details"><summary>{t("Pairing details", "配对详情")}</summary><PairingDetails request={request} /></details>
  </div>;
}
export default function CliAuthorizationsPage() {
  const { t, locale } = useI18n(); const search = useSearchParams(); const cache = useQueryClient();
  const requestId = search.get("request_id") || ""; const preselectedProject = validProjectId(search.get("projectId"));
  const [site, setSite] = useState(""), [inputRequest, setInputRequest] = useState(requestId); const [form] = Form.useForm();
  useEffect(() => { setSite(window.location.origin); }, []);
  const setup = useQuery({ queryKey: ["archive-web-setup"], queryFn: () => cliAuthorizationApi<CliWebSetup>("setup"), retry: false });
  const enabled = setup.data?.configured === true;
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => getProjects(), enabled, retry: false });
  const grants = useQuery({ queryKey: ["cli-grants"], queryFn: () => cliAuthorizationApi<{ items: CliGrant[]; authorizations?: CliGlobalAuthorization[] }>("grants"), enabled, retry: false });
  const request = useQuery({ queryKey: ["cli-request", requestId], queryFn: () => cliAuthorizationApi<CliRequest>(`requests/${requestId}`), enabled: enabled && Boolean(requestId), retry: false });
  const operation = useLocalWebOperation("auth", "global", `approve:${requestId}`, sendApproval, recoverApproval, validateCliApproval);
  const installCommand = cliInstallCommand();
  const cliServer = cliServerOrigin(setup.data?.cli_server_origin, site);
  let bindCommand = "";
  if (cliServer) { try { bindCommand = cliBindCommand(cliServer, preselectedProject || undefined); } catch { /* The prompt and manual command share the same validated origin. */ } }
  const changed = () => { void cache.invalidateQueries({ queryKey: ["cli-grants"] }); void cache.invalidateQueries({ queryKey: ["cli-request", requestId] }); };
  async function approve() {
    if (!request.data || request.data.status !== "PENDING") return;
    const result = await operation.submit(`requests/${requestId}/approve`, (key) => `requests/by-key?request_id=${requestId}&operation=APPROVE&idempotency_key=${key}`,
      { all_projects: true, project_ids: [], scopes: ["archive:read", "archive:write"], expires_in_days: null, short_code: request.data.short_code });
    if (result) changed();
  }
  return <main className="workspace-page cli-authorizations-page"><WorkspaceHeading title={t("CLI authorization", "CLI 授权")} backHref="/" backLabel={t("Projects", "项目")} description={t("Authorize one local CLI for all current and future projects without an expiration. Reuse it across workspaces and Agent sessions.", "为本地 CLI 授权全部现有及未来项目，默认永不过期，可跨工作目录与 Agent 会话复用。")}
    actions={<Button onClick={() => { void setup.refetch(); void grants.refetch(); if (requestId) void request.refetch(); }}>{t("Refresh", "刷新")}</Button>} />
    {setup.isError || setup.data?.configured === false ? <Alert type="warning" showIcon className="archive-operation-notice" message={t("CLI authorization is not available on this server", "此服务器尚未开放 CLI 授权")} description={t("The server operator must configure the archive Web boundary. No credential is requested or stored by this page.", "需要服务管理员配置归档 Web 入口。此页面不索取或保存凭据。") } /> : null}
    {requestId ? <section className="workspace-panel archive-section cli-approval-panel"><div className="activity-heading"><Typography.Title level={2}>{request.data && request.data.status !== "PENDING" ? t("CLI binding status", "CLI 绑定状态") : t("Approve this CLI", "批准此 CLI")}</Typography.Title><Button onClick={() => void request.refetch()} loading={request.isFetching}>{t("Refresh request", "刷新请求")}</Button></div>
      {request.isError ? <Alert type="error" showIcon message={t("Pairing request could not be read", "无法读取配对请求")} description={errorText(request.error, locale)} /> : null}
      {request.data ? request.data.status === "PENDING" ? <><PairingDetails request={request.data} />
      <Form key={requestId} form={form} layout="vertical" onFinish={approve} disabled={operation.blocked}>
        <Typography.Paragraph>{t("Access", "授权范围")}: {t("All current and future projects", "全部现有及未来项目")} · {t("Never expires", "永不过期")}</Typography.Paragraph>
        <Typography.Paragraph>{t("Permissions", "权限")}: <Tag>archive:read</Tag><Tag>archive:write</Tag></Typography.Paragraph>
        <Form.Item name="code_confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error(t("Check the terminal code first.", "请先核对终端短码。"))) }]}><Checkbox>{t("The code matches the CLI I started, and I approve this access.", "短码与我启动的 CLI 一致，我批准上述授权。")}</Checkbox></Form.Item>
        <Button type="primary" htmlType="submit" loading={operation.busy} disabled={operation.blocked}>{t("Approve CLI", "批准 CLI")}</Button>
      </Form></> : <CliRequestResult request={request.data} /> : null}
      <ArchiveOperationNotice operation={operation} onAccepted={changed} />
    </section> : null}
    <div className="cli-bind-guide"><section id="cli-install" className="workspace-panel cli-guide-install"><Typography.Title level={2}>{t("Let your Agent install or upgrade the CLI", "让 Agent 安装或升级 CLI")}</Typography.Title>
      <CliInstallPrompt projectId={preselectedProject || undefined} server={cliServer} caCertificate={setup.data?.cli_ca_certificate} />
      <details className="cli-install-manual"><summary>{t("Manual installation and binding", "手动安装与绑定")}</summary>
      {CLI_RELEASE.published ? <>
        <Typography.Paragraph>{t("Python 3.12 or later is required. Download both files into the same directory, then run the verified installer command there.", "需要 Python 3.12 或更高版本。将以下两个文件下载到同一目录，再在该目录执行校验安装命令。")}</Typography.Paragraph>
        <Space wrap><a href={CLI_RELEASE.installerUrl} download>{t("Download installer", "下载安装器")}</a><a href={CLI_RELEASE.artifactUrl} download>hypertest-cli-{CLI_RELEASE.version}.pyz</a><a href={CLI_RELEASE.releaseUrl} target="_blank" rel="noopener noreferrer">{t("Release notes", "发行说明")} · {CLI_RELEASE.version}</a></Space>
        <Typography.Paragraph className="archive-command" copyable={{ text: installCommand || "" }}><code>{installCommand}</code></Typography.Paragraph>
        <Typography.Paragraph className="muted">{t("The command checks the installer SHA-256 before execution; the installer separately verifies the CLI package. It installs hypertest in ~/.local/bin. Add that directory to your PATH if needed.", "命令先校验安装器 SHA-256，安装器再独立校验 CLI 包。hypertest 安装到 ~/.local/bin；如有需要，请将此目录加入 PATH。")}</Typography.Paragraph>
        <details><summary>{t("Release source and checksums", "发行源码与校验值")}</summary><Typography.Paragraph>{t("Source commit", "源码提交")}: <Typography.Text code copyable>{CLI_RELEASE.sourceCommit}</Typography.Text></Typography.Paragraph><Typography.Paragraph>Installer SHA-256: <Typography.Text code copyable>{CLI_RELEASE.installerSha256}</Typography.Text></Typography.Paragraph><Typography.Paragraph>CLI SHA-256: <Typography.Text code copyable>{CLI_RELEASE.artifactSha256}</Typography.Text></Typography.Paragraph></details>
      </> : <Typography.Paragraph>{t("Install the versioned HyperTest CLI package provided by your deployment operator. Public CLI release assets are not published yet; existing local-v packages belong to the retired sync client.", "安装部署管理员提供的固定版本 HyperTest CLI 包。公开 CLI 发行资产尚未发布；原 local-v 包属于旧同步客户端。")}</Typography.Paragraph>}
      <Typography.Title level={3}>{t("Bind to this server", "绑定此服务器")}</Typography.Title>
      {bindCommand ? <Typography.Paragraph className="archive-command" copyable={{ text: bindCommand }}><code>{bindCommand}</code></Typography.Paragraph> : <Typography.Paragraph className="muted">{t("Open this page over HTTPS, or have the deployment operator configure the CLI HTTPS address, to prepare the binding command.", "通过 HTTPS 地址打开本页，或由部署管理员配置 CLI HTTPS 地址后，可生成绑定命令。")}</Typography.Paragraph>}
      <Typography.Paragraph className="muted">{t("PENDING with exit code 4 means the CLI is waiting for your approval. Keep the original request_id, approve access at the returned link, then give the result back to your Agent to continue that request. To continue manually, replace the original ID below and run:", "返回 PENDING 和退出码 4 表示正常等待批准。请保留原 request_id，通过返回的链接批准授权，再将结果交给 Agent 继续原请求。手动继续时，请将下方原 ID 替换为该 request_id 后执行：")}</Typography.Paragraph>
      <Typography.Paragraph className="archive-command"><code>hypertest auth bind --resume --request-id &lt;{t("original ID", "原ID")}&gt; --wait-seconds 0 --json</code></Typography.Paragraph>
      <Typography.Paragraph className="muted">{t("Continue the original request instead of starting another pairing.", "请继续原请求，避免重复发起配对。")}</Typography.Paragraph>
      <Typography.Title level={3}>{t("Install the archive Skill", "安装归档 Skill")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("For Codex, use the command below. Your Agent can select its own host when using the installation prompt.", "Codex 可使用下方命令。使用安装 Prompt 时，Agent 会按当前宿主选择安装方式。")}</Typography.Paragraph>
      <Typography.Paragraph className="archive-command" copyable><code>hypertest skill install --global --host codex</code></Typography.Paragraph>
      <Typography.Paragraph className="archive-command" copyable><code>hypertest doctor</code></Typography.Paragraph>
      </details>
    </section><section className="workspace-panel cli-guide-approval"><Typography.Title level={2}>{t("Approve access, then archive when ready", "批准授权，按需归档")}</Typography.Title>
      <Typography.Paragraph>{t("The Agent opens a pairing link. Match the terminal code and approve access. Credentials stay in the CLI's private profile.", "Agent 会打开配对链接。请核对终端短码并批准访问；凭据保存在 CLI 私有 profile 中。")}</Typography.Paragraph>
      <Form layout="vertical" onFinish={() => { if (/^[a-f0-9-]{36}$/i.test(inputRequest)) window.location.assign(`/cli-authorizations?request_id=${encodeURIComponent(inputRequest)}`); }}><Form.Item label={t("Open a pairing request", "打开配对请求")}><Space.Compact style={{ width: "100%" }}><Input aria-label={t("Pairing request ID", "配对请求 ID")} value={inputRequest} onChange={(event) => setInputRequest(event.target.value)} placeholder="Request ID" /><Button htmlType="submit" disabled={!/^[a-f0-9-]{36}$/i.test(inputRequest)}>{t("Open", "打开")}</Button></Space.Compact></Form.Item></Form>
      <Typography.Paragraph>{t("After testing, copy the archive instruction from a task page. Project ID and Task ID are required; Subtask ID is optional.", "测试结束后，从任务页复制归档指令。项目 ID 和任务 ID 必填，子任务 ID 可选。")}</Typography.Paragraph><Typography.Paragraph className="muted">{t("The Skill runs only when explicitly selected. Uploading to the task root creates no default subtask. Revoke server access below; local logout only disables the local profile.", "Skill 仅在显式选择时运行。上传到根空间不会创建默认子任务。下方撤销操作终止服务器授权；本机 logout 仅停用本机 profile。")}</Typography.Paragraph>
    </section></div>
    <section className="workspace-panel cli-authorizations-list"><div className="activity-heading"><div><Typography.Title level={2}>{t("Authorized clients and projects", "已授权客户端与项目")}</Typography.Title><p className="cli-section-description">{t("Review the clients that can access your projects and manage their grants.", "查看可以访问项目的客户端并管理其授权。")}</p></div><Button loading={grants.isFetching} onClick={() => void grants.refetch()}>{t("Refresh grants", "刷新授权")}</Button></div>
      {grants.isError ? <Alert type="error" showIcon message={t("Grants could not be refreshed", "无法刷新授权")} description={errorText(grants.error, locale)} /> : null}
      {projects.isError ? <Alert type="warning" showIcon message={t("Project names are unavailable", "项目名称暂不可用")} description={t("Refresh the project list to show names for existing project grants.", "刷新项目列表后可查看既有项目授权的名称。")} action={<Button onClick={() => void projects.refetch()}>{t("Refresh projects", "刷新项目")}</Button>} /> : null}
      {setup.isLoading || (enabled && grants.isLoading) ? <Typography.Paragraph role="status" className="muted">{t("Loading authorized clients…", "正在读取已授权客户端…")}</Typography.Paragraph> : <>{grants.data && !grants.data.authorizations?.length && !grants.data.items?.length ? <Empty description={t("No CLI grants", "暂无 CLI 授权")} /> : null}<GlobalCliAuthorizations authorizations={grants.data?.authorizations || []} onChanged={changed} /><AuthorizedCliClients grants={grants.data?.items || []} projects={projects.data || []} server={cliServer || ""} canAddProject={enabled && !projects.isLoading && !projects.isError && Boolean(projects.data)} onChanged={changed} /></>}
    </section>
  </main>;
}
