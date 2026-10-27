"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Descriptions, Empty, Form, Input, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText, getProjects } from "@/lib/api";
import { cliAuthorizationApi, validateCliApproval, validateCliRevocation, type CliGrant, type CliRequest } from "@/lib/cli-authorization";
import { useLocalWebOperation } from "@/lib/archive-operation";
import { CLI_RELEASE, cliInstallCommand } from "@/lib/cli-release";
import { cliBindCommand } from "@/lib/cli-install-prompt";
import { useI18n } from "@/lib/i18n";
import { WorkspaceHeading } from "@/app/workspace-ui";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";
import { CliInstallPrompt } from "./cli-install-prompt";

const sendApproval = (path: string, payload: Record<string, unknown>) => cliAuthorizationApi<CliRequest>(path, { method: "POST", body: JSON.stringify(payload) });
const recoverApproval = (path: string) => cliAuthorizationApi<CliRequest>(path);
const sendRevocation = (path: string, payload: Record<string, unknown>) => cliAuthorizationApi<CliGrant>(path, { method: "POST", body: JSON.stringify(payload) });
const recoverRevocation = (path: string) => cliAuthorizationApi<CliGrant>(path);
function RevokeGrant({ grant, onChanged }: { grant: CliGrant; onChanged: () => void }) {
  const { t } = useI18n();
  const operation = useLocalWebOperation("auth", "global", `revoke:${grant.grant_id}`, sendRevocation, recoverRevocation, validateCliRevocation);
  return <><Button danger disabled={operation.blocked || grant.status === "REVOKED"} loading={operation.busy} onClick={() => void operation.submit(`grants/${grant.grant_id}/revoke`, (key) => `grants/${grant.grant_id}/operations/by-key?idempotency_key=${key}`, {}).then((value) => { if (value) onChanged(); })}>{t("Revoke", "撤销")}</Button><ArchiveOperationNotice operation={operation} onAccepted={onChanged} /></>;
}
export default function CliAuthorizationsPage() {
  const { t, locale, formatDate } = useI18n(); const search = useSearchParams(); const cache = useQueryClient();
  const requestId = search.get("request_id") || ""; const projectHint = search.get("projectId") || ""; const preselectedProject = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(projectHint) ? projectHint : null;
  const [server, setServer] = useState(""), [inputRequest, setInputRequest] = useState(requestId); const [form] = Form.useForm();
  useEffect(() => { setServer(window.location.origin); }, []);
  const setup = useQuery({ queryKey: ["archive-web-setup"], queryFn: () => cliAuthorizationApi<{ configured: boolean }>("setup"), retry: false });
  const enabled = setup.data?.configured === true;
  const actors = useQuery({ queryKey: ["cli-actors"], queryFn: () => cliAuthorizationApi<{ items: { actor_identity_id: string; actor_ref: string; status: string }[] }>("actors"), enabled, retry: false });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => getProjects(), enabled, retry: false });
  const grants = useQuery({ queryKey: ["cli-grants"], queryFn: () => cliAuthorizationApi<{ items: CliGrant[] }>("grants"), enabled, retry: false });
  const request = useQuery({ queryKey: ["cli-request", requestId], queryFn: () => cliAuthorizationApi<CliRequest>(`requests/${requestId}`), enabled: enabled && Boolean(requestId), retry: false });
  const operation = useLocalWebOperation("auth", "global", `approve:${requestId}`, sendApproval, recoverApproval, validateCliApproval);
  const installCommand = cliInstallCommand();
  let bindCommand = "";
  if (server) { try { bindCommand = cliBindCommand(server, preselectedProject || undefined); } catch { /* HTTPS origin guidance is shown by the install prompt. */ } }
  const changed = () => { void cache.invalidateQueries({ queryKey: ["cli-grants"] }); void cache.invalidateQueries({ queryKey: ["cli-request", requestId] }); };
  async function approve(values: { actor_identity_id: string; project_ids: string[]; expires_in_days: number }) {
    if (!request.data || request.data.status !== "PENDING") return;
    const result = await operation.submit(`requests/${requestId}/approve`, (key) => `requests/by-key?request_id=${requestId}&operation=APPROVE&idempotency_key=${key}`,
      { actor_identity_id: values.actor_identity_id, project_ids: values.project_ids, scopes: ["archive:read", "archive:write"], expires_in_days: values.expires_in_days, short_code: request.data.short_code });
    if (result) changed();
  }
  return <main className="workspace-page"><WorkspaceHeading title={t("CLI authorization", "CLI 授权")} backHref="/" backLabel={t("Projects", "项目")} description={t("Authorize one local CLI for explicitly selected projects. Reuse it across workspaces and Agent sessions; run it only when archiving.", "为一个本地 CLI 授权明确的项目，在工作目录与 Agent 会话间复用，仅在归档时调用。")}
    actions={<Button onClick={() => { void setup.refetch(); void actors.refetch(); void grants.refetch(); if (requestId) void request.refetch(); }}>{t("Refresh", "刷新")}</Button>} />
    {setup.isError || setup.data?.configured === false ? <Alert type="warning" showIcon className="archive-operation-notice" message={t("CLI authorization is not available on this server", "此服务器尚未开放 CLI 授权")} description={t("The server operator must configure the archive Web boundary. No credential is requested or stored by this page.", "需要服务管理员配置归档 Web 入口。此页面不索取或保存凭据。") } /> : null}
    <div className="cli-bind-guide"><section id="cli-install" className="workspace-panel"><Typography.Title level={2}>{t("Let your Agent install the CLI", "让 Agent 安装 CLI")}</Typography.Title>
      <CliInstallPrompt projectId={preselectedProject || undefined} />
      <details className="cli-install-manual"><summary>{t("Manual installation and binding", "手动安装与绑定")}</summary>
      {CLI_RELEASE.published ? <>
        <Typography.Paragraph>{t("Python 3.12 or later is required. Download both files into the same directory, then run the verified installer command there.", "需要 Python 3.12 或更高版本。将以下两个文件下载到同一目录，再在该目录执行校验安装命令。")}</Typography.Paragraph>
        <Space wrap><a href={CLI_RELEASE.installerUrl} download>{t("Download installer", "下载安装器")}</a><a href={CLI_RELEASE.artifactUrl} download>hypertest-cli-{CLI_RELEASE.version}.pyz</a><a href={CLI_RELEASE.releaseUrl} target="_blank" rel="noopener noreferrer">{t("Release notes", "发行说明")} · {CLI_RELEASE.version}</a></Space>
        <Typography.Paragraph className="archive-command" copyable={{ text: installCommand || "" }}><code>{installCommand}</code></Typography.Paragraph>
        <Typography.Paragraph className="muted">{t("The command checks the installer SHA-256 before execution; the installer separately verifies the CLI package. It installs hypertest in ~/.local/bin. Add that directory to your PATH if needed.", "命令先校验安装器 SHA-256，安装器再独立校验 CLI 包。hypertest 安装到 ~/.local/bin；如有需要，请将此目录加入 PATH。")}</Typography.Paragraph>
        <details><summary>{t("Release source and checksums", "发行源码与校验值")}</summary><Typography.Paragraph>{t("Source commit", "源码提交")}: <Typography.Text code copyable>{CLI_RELEASE.sourceCommit}</Typography.Text></Typography.Paragraph><Typography.Paragraph>Installer SHA-256: <Typography.Text code copyable>{CLI_RELEASE.installerSha256}</Typography.Text></Typography.Paragraph><Typography.Paragraph>CLI SHA-256: <Typography.Text code copyable>{CLI_RELEASE.artifactSha256}</Typography.Text></Typography.Paragraph></details>
      </> : <Typography.Paragraph>{t("Install the versioned HyperTest CLI package provided by your deployment operator. Public CLI release assets are not published yet; existing local-v packages belong to the retired sync client.", "安装部署管理员提供的固定版本 HyperTest CLI 包。公开 CLI 发行资产尚未发布；原 local-v 包属于旧同步客户端。")}</Typography.Paragraph>}
      <Typography.Title level={3}>{t("Bind to this server", "绑定此服务器")}</Typography.Title>
      {bindCommand ? <Typography.Paragraph className="archive-command" copyable={{ text: bindCommand }}><code>{bindCommand}</code></Typography.Paragraph> : <Typography.Paragraph className="muted">{t("Open this page at your configured HTTPS address to prepare the binding command.", "通过配置的 HTTPS 地址打开本页后，可生成绑定命令。")}</Typography.Paragraph>}
      <Typography.Paragraph className="muted">{t("PENDING with exit code 4 means the CLI is waiting for your approval. Keep the original request_id, approve access at the returned link, then give the result back to your Agent to continue that request. To continue manually, replace the original ID below and run:", "返回 PENDING 和退出码 4 表示正常等待批准。请保留原 request_id，通过返回的链接批准授权，再将结果交给 Agent 继续原请求。手动继续时，请将下方原 ID 替换为该 request_id 后执行：")}</Typography.Paragraph>
      <Typography.Paragraph className="archive-command"><code>hypertest auth bind --resume --request-id &lt;{t("original ID", "原ID")}&gt; --wait-seconds 0 --json</code></Typography.Paragraph>
      <Typography.Paragraph className="muted">{t("Continue the original request instead of starting another pairing.", "请继续原请求，避免重复发起配对。")}</Typography.Paragraph>
      <Typography.Title level={3}>{t("Install the archive Skill", "安装归档 Skill")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("For Codex, use the command below. Your Agent can select its own host when using the installation prompt.", "Codex 可使用下方命令。使用安装 Prompt 时，Agent 会按当前宿主选择安装方式。")}</Typography.Paragraph>
      <Typography.Paragraph className="archive-command" copyable><code>hypertest skill install --global --host codex</code></Typography.Paragraph>
      <Typography.Paragraph className="archive-command" copyable><code>hypertest doctor</code></Typography.Paragraph>
      </details>
    </section><section className="workspace-panel"><Typography.Title level={2}>{t("Approve access, then archive when ready", "批准授权，按需归档")}</Typography.Title>
      <Typography.Paragraph>{t("The Agent opens a pairing link. Match the terminal code, choose the projects and approve access. Credentials stay in the CLI's private profile.", "Agent 会打开配对链接。请核对终端短码、选择项目并批准访问；凭据保存在 CLI 私有 profile 中。")}</Typography.Paragraph>
      <Form layout="vertical" onFinish={() => { if (/^[a-f0-9-]{36}$/i.test(inputRequest)) window.location.assign(`/cli-authorizations?request_id=${encodeURIComponent(inputRequest)}`); }}><Form.Item label={t("Open a pairing request", "打开配对请求")}><Space.Compact style={{ width: "100%" }}><Input aria-label={t("Pairing request ID", "配对请求 ID")} value={inputRequest} onChange={(event) => setInputRequest(event.target.value)} placeholder="Request ID" /><Button htmlType="submit" disabled={!/^[a-f0-9-]{36}$/i.test(inputRequest)}>{t("Open", "打开")}</Button></Space.Compact></Form.Item></Form>
      <Typography.Paragraph>{t("After testing, copy the archive instruction from a task page. Project ID and Task ID are required; Subtask ID is optional.", "测试结束后，从任务页复制归档指令。项目 ID 和任务 ID 必填，子任务 ID 可选。")}</Typography.Paragraph><Typography.Paragraph className="muted">{t("The Skill runs only when explicitly selected. Uploading to the task root creates no default subtask. Revoke server access below; local logout only disables the local profile.", "Skill 仅在显式选择时运行。上传到根空间不会创建默认子任务。下方撤销操作终止服务器授权；本机 logout 仅停用本机 profile。")}</Typography.Paragraph>
    </section></div>
    {requestId ? <section className="workspace-panel archive-section"><div className="activity-heading"><Typography.Title level={2}>{t("Approve this CLI", "批准此 CLI")}</Typography.Title><Button onClick={() => void request.refetch()} loading={request.isFetching}>{t("Refresh request", "刷新请求")}</Button></div>
      {request.isError ? <Alert type="error" showIcon message={t("Pairing request could not be read", "无法读取配对请求")} description={errorText(request.error, locale)} /> : null}
      {request.data ? <><Descriptions column={2} items={[
        { key: "code", label: t("Match this code in your terminal", "与终端核对短码"), children: <Typography.Text className="cli-pairing-code">{request.data.short_code}</Typography.Text> }, { key: "state", label: t("State", "状态"), children: <Tag>{request.data.status}</Tag> },
        { key: "client", label: t("Client", "客户端"), children: request.data.client_name }, { key: "server", label: t("Server", "服务器"), children: request.data.server_url },
        { key: "fingerprint", label: t("Client credential fingerprint", "客户端凭据指纹"), children: <Typography.Text code>{request.data.credential_fingerprint}</Typography.Text> }, { key: "expires", label: t("Pairing expires", "配对有效期至"), children: formatDate(request.data.expires_at) },
      ]} />
      {request.data.status === "PENDING" ? <Form form={form} layout="vertical" onFinish={approve} disabled={operation.blocked} initialValues={{ project_ids: preselectedProject ? [preselectedProject] : [], expires_in_days: 30 }} requiredMark="optional">
        <Form.Item name="actor_identity_id" label={t("Existing uploader identity", "既有上传身份")} rules={[{ required: true, message: t("Select an existing identity.", "请选择既有身份。") }]}><Select loading={actors.isLoading} options={actors.data?.items.filter((actor) => actor.status === "ACTIVE").map((actor) => ({ value: actor.actor_identity_id, label: actor.actor_ref }))} /></Form.Item>
        <Form.Item name="project_ids" label={t("Allowed projects", "允许的项目")} rules={[{ required: true, type: "array", min: 1, message: t("Explicitly select at least one project.", "请明确选择至少一个项目。") }]}><Select mode="multiple" loading={projects.isLoading} options={projects.data?.filter((project) => !project.deleted_at).map((project) => ({ value: project.id, label: `${project.name} · ${project.id}` }))} /></Form.Item>
        <Form.Item name="expires_in_days" label={t("Grant validity", "授权有效期")} rules={[{ required: true }]}><Select options={[1, 7, 30, 90].map((days) => ({ value: days, label: `${days} ${t("days", "天")}` }))} /></Form.Item>
        <Typography.Paragraph>{t("Permissions", "权限")}: <Tag>archive:read</Tag><Tag>archive:write</Tag></Typography.Paragraph>
        <Form.Item name="code_confirmed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error(t("Check the terminal code first.", "请先核对终端短码。"))) }]}><Checkbox>{t("The code matches the CLI I started, and I approve these projects and permissions.", "短码与我启动的 CLI 一致，我批准上述项目及权限。")}</Checkbox></Form.Item>
        {(actors.isError || projects.isError) ? <Alert type="error" showIcon className="archive-operation-notice" message={t("Authorization choices could not be loaded", "无法读取授权选项")} description={errorText(actors.error || projects.error, locale)} /> : null}
        <Button type="primary" htmlType="submit" loading={operation.busy} disabled={operation.blocked || actors.isError || projects.isError}>{t("Approve CLI", "批准 CLI")}</Button>
      </Form> : <Alert type={request.data.status === "BOUND" ? "success" : "info"} showIcon message={request.data.status === "BOUND" ? t("Binding completed", "绑定已完成") : request.data.status === "APPROVED" ? t("Approved. Return to the CLI to finish binding.", "已批准，请返回 CLI 完成绑定。") : t("This pairing request is closed", "此配对请求已结束")} description={request.data.approval ? `${request.data.approval.actor_ref} · ${request.data.approval.project_ids.length} ${t("projects", "个项目")} · ${formatDate(request.data.approval.expires_at)}` : undefined} />}</> : null}
      <ArchiveOperationNotice operation={operation} onAccepted={changed} />
    </section> : null}
    <section className="workspace-panel"><div className="activity-heading"><Typography.Title level={2}>{t("Authorized clients and projects", "已授权客户端与项目")}</Typography.Title><Button loading={grants.isFetching} onClick={() => void grants.refetch()}>{t("Refresh grants", "刷新授权")}</Button></div>
      {grants.isError ? <Alert type="error" showIcon message={t("Grants could not be refreshed", "无法刷新授权")} description={errorText(grants.error, locale)} /> : null}
      <Table rowKey="grant_id" loading={grants.isLoading} dataSource={grants.data?.items || []} pagination={{ pageSize: 10, hideOnSinglePage: true }} scroll={{ x: 1150 }} locale={{ emptyText: <Empty description={t("No CLI grants", "暂无 CLI 授权")} /> }} columns={[
        { title: t("Client / uploader", "客户端 / 上传身份"), key: "client", render: (_, grant) => <><Typography.Text strong>{grant.client_name}</Typography.Text><div className="entity-key">{grant.actor_ref}</div><div className="entity-key">{grant.credential_fingerprint}</div></> },
        { title: t("Project", "项目"), key: "project", render: (_, grant) => <Link href={`/projects/${grant.project_id}`}>{projects.data?.find((p) => p.id === grant.project_id)?.name || grant.project_id}</Link> }, { title: t("Scopes", "权限"), dataIndex: "scopes", render: (scopes: string[]) => scopes.join(", ") }, { title: t("Expires", "有效期至"), dataIndex: "expires_at", render: formatDate }, { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Tag>{value}</Tag> }, { title: t("Action", "操作"), key: "revoke", render: (_, grant) => <RevokeGrant grant={grant} onChanged={changed} /> },
      ]} />
    </section>
  </main>;
}
