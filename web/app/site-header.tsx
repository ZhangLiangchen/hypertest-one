"use client";

import { AppstoreOutlined, ExperimentOutlined, GlobalOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import { Button, Select } from "antd";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import dynamic from "next/dynamic";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";
import { getProject } from "@/lib/api";
import type { ArchiveDetail } from "@/lib/archive";
import type { CloudDocument } from "@/lib/cloud";

const WorkflowGuide = dynamic(() => import("./workflow-guide").then((module) => module.WorkflowGuide));

export function SiteHeader() {
  const { locale, setLocale, t } = useI18n();
  const path = usePathname();
  const search = useSearchParams();
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideOpened, setGuideOpened] = useState(false);
  const projectMatch = path.match(/^\/projects\/([^/]+)(?:\/(cloud|memory|tasks\/new))?\/?$/);
  const taskMatch = path.match(/^\/(cloud-tasks|tasks|archives)\/([^/]+)\/?$/);
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  const candidateProject = projectMatch?.[1] || (taskMatch ? search.get("projectId") : "") || "";
  const projectId = uuid.test(candidateProject) ? candidateProject : "";
  const taskId = taskMatch && uuid.test(taskMatch[2]) ? taskMatch[2] : "";
  const cloudTask = taskMatch?.[1] === "cloud-tasks";
  const localTask = taskMatch?.[1] === "archives" || (taskMatch?.[1] === "tasks" && search.get("mode") === "archive");
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true), enabled: !!projectId });
  // The detail pages own these reads, including Cloud's fixed-version checks.
  const cloud = useQuery<CloudDocument>({ queryKey: ["cloud-task", projectId, taskId], enabled: false });
  const archive = useQuery<ArchiveDetail>({ queryKey: ["archive-task", projectId, taskId], enabled: false });
  const task = cloudTask ? cloud.data?.task : localTask ? archive.data?.task : undefined;
  const taskTitle = task?.id === taskId && task?.project_id === projectId ? task.title : undefined;
  const projectName = project.data?.id === projectId ? project.data.name : t("Project", "项目");
  const crumbs: { label: string; href?: string }[] = [];
  if (projectId) crumbs.push({ label: projectName, href: projectMatch && !projectMatch[2] ? undefined : `/projects/${projectId}` });
  if (projectMatch?.[2]) crumbs.push({ label: projectMatch[2] === "cloud" ? t("Cloud testing", "云端测试") : projectMatch[2] === "memory" ? t("Project experience", "项目经验") : t("Create test task", "创建测试任务") });
  if (taskMatch) {
    if (cloudTask && projectId) crumbs.push({ label: t("Cloud testing", "云端测试"), href: `/projects/${projectId}/cloud?tab=tasks` });
    crumbs.push({ label: taskTitle || (cloudTask ? t("Cloud task", "云端任务") : t("Local task", "本地任务")) });
  }
  if (path.startsWith("/cli-authorizations")) crumbs.push({ label: t("CLI authorization", "CLI 授权") });
  return <><a href="#main-content" className="skip-link">{t("Skip to content", "跳转到内容")}</a><header className="topbar">
    <Link href="/" className="brand"><ExperimentOutlined /><span>HyperTest One</span></Link>
    <nav className="topbar-nav" aria-label={t("Breadcrumb", "层级导航")}>
      <Link href="/" aria-current={path === "/" ? "page" : undefined}><AppstoreOutlined aria-hidden /> {t("Projects", "项目")}</Link>
      {crumbs.map((crumb, index) => <span className="header-crumb" key={index}><span className="header-separator" aria-hidden>/</span>{crumb.href
        ? <Link href={crumb.href} title={crumb.label}>{crumb.label}</Link>
        : <span className="header-location" aria-current="page" title={crumb.label}>{crumb.label}</span>}</span>)}
    </nav>
    <div className="topbar-actions">
      <Link href="/cli-authorizations" aria-current={path.startsWith("/cli-authorizations") ? "page" : undefined}>{t("CLI authorization", "CLI 授权")}</Link>
      <Button className="guide-button" type="text" icon={<QuestionCircleOutlined aria-hidden />} onClick={() => { setGuideOpened(true); setGuideOpen(true); }} aria-label={t("Workflow guide", "使用指南")}><span>{t("Guide", "使用指南")}</span></Button>
      <Select
        className="locale-select"
        id="interface-language"
        aria-label={t("Interface language", "界面语言")}
        value={locale}
        onChange={setLocale}
        suffixIcon={<GlobalOutlined />}
        options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]}
        popupMatchSelectWidth={120}
      />
    </div>
  </header>{guideOpened && <WorkflowGuide open={guideOpen} onClose={() => setGuideOpen(false)} />}</>;
}
