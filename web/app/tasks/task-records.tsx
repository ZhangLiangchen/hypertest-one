"use client";

import { Descriptions, Empty, Pagination, Space, Table, Tag, Typography } from "antd";
import { useMemo, useState, type ReactNode } from "react";

import { useI18n } from "@/lib/i18n";
import type { ReportedResult, SessionCaseRevision, SessionReportRevision, SessionTaskDetail } from "@/lib/types";

// Native <details> hides DOM visually but still eagerly renders its children.
// Keep large accepted artifacts and snapshots out of React/DOM until requested.
function DeferredDetails({ summary, children, className }: { summary: ReactNode; children: () => ReactNode; className?: string }) {
  const [open, setOpen] = useState(false);
  return <details className={className} open={open} onToggle={(event) => {
    if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
  }}><summary>{summary}</summary>{open ? children() : null}</details>;
}

function PagedRecords<T>({ items, children, label, ordered = false }: { items: T[]; children: (item: T, index: number) => ReactNode; label: string; ordered?: boolean }) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const current = Math.min(page, Math.max(1, Math.ceil(items.length / pageSize)));
  const offset = (current - 1) * pageSize;
  const records = items.slice(offset, offset + pageSize).map((item, index) => children(item, offset + index));
  return <>
    {ordered ? <ol className="session-sync-history" start={offset + 1}>{records}</ol> : records}
    {items.length > pageSize ? <nav aria-label={label} className="session-record-pagination"><Pagination current={current} pageSize={pageSize} total={items.length} showSizeChanger={false} onChange={setPage}
      showTotal={(total, range) => t(`${range[0]}–${range[1]} of ${total}`, `第 ${range[0]}–${range[1]} 条，共 ${total} 条`)} /></nav> : null}
  </>;
}

function TaskSnapshot({ snapshot }: { snapshot: SessionTaskDetail["task"] }) {
  const content = useMemo(() => JSON.stringify(snapshot, null, 2), [snapshot]);
  return <pre className="artifact-content">{content}</pre>;
}

export function ReportedResultTag({ result }: { result: ReportedResult }) {
  const { label } = useI18n();
  return <Tag color={result === "PASS" ? "green" : ["FAIL", "ERROR"].includes(result) ? "red" : ["BLOCKED", "UNKNOWN"].includes(result) ? "gold" : undefined}>{label(result)}</Tag>;
}

function CaseContent({ item }: { item: SessionCaseRevision }) {
  const { t } = useI18n();
  return <div className="session-case-content">
    <p className="muted">{t("Sync source", "同步来源")}: {item.source} · {t("Revision", "修订")} {item.revision} · {t("Task version", "任务版本")} {item.task_version}</p>
    <Typography.Title level={5}>{t("Steps", "测试步骤")}</Typography.Title>
    {item.steps.length ? <ol>{item.steps.map((step, index) => <li key={index}>{step}</li>)}</ol> : <p className="muted">{t("No steps supplied.", "未提供步骤。")}</p>}
    <Typography.Title level={5}>{t("Expected result", "预期结果")}</Typography.Title><p className="session-literal">{item.expected || t("Not supplied", "未提供")}</p>
    <Typography.Title level={5}>{t("Agent reported observation", "Agent 报告观察")}</Typography.Title><p className="session-literal">{item.actual || t("Not supplied", "未提供")}</p>
    {item.implementation_ref ? <p>{t("Test implementation reference", "测试实现引用")}: <span className="session-literal">{item.implementation_ref}</span></p> : null}
  </div>;
}

function ReportContent({ item }: { item: SessionReportRevision }) {
  const { t, formatDate } = useI18n();
  return <div className="session-report-content">
    <Space wrap><ReportedResultTag result={item.reported_result} /><span>{t("Revision", "修订")} {item.revision}</span><span>{t("Task version", "任务版本")} {item.task_version}</span><span>{formatDate(item.created_at)}</span><Typography.Text copyable={{ text: item.markdown }}>{t("Copy original report", "复制原始报告")}</Typography.Text></Space>
    <p className="session-literal muted">{t("Sync source", "同步来源")}: {item.source}{item.source_ref ? ` · ${item.source_ref}` : ""}</p>
    {item.artifact_uri ? <p className="session-literal muted">{t("Original artifact reference", "原始产物引用")}: {item.artifact_uri}</p> : null}
    <pre className="artifact-content session-markdown" aria-label={t("Original Markdown report", "原始 Markdown 报告")}>{item.markdown}</pre>
  </div>;
}

