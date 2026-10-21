"use client";

import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";

import { errorText, getProjectTasks } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { ReportedResultTag } from "@/app/tasks/task-records";

export function ProjectSessionTasks({ projectId }: { projectId: string }) {
  const { t, label, locale, formatDate } = useI18n();
  const [page, setPage] = useState(1);
  const tasks = useQuery({ queryKey: ["project-tasks", projectId, page], queryFn: () => getProjectTasks(projectId, (page - 1) * 20) });
  return <section className="session-task-section" aria-labelledby="session-tasks-heading">
    <div className="activity-heading">
      <Typography.Title id="session-tasks-heading" level={2}>{t("Codex test tasks", "Codex 测试任务")}</Typography.Title>
      <Button icon={<ReloadOutlined aria-hidden />} onClick={() => void tasks.refetch()} loading={tasks.isFetching}>{t("Refresh", "刷新")}</Button>
    </div>
    <Typography.Paragraph className="muted">{t("Each Codex session has one task. Codex performs the testing work and syncs its plan, cases and reports here.", "一个 Codex 会话对应一个任务。Codex 完成测试工作，将计划、用例和报告同步到此处。")}</Typography.Paragraph>
    {tasks.isError ? <Alert showIcon type="error" message={t("Task sync records could not be refreshed", "无法刷新任务同步记录")} description={errorText(tasks.error, locale)} action={<Button onClick={() => void tasks.refetch()}>{t("Retry", "重试")}</Button>} /> : null}
    {tasks.isLoading || tasks.data?.items.length ? <div className="data-surface"><Table
      rowKey="id" loading={tasks.isLoading} dataSource={tasks.data?.items || []} scroll={{ x: 850 }}
      pagination={{ current: page, pageSize: 20, total: tasks.data?.total || 0, onChange: setPage, hideOnSinglePage: true, showSizeChanger: false }}
      columns={[
        { title: t("Task", "任务"), key: "title", render: (_, task) => <><Link className="entity-title" href={`/tasks/${task.id}`}>{task.title}</Link><span className="session-table-source">{task.provider} · {task.session_id}</span></> },
        { title: t("Task status", "任务状态"), dataIndex: "status", width: 125, render: (status: string) => <Tag color={status === "BLOCKED" ? "gold" : status === "IN_PROGRESS" ? "blue" : undefined}>{label(status)}</Tag> },
        { title: t("Codex reported result", "Codex 报告结果"), dataIndex: "reported_result", width: 160, render: (result) => <ReportedResultTag result={result} /> },
        { title: t("Version", "版本"), dataIndex: "version", width: 80 },
        { title: t("Last synced", "最后同步"), dataIndex: "last_synced_at", width: 190, render: formatDate },
      ]}
    /></div> : tasks.data ? <div className="data-surface session-task-empty"><Empty description={t("No Codex tasks have been synced to this project.", "此项目尚未同步 Codex 测试任务。")} /><Typography.Paragraph className="muted">{t("Use hypertest_sync_task in the Codex session to sync the task, cases and original report.", "在 Codex 会话中使用 hypertest_sync_task，同步任务、用例和原始报告。")}</Typography.Paragraph></div> : null}
    {tasks.data ? <Typography.Paragraph className="table-footnote">{t("Results are reported by Codex. Task status tracks progress; report revisions preserve earlier outcomes.", "结果来自 Codex 报告。任务状态表示进度，报告修订保留此前结果。")}</Typography.Paragraph> : null}
  </section>;
}
