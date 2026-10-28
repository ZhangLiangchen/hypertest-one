"use client";
import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useState } from "react";
import { getArchiveTasks } from "@/lib/archive";
import { errorText } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { archiveTaskHref } from "@/lib/task-url";
import { ReportedResultTag } from "@/app/tasks/task-records";
import { LocalModeGuide } from "./local-mode-guide";
export function ProjectArchiveTasks({ projectId, projectDeleted }: { projectId: string; projectDeleted: boolean }) {
  const { t, locale, formatDate, label } = useI18n(); const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ["archive-tasks", projectId, page], queryFn: () => getArchiveTasks(projectId, (page - 1) * 20), retry: false });
  return <section className="session-task-section" aria-labelledby="archive-tasks-heading">
    <div className="activity-heading"><Typography.Title id="archive-tasks-heading" level={2}>{t("Local test tasks", "本地测试任务")}</Typography.Title><Button icon={<ReloadOutlined aria-hidden />} onClick={() => void query.refetch()} loading={query.isFetching}>{t("Refresh", "刷新")}</Button></div>
    <Typography.Paragraph className="muted">{t("Finish testing locally, then explicitly archive selected plans, cases and reports. One task can hold artifacts from several sessions, with optional subtasks.", "在本地完成测试后，显式归档选定的计划、用例和报告。一个任务可保存多个会话的产物，子任务按需创建。")}</Typography.Paragraph>
    <LocalModeGuide projectId={projectId} />
    {query.isError ? <Alert type="error" showIcon message={t("Archives could not be refreshed", "无法刷新归档任务")} description={errorText(query.error, locale)} action={<Button onClick={() => void query.refetch()}>{t("Retry", "重试")}</Button>} /> : null}
    <div className="data-surface"><Table rowKey="id" loading={query.isLoading} dataSource={query.data?.items || []} pagination={{ current: page, pageSize: 20, total: query.data?.total || 0, onChange: setPage, hideOnSinglePage: true, showSizeChanger: false }} scroll={{ x: 1050 }}
      locale={{ emptyText: <Empty description={t("No local test tasks yet", "暂无本地测试任务")} /> }}
      columns={[
        { title: t("Task", "任务"), key: "task", render: (_, task) => <><Link className="entity-title" href={archiveTaskHref(task.id, projectId)}>{task.title}</Link><div><Typography.Text className="entity-key" copyable>{task.id}</Typography.Text></div></> },
        { title: t("Status", "状态"), dataIndex: "status", render: (value: string) => <Tag>{label(value)}</Tag> },
        { title: t("Published result", "已发布汇总结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> },
        { title: t("Uploader", "上传身份"), dataIndex: "owner_uploader_actor_ref", render: (value: string | null) => value ? <Typography.Text className="entity-key">{value}</Typography.Text> : <Tag color="gold">{t("Not authorized", "待授权")}</Tag> },
        { title: t("Root version", "根归档版本"), dataIndex: "archive_version", render: (value: number) => `v${value}` },
        { title: t("Updated", "更新时间"), dataIndex: "updated_at", render: formatDate },
      ]} /></div>
  </section>;
}
