"use client";

import { ArrowLeftOutlined, ArrowRightOutlined, BranchesOutlined, PlusOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Empty, Space, Spin, Table, Tag, Typography } from "antd";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { errorText, getProject, getProjectRuns } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ProjectSessionTasks } from "./session-tasks";
import { ProjectActions } from "../project-actions";
import { ProjectNavigation, WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";

const RunCreateDialog = dynamic(() => import("./run-create-dialog"), {
  ssr: false,
  loading: () => <div role="status" style={{ position: "fixed", top: 96, right: 32, zIndex: 1001 }}><Spin /></div>,
});

export default function ProjectPage() {
  const { t, label, locale, formatDate } = useI18n();
  const params = useParams<{ projectId: string }>();
  const searchParams = useSearchParams();
  const fromRun = searchParams.get("fromRun");
  const [createMounted, setCreateMounted] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [hasDraft, setHasDraft] = useState(false);
  const project = useQuery({
    queryKey: ["project", params.projectId],
    queryFn: () => getProject(params.projectId, true),
  });
  const runs = useQuery({
    queryKey: ["project-runs", params.projectId],
    queryFn: () => getProjectRuns(params.projectId),
    enabled: Boolean(project.data && !project.data.deleted_at),
  });
  const openCreate = () => {
    setCreateMounted(true);
    setCreateOpen(true);
  };

  if (project.isLoading) return <WorkspaceLoading label={t("Loading project", "正在读取项目")} />;
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

  const createLabel = hasDraft ? t("Continue draft", "继续创建草稿") : t("Create test run", "创建测试运行");

  return (
    <main className="workspace-page">
      <WorkspaceHeading backHref="/" backLabel={t("Projects", "项目")} title={project.data.name}
        description={project.data.description || t("Project testing workspace", "项目测试工作台")}
        actions={<Space wrap><ProjectActions project={project.data} /><Button type="primary" icon={<PlusOutlined aria-hidden />} href={project.data.deleted_at ? undefined : `/projects/${params.projectId}/tasks/new`} disabled={Boolean(project.data.deleted_at)}>{t("Create test task", "创建测试任务")}</Button></Space>}
        metadata={<>
          <span className="muted">{t("Project key", "项目标识")}: <span className="entity-key">{project.data.key}</span></span>
          <Tag color="blue">{label(project.data.status)}</Tag>
          <Tag icon={<BranchesOutlined aria-hidden />}>{project.data.default_branch}</Tag>
          {project.data.repository_url ? <Tag style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{project.data.repository_url}</Tag> : null}
        </>} />
      <ProjectNavigation projectId={params.projectId} active="local" />

      {project.data.deleted_at ? <Alert type="warning" showIcon message={t("This project is in the recycle bin", "此项目已移入回收站")} description={t("History remains readable. Restore the project to edit it or continue task synchronization.", "历史仍可查看。请先恢复项目，再编辑或继续同步任务。") } style={{ marginBottom: 20 }} /> : null}

      {project.error ? <Alert type="warning" showIcon message={t("Project refresh failed", "项目刷新失败")} description={t("Previously loaded project details and your draft remain available. Retry to get the latest state.", "已加载的项目资料和草稿仍会保留，请重试获取最新状态。")} action={<Button onClick={() => void project.refetch()} loading={project.isFetching}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 20 }} /> : null}

      {(createMounted || fromRun || hasDraft) && <RunCreateDialog key={params.projectId} project={project.data} fromRun={fromRun} createOpen={createOpen} setCreateOpen={setCreateOpen} onDraftChange={setHasDraft} />}
      <ProjectSessionTasks projectId={params.projectId} projectDeleted={Boolean(project.data.deleted_at)} />

      <details className="session-legacy-history" open={fromRun ? true : undefined}>
        <summary>{t("Managed test run history", "受管测试运行历史")}</summary>
      <Space wrap style={{ display: "flex", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>{t("Test runs", "测试运行")}</Typography.Title>
          <Typography.Text className="muted">{t("Each run fixes the source, requirements and policy for a reproducible test cycle.", "每次运行固定代码版本、需求和策略，形成可复现的完整测试周期。")}</Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate} disabled={Boolean(project.data.deleted_at)}>{createLabel}</Button>
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
        <div className="data-surface"><Table rowKey="id" dataSource={runs.data} pagination={{pageSize: 10, hideOnSinglePage: true}} scroll={{x: 780}} columns={[
          {title: t("Test run", "测试运行"), key: "run", render: (_, run) => <Link className="entity-title" href={`/runs/${run.id}`}>{run.key}</Link>},
          {title: t("Run status", "运行状态"), dataIndex: "status", filters: [...new Set(runs.data.map((run) => run.status))].map((status) => ({text: label(status), value: status})), onFilter: (value, run) => run.status === value, render: (value: string) => <Tag color={["FAILED", "BLOCKED"].includes(value) ? "red" : value === "COMPLETED" ? undefined : "blue"}>{label(value)}</Tag>},
          {title: t("Source snapshot", "源码快照"), dataIndex: "source_snapshot_id", render: (value: string) => <span className="entity-key">{value}</span>},
          {title: t("Created", "创建时间"), dataIndex: "created_at", defaultSortOrder: "descend", sorter: (a, b) => a.created_at.localeCompare(b.created_at), render: formatDate},
          {title: t("Open", "打开"), key: "open", width: 65, render: (_, run) => <Link href={`/runs/${run.id}`} aria-label={`${t("Open test run", "打开测试运行")} ${run.key}`}><ArrowRightOutlined /></Link>},
        ]} /><p className="table-footnote">{t("Run status tracks the workflow. Open a run to see its quality verdict and supporting evidence.", "运行状态表示流程进度。打开运行，查看质量判定及其证据依据。")}</p></div>
      ) : (
        <Card className="section-card">
          <Empty description={t("Create a test run to analyze requirements and build test coverage.", "创建测试运行，开始分析需求并建立测试覆盖。")}>
            <Button type="primary" icon={<PlusOutlined aria-hidden />} onClick={openCreate} disabled={Boolean(project.data.deleted_at)}>{createLabel}</Button>
          </Empty>
        </Card>
      )}
      </details>

    </main>
  );
}
