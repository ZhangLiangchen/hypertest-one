"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Empty, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";

import { errorText, getProjectTasks } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ReportedResultTag } from "@/app/tasks/task-records";
import { SessionTaskActions } from "@/app/tasks/task-actions";


export function ProjectSessionTasks({ projectId, projectDeleted = false }: { projectId: string; projectDeleted?: boolean }) {
  const { t, label, locale, formatDate } = useI18n();
  const [page, setPage] = useState(1);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const effectiveIncludeDeleted = includeDeleted || projectDeleted;
  const tasks = useQuery({ queryKey: ["project-tasks", projectId, page, effectiveIncludeDeleted], queryFn: () => getProjectTasks(projectId, (page - 1) * 20, 20, effectiveIncludeDeleted) });
  useEffect(() => {
    if (!tasks.data) return;
    const lastPage = Math.max(1, Math.ceil(tasks.data.total / 20));
    if (page > lastPage) setPage(lastPage);
  }, [tasks.data, page]);
  return <section className="session-task-section" aria-labelledby="session-tasks-heading">
    <div className="activity-heading">
      <Typography.Title id="session-tasks-heading" level={2}>{t("Local session tasks", "本地会话任务")}</Typography.Title>
      <Space wrap><Checkbox checked={effectiveIncludeDeleted} disabled={projectDeleted} onChange={(event) => { setIncludeDeleted(event.target.checked); setPage(1); }}>{t("Include recycle bin tasks", "显示回收站任务")}</Checkbox><Button icon={<ReloadOutlined aria-hidden />} onClick={() => void tasks.refetch()} loading={tasks.isFetching}>{t("Refresh", "刷新")}</Button></Space>
    </div>
    <Typography.Paragraph className="muted">{t("Previously synchronized plans, cases and reports retain their original session identity. New local work uses explicit CLI archives.", "已同步的计划、用例和报告保留原会话身份。新的本地工作使用 CLI 显式归档。")}</Typography.Paragraph>
    {effectiveIncludeDeleted ? <Typography.Paragraph className="table-footnote">{t("Deleted tasks are shown alongside active tasks. Restore a task to continue using its original session and history.", "回收站任务与未删除任务一并显示。恢复后可继续使用原会话及历史。")}</Typography.Paragraph> : null}
    {tasks.isError ? <Alert showIcon type="error" message={t("Task sync records could not be refreshed", "无法刷新任务同步记录")} description={errorText(tasks.error, locale)} action={<Button onClick={() => void tasks.refetch()}>{t("Retry", "重试")}</Button>} /> : null}
    {tasks.isLoading || tasks.data?.items.length || (tasks.data?.total || 0) > 0 ? <div className="data-surface"><Table
      rowKey="id" loading={tasks.isLoading} dataSource={tasks.data?.items || []} scroll={{ x: 1250 }}
      pagination={{ current: page, pageSize: 20, total: tasks.data?.total || 0, onChange: setPage, hideOnSinglePage: true, showSizeChanger: false }}
      columns={[
        { title: t("Task", "任务"), key: "title", render: (_, task) => <><Link className="entity-title" href={`/tasks/${task.id}`}>{task.title}</Link>{task.deleted_at ? <Tag>{t("Deleted", "已删除")}</Tag> : null}<div><Typography.Text className="entity-key" copyable={{ text: task.id }}>{task.id}</Typography.Text></div><span className="session-table-source">{task.session_id ? `${task.provider} · ${task.session_id}` : t("No Agent session bound", "尚未绑定 Agent 会话")}</span></> },
        { title: t("Session binding", "会话绑定"), key: "binding", width: 125, render: (_, task) => <Tag color={task.binding_state === "UNBOUND" ? "gold" : "green"}>{task.binding_state === "UNBOUND" ? t("Awaiting binding", "待绑定") : t("Bound", "已绑定")}</Tag> },
        { title: t("Task status", "任务状态"), dataIndex: "status", width: 125, render: (status: string) => <Tag color={status === "BLOCKED" ? "gold" : status === "IN_PROGRESS" ? "blue" : undefined}>{label(status)}</Tag> },
        { title: t("Agent reported result", "Agent 报告结果"), dataIndex: "reported_result", width: 160, render: (result) => <ReportedResultTag result={result} /> },
        { title: t("Version", "版本"), dataIndex: "version", width: 80 },
        { title: t("Last synced", "最后同步"), dataIndex: "last_synced_at", width: 190, render: formatDate },
        { title: t("Last managed", "最近人工管理"), dataIndex: "last_managed_at", width: 190, render: (value?: string | null) => value ? formatDate(value) : "—" },
        { title: t("Actions", "操作"), key: "actions", width: 120, render: (_, task) => projectDeleted ? <Typography.Text className="muted">{t("Restore project first", "请先恢复项目")}</Typography.Text> : <SessionTaskActions task={task} compact /> },
      ]}
    /></div> : tasks.data ? <div className="data-surface session-task-empty"><Empty description={effectiveIncludeDeleted ? t("No tasks or deleted tasks in this project.", "此项目暂无任务或回收站任务。") : t("No local session tasks in this project.", "此项目暂无本地会话任务。")} /><Typography.Paragraph className="muted">{t("New local work is stored under Local test archives. Existing session records remain in this history.", "新的本地工作保存在“本地测试归档”。已有会话记录保留于此历史入口。")}</Typography.Paragraph></div> : null}
    {tasks.data ? <Typography.Paragraph className="table-footnote">{t("Results are reported by the source Agent. Task status tracks progress; report revisions preserve earlier outcomes.", "结果来自来源 Agent 的报告。任务状态表示进度，报告修订保留此前结果。")}</Typography.Paragraph> : null}
  </section>;
}
