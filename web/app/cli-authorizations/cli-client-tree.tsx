"use client";
import { CopyOutlined, DownOutlined, FolderOutlined, LaptopOutlined, PlusOutlined, RightOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Select, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { cliAuthorizationApi, validateCliRevocation, type CliGrant } from "@/lib/cli-authorization";
import { useLocalWebOperation } from "@/lib/archive-operation";
import { cliProjectAuthorizationPrompt, groupCliGrants, type CliClientGroup } from "@/lib/cli-project-authorization";
import { useI18n } from "@/lib/i18n";
import type { Project } from "@/lib/types";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";

const sendRevocation = (path: string, payload: Record<string, unknown>) => cliAuthorizationApi<CliGrant>(path, { method: "POST", body: JSON.stringify(payload) });
const recoverRevocation = (path: string) => cliAuthorizationApi<CliGrant>(path);

function RevokeGrant({ grant, onChanged }: { grant: CliGrant; onChanged: () => void }) {
  const { t } = useI18n();
  const operation = useLocalWebOperation("auth", "global", `revoke:${grant.grant_id}`, sendRevocation, recoverRevocation, validateCliRevocation);
  return <div className="cli-grant-actions"><Button danger size="small" disabled={operation.blocked || grant.status === "REVOKED"} loading={operation.busy} onClick={() => void operation.submit(`grants/${grant.grant_id}/revoke`, (key) => `grants/${grant.grant_id}/operations/by-key?idempotency_key=${key}`, {}).then((value) => { if (value) onChanged(); })}>{t("Revoke", "撤销")}</Button><ArchiveOperationNotice operation={operation} onAccepted={onChanged} /></div>;
}

function GrantStatus({ status }: { status: string }) {
  const { t } = useI18n();
  const label = status === "ACTIVE" ? t("Active", "有效") : status === "REVOKED" ? t("Revoked", "已撤销") : status === "EXPIRED" ? t("Expired", "已过期") : status;
  return <Tag color={status === "ACTIVE" ? "green" : undefined}>{label}</Tag>;
}

export function AddCliProject({ client, projects, server, onClose }: { client: CliClientGroup; projects: Project[]; server: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const id = useId();
  const [projectId, setProjectId] = useState<string>();
  const [expanded, setExpanded] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const activeProjects = new Set(client.projects.filter((project) => project.grants.some((grant) => grant.status === "ACTIVE")).map((project) => project.project_id));
  const available = projects.filter((project) => !project.deleted_at && !activeProjects.has(project.id));
  const selectedProject = available.find((project) => project.id === projectId);
  useEffect(() => { setCopyState("idle"); }, [projectId, locale, server]);
  let prompt = "", invalid = false;
  if (selectedProject && server) {
    try { prompt = cliProjectAuthorizationPrompt({ server, clientInstanceId: client.client_instance_id, actorRef: client.actor_ref, projectId: selectedProject.id, locale }); }
    catch { invalid = true; }
  }
  async function copy() {
    if (!prompt) return;
    try { await navigator.clipboard.writeText(prompt); setCopyState("copied"); }
    catch { setCopyState("failed"); setExpanded(true); }
  }
  return <section className="cli-add-project" aria-labelledby={`${id}-title`}>
    <div className="cli-add-project-heading"><h3 id={`${id}-title`}>{t("Add project access", "添加项目授权")}</h3><Button type="text" size="small" onClick={onClose}>{t("Close", "收起")}</Button></div>
    <Typography.Paragraph className="muted">{t("Choose a project and give the prompt to the Agent on this client. It reuses the existing CLI profile and opens a new pairing request for you to approve.", "选择项目，将 Prompt 交给此客户端上的 Agent。它会复用现有 CLI 配置并发起新配对，待你核对短码后批准。")}</Typography.Paragraph>
    {available.length ? <>
      <label className="cli-add-project-label" htmlFor={`${id}-project`}>{t("Project to authorize", "待授权项目")}</label>
      <div className="cli-add-project-controls"><Select id={`${id}-project`} autoFocus showSearch optionFilterProp="label" value={selectedProject?.id} onChange={setProjectId} placeholder={t("Choose a project", "选择项目")} options={available.map((project) => ({ value: project.id, label: `${project.name} · ${project.id}` }))} /><Button type="primary" icon={<CopyOutlined aria-hidden />} disabled={!prompt} onClick={() => void copy()}>{t("Copy authorization prompt", "复制授权 Prompt")}</Button></div>
      <div className="cli-add-project-feedback" role="status" aria-live="polite">{copyState === "copied" ? t("Copied. Paste it into the Agent on this client.", "已复制，请粘贴到此客户端的 Agent 会话。") : t("Existing project grants stay in place. New access takes effect after approval and CLI confirmation.", "已有项目授权保留；新增权限在网页批准并由 CLI 确认后生效。")}</div>
      {invalid ? <Alert type="warning" showIcon message={t("Authorization prompt could not be prepared", "无法生成授权 Prompt")} description={t("Refresh the client list and open HyperTest One at its configured HTTPS address.", "请刷新客户端列表，并通过配置的 HTTPS 地址打开 HyperTest One。") } /> : null}
      {copyState === "failed" ? <Alert type="warning" showIcon message={t("Clipboard access failed", "无法写入剪贴板")} description={t("Select the prompt below and copy it manually.", "请选中下方 Prompt，手动复制。") } /> : null}
      {prompt ? <details className="cli-install-prompt-details" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>{t("Read or manually copy the prompt", "查看或手动复制 Prompt")}</summary><textarea aria-label={t("Add project authorization prompt", "新增项目授权 Prompt")} className="cli-install-prompt-text" readOnly value={prompt} rows={10} spellCheck={false} onFocus={(event) => event.currentTarget.select()} /></details> : null}
    </> : <Typography.Paragraph>{t("This client already has access to every available project. Create a project, then refresh this page to add it.", "此客户端已获准访问全部可用项目。创建新项目后，刷新此页面即可添加。")}</Typography.Paragraph>}
  </section>;
}

function CliClient({ client, projects, server, canAddProject, onChanged }: { client: CliClientGroup; projects: Project[]; server: string; canAddProject: boolean; onChanged: () => void }) {
  const { t, formatDate } = useI18n();
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  const [addingProject, setAddingProject] = useState(false);
  const [addMounted, setAddMounted] = useState(false);
  const activeCount = client.projects.filter((project) => project.grants.some((grant) => grant.status === "ACTIVE")).length;
  return <li className="cli-client-node">
    <div className="cli-client-heading"><button type="button" className="cli-client-toggle" aria-expanded={expanded} aria-controls={`${id}-projects`} onClick={() => setExpanded(!expanded)}>
      {expanded ? <DownOutlined aria-hidden className="cli-client-caret" /> : <RightOutlined aria-hidden className="cli-client-caret" />}<LaptopOutlined aria-hidden className="cli-client-icon" />
      <span className="cli-client-label"><strong>{client.client_name}</strong><span className="cli-client-identity">{t("Client ID", "客户端 ID")}: <code>{client.client_instance_id}</code></span></span>
      <span className="cli-client-count">{activeCount} {t("active projects", "个有效项目")}<span>{client.projects.length} {t("projects in total", "个项目记录")}</span></span>
    </button><Button icon={<PlusOutlined aria-hidden />} disabled={!canAddProject} aria-expanded={addingProject} aria-controls={`${id}-add`} onClick={() => { setAddMounted(true); setAddingProject(!addingProject); setExpanded(true); }}>{t("Add project", "添加项目")}</Button></div>
    <div id={`${id}-add`} hidden={!addingProject}>{addMounted ? <AddCliProject client={client} projects={projects} server={server} onClose={() => setAddingProject(false)} /> : null}</div>
    <div id={`${id}-projects`} hidden={!expanded}><ul className="cli-project-children">
      {client.projects.map((projectGroup) => {
        const project = projects.find((item) => item.id === projectGroup.project_id);
        return <li className="cli-project-node" key={projectGroup.project_id}><div className="cli-project-heading"><FolderOutlined aria-hidden /><div><Link href={`/projects/${projectGroup.project_id}`}>{project?.name || projectGroup.project_id}</Link><div className="entity-key">{projectGroup.project_id}</div></div>{project?.deleted_at ? <Tag>{t("Deleted project", "已删除项目")}</Tag> : null}{projectGroup.grants.length > 1 ? <span className="cli-record-count">{projectGroup.grants.length} {t("grant records", "条授权记录")}</span> : null}</div>
          <ul className="cli-grant-records">{projectGroup.grants.map((grant) => <li className="cli-grant-record" key={grant.grant_id}>
            <div className="cli-grant-summary"><Space size={8} wrap><GrantStatus status={grant.status} /><span>{t("Valid until", "有效期至")} {formatDate(grant.expires_at)}</span></Space><div className="cli-grant-meta"><span>{grant.scopes.join(" · ")}</span><span>{t("Credential", "凭据指纹")}: <code>{grant.credential_fingerprint}</code></span></div></div>
            <RevokeGrant grant={grant} onChanged={onChanged} />
          </li>)}</ul>
        </li>;
      })}
    </ul></div>
  </li>;
}

export function AuthorizedCliClients({ grants, projects, server, canAddProject, onChanged }: { grants: CliGrant[]; projects: Project[]; server: string; canAddProject: boolean; onChanged: () => void }) {
  const { t } = useI18n();
  const clients = groupCliGrants(grants);
  if (!clients.length) return <Empty description={t("No CLI grants", "暂无 CLI 授权")} />;
  return <ul className="cli-client-tree" aria-label={t("Clients and authorized projects", "客户端及已授权项目")}>{clients.map((client) => <CliClient key={client.key} client={client} projects={projects} server={server} canAddProject={canAddProject} onChanged={onChanged} />)}</ul>;
}
