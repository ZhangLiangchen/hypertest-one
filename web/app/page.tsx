"use client";

import { ArrowRightOutlined, FolderOpenOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Input, Select, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";
import dynamic from "next/dynamic";

import { errorText, getProjects } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ProjectActions } from "@/app/projects/project-actions";
import { WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";

const CreateProjectDialog = dynamic(() => import("./create-project-dialog").then((module) => module.CreateProjectDialog));

export default function DashboardPage() {
  const { t, label, locale, formatDate } = useI18n();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [createOpened, setCreateOpened] = useState(false);
  const projects = useQuery({ queryKey: ["projects", "include-deleted"], queryFn: () => getProjects(true) });
  const openCreate = () => { setCreateOpened(true); setCreateOpen(true); };

  return (
    <main className="workspace-page">
      <WorkspaceHeading title={t("Projects", "项目工作台")}
        description={t("Manage local and cloud testing tasks, cases and reports by project.", "按项目统一管理本地与云端测试任务、用例和报告。")}
        actions={<Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{t("Create project", "创建项目")}</Button>} />
      <section className="workspace-intro" aria-label={t("Testing workflow", "测试工作流")}>
        <div className="intro-mark"><FolderOpenOutlined aria-hidden /></div>
        <div><h2>{t("Keep testing work traceable.", "让测试工作，有迹可循。")}</h2><p>{t("Connect Codex, Claude Code or DeepSeek Harness locally, or use DeepSeek Harness + Codex for cloud testing. Keep tasks, plans, cases and original reports together by project.", "本地接入 Codex、Claude Code 和 DeepSeek Harness，云端支持 DeepSeek Harness + Codex 测试；任务、计划、用例与原始报告统一归档到所属项目。")}</p></div>
        <div className="workflow-labels"><span>{t("Task", "任务")}</span><ArrowRightOutlined aria-hidden /><span>{t("Cases", "用例")}</span><ArrowRightOutlined aria-hidden /><span>{t("Reports & history", "报告与历史")}</span></div>
      </section>
      <section className="data-surface" aria-label={t("Project list", "项目列表")}>
        <div className="list-toolbar">
          <h2>{status === "deleted" ? t("Project recycle bin", "项目回收站") : t("All projects", "全部项目")} <span className="count-badge">{projects.data?.filter((project) => status === "deleted" ? Boolean(project.deleted_at) : !project.deleted_at).length ?? "—"}</span></h2>
          <div className="list-filters"><Input prefix={<SearchOutlined aria-hidden />} allowClear value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("Search name, key or repository", "搜索名称、标识或仓库")} aria-label={t("Search projects", "搜索项目")} /><Select id="project-status" value={status} onChange={setStatus} aria-label={t("Project status", "项目状态")} options={[{value: "all", label: t("All statuses", "全部状态")}, {value: "ACTIVE", label: label("ACTIVE")}, {value: "ARCHIVED", label: label("ARCHIVED")}, {value: "deleted", label: t("Recycle bin", "回收站")}]} /><Button icon={<ReloadOutlined aria-hidden />} onClick={() => void projects.refetch()} loading={projects.isFetching}>{t("Refresh", "刷新")}</Button></div>
        </div>
        {projects.isError ? <div className="surface-message"><Alert type="error" showIcon message={t("Unable to load projects", "无法加载项目")} description={errorText(projects.error, locale)} action={<Button onClick={() => void projects.refetch()} loading={projects.isFetching}>{t("Retry", "重试")}</Button>} /></div> : null}
        {status === "deleted" ? <Typography.Paragraph className="table-footnote">{t("Deleted projects retain their keys and history. Restore a project here to use it again.", "已删除项目保留原标识与历史。需要继续使用时，请在此恢复。")}</Typography.Paragraph> : null}
        {projects.isLoading ? <WorkspaceLoading label={t("Loading projects…", "正在加载项目…")} /> : projects.data?.length ? <Table
          rowKey="id" pagination={{pageSize: 10, hideOnSinglePage: true}} scroll={{ x: 900 }}
          dataSource={projects.data.filter((project) => (status === "deleted" ? Boolean(project.deleted_at) : !project.deleted_at && (status === "all" || project.status === status)) && `${project.name} ${project.key} ${project.repository_url || ""} ${project.test_framework_repository_url || ""}`.toLowerCase().includes(search.trim().toLowerCase()))}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("No matching projects. Try a different search or reset the filters.", "未找到匹配项目。请修改搜索内容，或重置筛选。")}><Button onClick={() => { setSearch(""); setStatus("all"); }}>{t("Reset filters", "重置筛选")}</Button></Empty> }}
          columns={[
            {title: t("Project", "项目"), key: "name", width: "38%", sorter: (a, b) => a.name.localeCompare(b.name), render: (_, project) => <div className="project-name-cell"><span className="project-avatar" aria-hidden>{project.name.slice(0, 1).toUpperCase()}</span><div><Link className="entity-title" href={`/projects/${project.id}`}>{project.name}</Link><div className="entity-key">{project.key}</div><p className="cell-description">{project.description || t("No description", "暂无描述")}</p></div></div>},
            {title: t("SUT repository", "被测对象仓库"), key: "repository", render: (_, project) => <div className="repository-cell"><span>{project.repository_url || t("Repository not set", "尚未设置仓库")}</span></div>},
            {title: t("Test framework repository", "测试框架仓库"), key: "framework", render: (_, project) => <div className="repository-cell"><span>{project.test_framework_repository_url || t("Repository not set", "尚未设置仓库")}</span></div>},
            {title: t("Status", "状态"), key: "status", width: 120, render: (_, project) => <Tag className="project-status-tag" color={!project.deleted_at && project.status === "ACTIVE" ? "green" : undefined}>{project.deleted_at ? t("Deleted", "已删除") : label(project.status)}</Tag>},
            {title: t("Updated", "更新时间"), dataIndex: "updated_at", width: 160, sorter: (a, b) => a.updated_at.localeCompare(b.updated_at), render: formatDate},
            {title: t("Open", "打开"), key: "open", width: 65, render: (_, project) => <Link href={`/projects/${project.id}`} aria-label={`${t("Open project", "打开项目")} ${project.name}`}><ArrowRightOutlined /></Link>},
            {title: t("Actions", "操作"), key: "actions", width: 120, render: (_, project) => <ProjectActions project={project} compact />},
          ]}
        /> : projects.data ? <div className="empty-workspace"><FolderOpenOutlined aria-hidden /><h3>{t("Your first project starts here", "从第一个项目开始")}</h3><p>{t("Create a project, then connect a local Agent or set up cloud testing to manage tasks and artifacts.", "创建项目，接入本地 Agent 或配置云端测试，集中管理任务和产物。")}</p><Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate}>{t("Create project", "创建项目")}</Button></div> : null}
      </section>

      {createOpened && <CreateProjectDialog open={createOpen} onClose={() => setCreateOpen(false)} projects={projects.data || []} />}
    </main>
  );
}
