"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Table, Tabs, Tag, Typography } from "antd";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getProject } from "@/lib/api";
import { cloudCapabilities, cloudConfiguration, cloudCredentials, cloudDirectory, cloudProgressTone, cloudSetup } from "@/lib/cloud";
import { useCloudOperation } from "@/lib/cloud-operation";
import { useI18n } from "@/lib/i18n";
import { ReportedResultTag } from "@/app/tasks/task-records";
import { ProjectNavigation, WorkspaceLoading } from "@/app/workspace-ui";
import { ProjectWorkspaceHeading } from "../../project-workspace-heading";
import { CloudCapabilitiesNotice, CloudOperationNotice } from "./cloud-shared";

function LoadingPanel() {
  const { t } = useI18n();
  return <WorkspaceLoading label={t("Loading form…", "正在加载表单…")} />;
}
const CloudResources = dynamic(() => import("./resources").then((module) => module.CloudResources), { loading: LoadingPanel });

export default function CloudProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const search = useSearchParams(); const requestedTab = search.get("tab");
  const { t, label, formatDate } = useI18n(); const [tab, setTab] = useState(["tasks", "resources"].includes(requestedTab || "") ? requestedTab! : "tasks"); const [page, setPage] = useState(1);
  const operation = useCloudOperation(projectId);
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true) });
  const setup = useQuery({ queryKey: ["cloud-web-setup"], queryFn: cloudSetup });
  const configured = setup.data?.configured === true;
  const capabilities = useQuery({ queryKey: ["cloud-capabilities"], queryFn: cloudCapabilities, enabled: configured });
  const configuration = useQuery({ queryKey: ["cloud-config", projectId], queryFn: () => cloudConfiguration(projectId), enabled: configured });
  const credentials = useQuery({ queryKey: ["cloud-credentials", projectId], queryFn: () => cloudCredentials(projectId), enabled: configured });
  const tasks = useQuery({ queryKey: ["cloud-directory", projectId, "CLOUD", page], queryFn: () => cloudDirectory(projectId, "CLOUD", (page - 1) * 20), enabled: configured });
  const latest = configuration.data?.items.slice().sort((a, b) => b.revision - a.revision)[0];
  useEffect(() => { if (tasks.data && page > Math.max(1, Math.ceil(tasks.data.total / 20))) setPage(Math.max(1, Math.ceil(tasks.data.total / 20))); }, [tasks.data, page]);
  const enabled = capabilities.data?.enabled === true && project.isSuccess && !project.isError && !project.data?.deleted_at;
  function refresh() { void configuration.refetch(); void credentials.refetch(); void tasks.refetch(); void capabilities.refetch(); }
  return <main className="workspace-page">
    <ProjectWorkspaceHeading project={project.data} projectId={projectId} mode="cloud" />
    <ProjectNavigation projectId={projectId} active="cloud" />
    {setup.isLoading ? <WorkspaceLoading label={t("Checking Cloud access", "正在检查云端访问")} /> : <CloudCapabilitiesNotice configured={configured} capabilities={capabilities.data} />}
    {project.isError || project.data?.deleted_at ? <Alert showIcon type="error" style={{ marginTop: 20 }} message={project.data?.deleted_at ? t("Project is in the recycle bin", "项目已在回收站") : t("Project could not be read", "无法读取项目")}
      description={t("Drafts and loaded records are retained. Return to the project workspace to restore the project or check access before creating or changing Cloud resources.", "保留草稿及已加载记录。请返回项目工作台恢复项目或核对访问权限后，再创建任务或修改云端资源。")}
      action={<Link href={`/projects/${projectId}`}>{t("Open project", "打开项目")}</Link>} /> : null}
    {setup.isError || capabilities.isError || configuration.isError || credentials.isError || tasks.isError ? <Alert showIcon type="warning" style={{ marginTop: 20 }} message={t("Some Cloud records could not be refreshed", "部分云端记录无法刷新")} description={t("Loaded records and drafts remain visible. Refresh to verify current access and versions.", "已加载记录和草稿保留；请刷新核对当前访问与版本。 ")} /> : null}
    <div style={{ marginTop: 24 }}><CloudOperationNotice operation={operation} /></div>
    <Tabs className="workspace-tabs" activeKey={tab} onChange={setTab} animated={false} items={[
      { key: "tasks", label: t("Project tasks", "项目任务"), children: <section aria-labelledby="cloud-task-list-heading">
        <div className="activity-heading"><Typography.Title id="cloud-task-list-heading" level={2}>{t("Cloud test tasks", "云端测试任务")}</Typography.Title><Button icon={<ReloadOutlined aria-hidden />} onClick={refresh} disabled={!configured}>{t("Refresh", "刷新")}</Button></div>
        <div className="data-surface"><Table rowKey={(row) => `${row.task_kind}:${row.task_id}`} loading={tasks.isLoading && configured} dataSource={tasks.data?.items || []} scroll={{ x: 850 }}
          locale={{ emptyText: <Empty description={configured ? t("No tasks match this source.", "此来源尚无任务。") : t("Configure Cloud Web access to read this directory. Local tasks remain in the project workspace.", "配置云端 Web 访问后可读取此目录；Local 任务仍在项目工作台。 ")} /> }}
          pagination={{ current: page, pageSize: 20, total: tasks.data?.total || 0, hideOnSinglePage: true, showSizeChanger: false, onChange: setPage }} columns={[
            { title: t("Task", "任务"), key: "title", render: (_, row) => <Link className="entity-title" href={`/cloud-tasks/${row.task_id}?projectId=${projectId}`}>{String(row.title)}</Link> },
            { title: t("Source", "来源"), key: "source", render: (_, row) => <><Tag>Cloud</Tag><span>{row.provider ? String(row.provider) : "—"}</span></> },
            { title: t("Task progress", "任务进度"), dataIndex: "status", render: (value: string) => <Tag color={cloudProgressTone(value)}>{label(value)}</Tag> },
            { title: t("Reported test result", "报告的测试结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> },
            { title: t("Version", "版本"), dataIndex: "version" }, { title: t("Updated", "更新时间"), dataIndex: "updated_at", render: (value: string) => formatDate(value) },
          ]} /></div>
      </section> },
      { key: "resources", label: t("Project resources", "项目资源"), children: <CloudResources key={projectId} project={project.data} latest={latest} credentials={credentials.data?.credentials || []} versions={credentials.data?.versions || []} operation={operation} enabled={enabled} onSaved={refresh} /> },
    ]} />
  </main>;
}