export function SessionTaskRecords({ detail }: { detail: SessionTaskDetail }) {
  const { t, label, formatDate } = useI18n();
  const { task, cases, reports, case_history, report_history, sync_history, management_history = [], binding_history = [] } = detail;
  return <>
    <section className="data-surface session-record" aria-label={t("Task and session", "任务与会话")}>
      <Descriptions column={{ xs: 1, sm: 2, lg: 3 }} layout="vertical" items={[
        { key: "id", label: t("Task ID", "任务 ID"), children: <Typography.Text code copyable>{task.id}</Typography.Text> },
        { key: "mode", label: t("Execution mode", "执行方式"), children: t("Local Agent", "本地执行") },
        { key: "binding", label: t("Session binding", "会话绑定"), children: <Tag color={task.binding_state === "UNBOUND" ? "gold" : "green"}>{task.binding_state === "UNBOUND" ? t("Awaiting binding", "待绑定") : t("Bound", "已绑定")}</Tag> },
        { key: "bound", label: t("Bound at", "绑定时间"), children: formatDate(task.bound_at) },
        { key: "status", label: t("Task status", "任务状态"), children: <Tag color={task.status === "IN_PROGRESS" ? "blue" : task.status === "BLOCKED" ? "gold" : undefined}>{label(task.status)}</Tag> },
        { key: "result", label: t("Agent reported result", "Agent 报告结果"), children: <ReportedResultTag result={task.reported_result} /> },
        { key: "sync", label: t("Last synced", "最后同步"), children: formatDate(task.last_synced_at) },
        { key: "managed", label: t("Last managed", "最近人工管理"), children: task.last_managed_at ? formatDate(task.last_managed_at) : "—" },
        { key: "session", label: t("Initially bound session", "初始绑定会话"), children: task.session_id ? <span className="entity-key">{task.session_id}</span> : t("Not bound yet", "尚未绑定") },
        { key: "source", label: t("Record source", "记录来源"), children: [task.provider, task.source].filter(Boolean).join(" · ") || t("No Agent sync received", "尚未收到 Agent 同步") },
        { key: "version", label: t("Task version", "任务版本"), children: task.version },
      ]} />
      <Typography.Title level={3}>{t("Objective", "测试目标")}</Typography.Title>
      <p className="session-literal">{task.objective}</p>
      <Typography.Paragraph className="muted">{task.binding_state === "UNBOUND"
        ? t("This task was created on the platform. Bind the intended local Agent session before synchronizing its work. Creating or binding a task does not execute tests.", "此任务由平台创建。请先绑定获准的本地 Agent 会话，再同步测试产物。创建或绑定任务不会执行测试。")
        : !task.last_synced_at ? t("The session is bound, but no Agent work has been synced yet. Binding time and sync time are separate; results remain Not run until the Agent explicitly reports otherwise.", "会话已绑定，尚未收到 Agent 同步的测试产物。绑定时间与同步时间分别记录；结果保持尚未运行，直到 Agent 明确报告。")
          : t("Synced from the source Agent session. The Agent performs the testing work; this page manages its records and reported results. Manual edits appear separately in management history.", "内容同步自来源 Agent 会话。测试工作由 Agent 完成，此页面管理任务记录与报告结果；手动修改单独记录在管理历史中。")}</Typography.Paragraph>
    </section>
    <section className="data-surface session-record" aria-labelledby="task-plan-heading">
      <Typography.Title id="task-plan-heading" level={2}>{t("Test plan", "测试计划")}</Typography.Title>
      {task.plan_markdown ? <pre className="artifact-content session-markdown">{task.plan_markdown}</pre> : <Empty description={t("No test plan has been synced.", "尚未同步测试计划。")} />}
    </section>
    <section className="session-task-section" aria-labelledby="task-cases-heading">
      <Typography.Title id="task-cases-heading" level={2}>{t("Test cases", "测试用例")} ({cases.length})</Typography.Title>
      <div className="data-surface"><Table rowKey="id" dataSource={cases} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 680 }} expandable={{
        expandedRowRender: (item) => <CaseContent item={item} />,
        expandRowByClick: true,
      }} columns={[
        { title: t("Case", "用例"), key: "case", render: (_, item) => <><span className="entity-key">{item.key}</span><div>{item.title}</div></> },
        { title: t("Agent reported result", "Agent 报告结果"), dataIndex: "reported_result", width: 180, render: (result) => <ReportedResultTag result={result} /> },
        { title: t("Revision", "修订"), dataIndex: "revision", width: 80 },
        { title: t("Synced", "同步时间"), dataIndex: "created_at", width: 190, render: formatDate },
      ]} locale={{ emptyText: t("No cases have been synced.", "尚未同步测试用例。") }} /></div>
      <DeferredDetails className="session-history" summary={<>{t("Case revision history", "用例修订历史")} ({case_history.length})</>}>{() =>
        <PagedRecords key={task.id} items={case_history} label={t("Case history pages", "用例历史分页")}>{(item) =>
          <DeferredDetails key={item.id} className="session-revision" summary={<>{item.key} · {item.title} · {t("Revision", "修订")} {item.revision} · <ReportedResultTag result={item.reported_result} /> · {formatDate(item.created_at)}</>}>{() => <CaseContent item={item} />}</DeferredDetails>
        }</PagedRecords>
      }</DeferredDetails>
    </section>
    <section className="session-task-section" aria-labelledby="task-reports-heading">
      <Typography.Title id="task-reports-heading" level={2}>{t("Original test reports", "原始测试报告")} ({reports.length})</Typography.Title>
      {reports.length ? <PagedRecords key={task.id} items={reports} label={t("Report pages", "报告分页")}>{(item) =>
        <DeferredDetails key={item.id} className="data-surface session-record session-history" summary={<><strong>{item.title}</strong> · <span className="entity-key">{item.key}</span> · <ReportedResultTag result={item.reported_result} /> · {t("Revision", "修订")} {item.revision} · {formatDate(item.created_at)}</>}>{() => <ReportContent item={item} />}</DeferredDetails>
      }</PagedRecords> : <div className="data-surface session-task-empty"><Empty description={t("No reports have been synced.", "尚未同步测试报告。")} /></div>}
      <DeferredDetails className="session-history" summary={<>{t("Report revision history", "报告修订历史")} ({report_history.length})</>}>{() =>
        <PagedRecords key={task.id} items={report_history} label={t("Report history pages", "报告历史分页")}>{(item) =>
          <DeferredDetails key={item.id} className="session-revision" summary={<>{item.key} · {item.title} · {t("Revision", "修订")} {item.revision} · <ReportedResultTag result={item.reported_result} /></>}>{() => <ReportContent item={item} />}</DeferredDetails>
        }</PagedRecords>
      }</DeferredDetails>
    </section>
    {binding_history.length ? <section className="session-task-section" aria-labelledby="task-binding-history-heading">
      <Typography.Title id="task-binding-history-heading" level={2}>{t("Binding history", "会话绑定历史")} ({binding_history.length})</Typography.Title>
      <PagedRecords key={task.id} items={binding_history} ordered label={t("Binding history pages", "绑定历史分页")}>{(entry) => <li key={entry.id || `${entry.task_version}-${entry.action}`}>
        <Space wrap><strong>{t("Session bound", "已绑定会话")}</strong><span>{t("Task version", "任务版本")} {entry.task_version}</span><span>{formatDate(entry.created_at)}</span></Space>
        <p className="session-literal muted">{t("Bound by", "绑定客户端")}: {entry.actor_ref}</p>
        <DeferredDetails summary={t("Task after binding", "绑定后的任务记录")}>{() => <TaskSnapshot snapshot={entry.task_snapshot} />}</DeferredDetails>
      </li>}</PagedRecords>
    </section> : null}
    <section className="session-task-section" aria-labelledby="task-management-heading">
      <Typography.Title id="task-management-heading" level={2}>{t("Management history", "管理历史")} ({management_history.length})</Typography.Title>
      {management_history.length ? <PagedRecords key={task.id} items={management_history} ordered label={t("Management history pages", "管理历史分页")}>{(entry) => <li key={entry.id || `${entry.task_version}-${entry.action}`}>
        <Space wrap><strong>{label(entry.action)}</strong><span>{t("Task version", "任务版本")} {entry.task_version}</span><span>{formatDate(entry.created_at)}</span></Space>
        <p className="session-literal muted">{t("Managed by", "管理来源")}: {entry.actor_ref}</p>
        <DeferredDetails summary={t("Task after this change", "修改后的任务内容")}>{() => <TaskSnapshot snapshot={entry.task_snapshot} />}</DeferredDetails>
      </li>}</PagedRecords> : <Typography.Paragraph className="muted">{t("No manual changes recorded.", "暂无手动修改记录。")}</Typography.Paragraph>}
    </section>
    <section className="session-task-section" aria-labelledby="task-sync-heading">
      <Typography.Title id="task-sync-heading" level={2}>{t("Sync history", "同步历史")} ({sync_history.length})</Typography.Title>
      {sync_history.length ? <PagedRecords key={task.id} items={sync_history} ordered label={t("Sync history pages", "同步历史分页")}>{(receipt) => <li key={receipt.id}>
        <Space wrap><strong>{t("Task version", "任务版本")} {receipt.task_version}</strong><span>{formatDate(receipt.created_at)}</span></Space>
        <p className="session-literal muted">{t("Submitted by", "提交来源")}: {receipt.actor_ref}</p>
        <DeferredDetails summary={t("Task at this sync", "本次同步的任务内容")}>{() => <TaskSnapshot snapshot={receipt.task_snapshot} />}</DeferredDetails>
      </li>}</PagedRecords> : <Empty description={t("No sync history is available.", "暂无同步历史。")} />}
    </section>
  </>;
}
