"use client";

import { ArrowLeftOutlined, CloudOutlined, DatabaseOutlined, LaptopOutlined } from "@ant-design/icons";
import { Skeleton, Typography } from "antd";
import Link from "next/link";
import type { ReactNode } from "react";

import { useI18n } from "@/lib/i18n";

/** A single title and action hierarchy for every workspace. */
export function WorkspaceHeading({ title, description, backHref, backLabel, actions, metadata }: {
  title: ReactNode;
  description?: ReactNode;
  backHref?: string;
  backLabel?: ReactNode;
  actions?: ReactNode;
  metadata?: ReactNode;
}) {
  return <div className="page-heading workspace-heading">
    {backHref ? <Link className="back-link" href={backHref}><ArrowLeftOutlined aria-hidden /> {backLabel}</Link> : null}
    <div className="workspace-heading-row">
      <div className="workspace-heading-copy">
        <Typography.Title level={1}>{title}</Typography.Title>
        {description ? <Typography.Paragraph className="muted page-intro">{description}</Typography.Paragraph> : null}
      </div>
      {actions ? <div className="workspace-heading-actions">{actions}</div> : null}
    </div>
    {metadata ? <div className="workspace-metadata">{metadata}</div> : null}
  </div>;
}

/** Project resources share a workspace; Local and Cloud retain distinct task identities. */
export function ProjectNavigation({ projectId, active }: { projectId: string; active: "local" | "cloud" | "memory" }) {
  const { t } = useI18n();
  const items = [
    { key: "local", href: `/projects/${projectId}`, icon: <LaptopOutlined aria-hidden />, label: t("Local tasks", "本地任务") },
    { key: "cloud", href: `/projects/${projectId}/cloud?tab=tasks`, icon: <CloudOutlined aria-hidden />, label: t("Cloud testing", "云端测试") },
    { key: "memory", href: `/projects/${projectId}/memory`, icon: <DatabaseOutlined aria-hidden />, label: t("Project experience", "项目经验") },
  ];
  return <nav className="project-navigation" aria-label={t("Project navigation", "项目导航")}>
    {items.map((item) => <Link key={item.key} href={item.href} aria-current={active === item.key ? "page" : undefined}>{item.icon}<span>{item.label}</span></Link>)}
  </nav>;
}

export function WorkspaceLoading({ label }: { label: string }) {
  return <div className="workspace-loading" role="status" aria-label={label}>
    <span className="muted">{label}</span>
    <Skeleton active title={{ width: "38%" }} paragraph={{ rows: 4 }} />
  </div>;
}
