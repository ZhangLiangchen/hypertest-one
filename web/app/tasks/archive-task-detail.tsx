"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Empty, Form, Input, InputNumber, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";
import { errorText } from "@/lib/api";
import { archiveApi, getArchiveSnapshot, getArchiveTask, type ArchiveAsset, type ArchiveSnapshot, type ArchiveTask } from "@/lib/archive";
import { useArchiveOperation } from "@/lib/archive-operation";
import { useI18n } from "@/lib/i18n";
import { WorkspaceHeading, WorkspaceLoading, ProjectNavigation } from "@/app/workspace-ui";
import { ReportedResultTag } from "@/app/tasks/task-records";
import { ArchiveOperationNotice } from "@/app/archives/archive-shared";
import { ArchivePrompt } from "@/app/archives/archive-prompt";
import { TaskQuickNavigation } from "./task-quick-navigation";
import { ReloadOutlined } from "@ant-design/icons";

const statuses = ["DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"];
const results = ["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"];
type ManagementDraft = { mode: "subtask" | "update" | "publish"; version: number; task: ArchiveTask; root: number; children: { subtask_id: string; archive_version: number; title: string; status: string }[] };
export default function ArchiveTaskDetail({ taskId, projectId }: { taskId: string; projectId: string }) {
  const { t, locale, label, formatDate } = useI18n(); const cache = useQueryClient();
  const [target, setTarget] = useState(""), [version, setVersion] = useState<number | undefined>(), [submissionId, setSubmissionId] = useState<string | undefined>();
  const [draft, setDraft] = useState<ManagementDraft | null>(null);
  const [form] = Form.useForm();
  const includedChildren: string[] = Form.useWatch("selected_children", form) || [];
  useEffect(() => { setDraft(null); setTarget(""); setVersion(undefined); setSubmissionId(undefined); form.resetFields(); }, [projectId, taskId, form]);
  useEffect(() => { if (draft) document.getElementById("task-archive-edit")?.scrollIntoView({ block: "start" }); }, [draft]);
  const publicationAssets = useQuery({ queryKey: ["archive-publication-assets", projectId, taskId, draft?.version, draft?.root], enabled: draft?.mode === "publish", retry: false,
    queryFn: async () => { if (!draft) return []; const spaces = await Promise.all([getArchiveSnapshot(projectId, taskId, draft.root), ...draft.children.map((c) => getArchiveSnapshot(projectId, taskId, c.archive_version, c.subtask_id))]); return spaces.flatMap((space) => space.assets.map((item) => ({ ...item, space: space.subtask_id }))); } });
  const query = useQuery({ queryKey: ["archive-task", projectId, taskId], queryFn: () => getArchiveTask(projectId, taskId), enabled: Boolean(projectId), retry: false });
  const operation = useArchiveOperation(projectId, taskId);
  const task = query.data?.task; const children = query.data?.subtasks || []; const child = children.find((row) => row.id === target);
  const latestVersion = child?.archive_version || task?.archive_version || 1;
  const snapshot = useQuery({ queryKey: ["archive-snapshot", projectId, taskId, target, version || latestVersion, submissionId], enabled: Boolean(task), retry: false,
    queryFn: () => submissionId ? archiveApi<ArchiveSnapshot>(`submissions/${submissionId}?project_id=${projectId}&readback=complete`) : getArchiveSnapshot(projectId, taskId, version || latestVersion, target || undefined) });
  const accepted = (_result: unknown) => { setDraft(null); form.resetFields(); void cache.invalidateQueries({ queryKey: ["archive-task", projectId, taskId] }); void cache.invalidateQueries({ queryKey: ["archive-tasks", projectId] }); };
  function open(mode: ManagementDraft["mode"]) {
    if (!task) return;
    setDraft({ mode, version: task.version, task, root: task.archive_version, children: children.map((c) => ({ subtask_id: c.id, archive_version: c.archive_version, title: c.title, status: c.status })) });
    form.resetFields(); form.setFieldsValue(mode === "publish" ? { status: task.status, reported_result: task.reported_result, summary: "", selected_children: [], asset_revision_ids: [] }
      : mode === "update" ? { title: task.title, objective: task.objective } : { title: "", objective: "" });
  }
  async function manage(values: Record<string, unknown>) {
    if (!draft) return;
    let fields: Record<string, unknown> = { ...values, expected_task_version: draft.version };
    let action: string = draft.mode;
    if (draft.mode === "subtask") action = "subtasks";
    if (draft.mode === "publish") { action = "publications"; fields = { expected_task_version: draft.version, root_archive_version: draft.root, subtask_versions: draft.children.filter((c) => (values.selected_children as string[] || []).includes(c.subtask_id)).map(({ subtask_id, archive_version }) => ({ subtask_id, archive_version })), asset_revision_ids: values.asset_revision_ids || [], summary: values.summary, status: values.status, reported_result: values.reported_result }; }
    const result = await operation.manage(`tasks/${taskId}/${action}`, fields); if (result) accepted(result);
  }
  const assets = snapshot.data?.assets || [];
  const plans = assets.filter((item) => item.kind === "PLAN");
  const cases = assets.filter((item) => item.kind === "CASE");
  const reports = assets.filter((item) => item.kind === "REPORT");
  const snapshotTarget = submissionId ? snapshot.data?.subtask_id : target;
  const snapshotTitle = children.find((item) => item.id === snapshotTarget)?.title || (snapshotTarget ? snapshotTarget : t("Task root", "任务根空间"));
  function viewSnapshot(subtaskId: string, archiveVersion?: number, submission?: string) {
    setTarget(subtaskId); setVersion(archiveVersion); setSubmissionId(submission);
    document.getElementById("task-artifacts")?.scrollIntoView({ block: "start" });
  }
  if (!projectId) return <main className="workspace-page"><Alert type="error" showIcon message={t("A Project ID is required", "需要明确的项目 ID")} description={t("Open this archive from its Project workspace.", "请从所属项目工作区打开此归档任务。") } /></main>;
  if (query.isLoading) return <main className="workspace-page"><WorkspaceLoading label={t("Loading archive", "正在读取归档")} /></main>;
  if (!task) return <main className="workspace-page"><WorkspaceHeading title={t("Local archive", "本地归档")} backHref={`/projects/${projectId}`} backLabel={t("Project", "项目")} /><Alert type="error" showIcon message={t("Archive unavailable", "无法读取归档")} description={errorText(query.error, locale)} action={<Button onClick={() => void query.refetch()}>{t("Retry", "重试")}</Button>} /></main>;
  return <main className="workspace-page archive-task-page">
    <WorkspaceHeading title={task.title} backHref={`/projects/${projectId}`} backLabel={t("Project tasks", "项目任务")}
      actions={<Space><Button onClick={() => open("update")} disabled={operation.blocked}>{t("Edit task", "编辑任务")}</Button><Button icon={<ReloadOutlined aria-hidden />} onClick={() => { void query.refetch(); void snapshot.refetch(); }} loading={query.isFetching || snapshot.isFetching}>{t("Refresh", "刷新")}</Button></Space>} />
    <ProjectNavigation projectId={projectId} active="local" />
    {query.isError ? <Alert type="warning" showIcon message={t("Refresh failed; previously loaded records remain visible", "刷新失败，保留已读取记录")} description={errorText(query.error, locale)} /> : null}
    <div className="task-detail-layout">
      <TaskQuickNavigation items={[
        { id: "task-overview", label: t("Task overview", "任务概览") },
        { id: "task-upload", label: t("Archive artifacts", "归档产物") },
        { id: "task-subtasks", label: t("Subtasks", "子任务"), count: children.length },
        { id: "task-artifacts", label: t("Artifact versions", "产物版本") },
        { id: "task-plan", label: t("Test plan", "测试计划"), count: plans.length },
        { id: "task-cases", label: t("Test cases", "测试用例"), count: cases.length },
        { id: "task-reports", label: t("Original test reports", "原始测试报告"), count: reports.length },
        { id: "task-publications", label: t("Task summaries", "任务汇总") },
        { id: "task-submissions", label: t("Upload history", "上传历史"), history: true },
        { id: "task-management", label: t("Management history", "管理历史") },
      ]} />
      <div className="task-detail-content">
        <section id="task-overview" tabIndex={-1} className="data-surface session-record archive-overview" aria-label={t("Task overview", "任务概览")}>
          <div className="archive-overview-lead">
            <div className="archive-objective">
              <Typography.Title level={3}>{t("Objective", "测试目标")}</Typography.Title>
              <p className="session-literal">{task.objective || t("No objective supplied.", "尚未填写测试目标。")}</p>
            </div>
            <div className="archive-overview-status">
              <div><span>{t("Task status", "任务状态")}</span><Tag color={task.status === "IN_PROGRESS" ? "blue" : task.status === "BLOCKED" ? "gold" : undefined}>{label(task.status)}</Tag></div>
              <div><span>{t("Reported result", "报告结果")}</span><ReportedResultTag result={task.reported_result} /></div>
            </div>
          </div>
          <Descriptions className="archive-overview-details" column={3} layout="vertical" items={[
            { key: "id", label: t("Task ID", "任务 ID"), children: <Typography.Text code copyable>{task.id}</Typography.Text> },
            { key: "mode", label: t("Execution mode", "执行方式"), children: t("Local Agent · explicit archive", "本地执行 · 显式归档") },
            { key: "created", label: t("Created", "创建时间"), children: formatDate(task.created_at) },
            { key: "updated", label: t("Updated", "更新时间"), children: formatDate(task.updated_at) },
            { key: "management", label: t("Management version", "管理版本"), children: task.version },
            { key: "archive", label: t("Root archive version", "根归档版本"), children: `v${task.archive_version}` },
            { key: "project", label: t("Project ID", "项目 ID"), children: <Typography.Text code copyable>{projectId}</Typography.Text> },
          ]} />
          {(task.sut_repository_url || task.test_framework_repository_url || task.sut_branch || task.framework_branch) ? <>
            <Typography.Title level={3}>{t("Task repository inputs", "任务仓库输入")}</Typography.Title>
            <Descriptions column={2} layout="vertical" items={[
              { key: "sut-repo", label: t("SUT repository", "被测对象仓库"), children: task.sut_repository_url || t("Not recorded", "未记录") },
              { key: "sut-branch", label: t("SUT branch", "被测对象分支"), children: task.sut_branch || t("Not recorded", "未记录") },
              { key: "framework-repo", label: t("Test framework repository", "测试框架仓库"), children: task.test_framework_repository_url || t("Not recorded", "未记录") },
              { key: "framework-branch", label: t("Test framework branch", "测试框架分支"), children: task.framework_branch || t("Not recorded", "未记录") },
            ]} />
          </> : null}
          <Typography.Paragraph className="muted archive-overview-note">{t("The local Agent performs testing. Archive completed plans, cases and reports explicitly with the CLI. Uploading artifacts does not mark the task complete or change its reported result.", "测试由本地 Agent 完成，通过 CLI 显式归档已完成的计划、用例与报告。上传产物不会自动完成任务或改变报告结果。")}</Typography.Paragraph>
        </section>
        <ArchiveOperationNotice operation={operation} onAccepted={accepted} />
        {draft ? <section id="task-archive-edit" tabIndex={-1} className="data-surface session-record"><Typography.Title level={2}>{draft.mode === "subtask" ? t("Add subtask", "添加子任务") : draft.mode === "publish" ? t("Publish task summary", "发布任务汇总") : t("Edit task", "编辑任务")}</Typography.Title>
      <Form form={form} layout="vertical" onFinish={manage} disabled={operation.blocked} requiredMark="optional">
        {draft.mode === "subtask" || draft.mode === "update" ? <><Form.Item name="title" label={t("Title", "标题")} rules={[{ required: true, whitespace: true }, { max: 512 }]}><Input maxLength={512} /></Form.Item><Form.Item name="objective" label={t("Objective / responsibility", "目标 / 分工")} rules={[{ max: 16000 }]}><Input.TextArea rows={3} maxLength={16000} /></Form.Item></> : null}
        {draft.mode === "publish" ? <><Typography.Paragraph>{t("This summary freezes root version", "此次汇总固定根归档版本")} v{draft.root} · {t("management version", "管理版本")} {draft.version}</Typography.Paragraph><Form.Item name="selected_children" label={t("Included subtask versions", "纳入的子任务版本")} extra={t("Unselected and unfinished subtasks remain visible below and are not silently counted as complete.", "未选择及未完成的子任务仍保留显示，不会被自动视作完成。") }><Select mode="multiple" options={draft.children.map((c) => ({ value: c.subtask_id, label: `${c.title} · v${c.archive_version} · ${label(c.status)}` }))} /></Form.Item><Form.Item name="asset_revision_ids" label={t("Referenced artifact revisions", "引用的产物修订")}><Select mode="multiple" loading={publicationAssets.isFetching} options={publicationAssets.data?.filter((item) => !item.space || includedChildren.includes(item.space)).map((item) => ({ value: item.id, label: `${item.title} · ${item.kind} · r${item.revision}` }))} /></Form.Item>{publicationAssets.isError ? <Alert type="warning" showIcon message={t("Artifact references could not be loaded", "无法读取产物引用")} action={<Button onClick={() => void publicationAssets.refetch()}>{t("Retry", "重试")}</Button>} /> : null}<Form.Item name="summary" label={t("Summary, omissions and unfinished work", "汇总、未纳入范围与未完成工作")} rules={[{ required: true, whitespace: true }, { max: 262144 }]}><Input.TextArea rows={6} maxLength={262144} /></Form.Item><Space align="start"><Form.Item name="status" label={t("Task progress", "任务进度")} rules={[{ required: true }]}><Select className="archive-status-select" options={statuses.map((value) => ({ value, label: label(value) }))} /></Form.Item><Form.Item name="reported_result" label={t("Explicit reported result", "明确报告结果")} rules={[{ required: true }]}><Select className="archive-status-select" options={results.map((value) => ({ value, label: value }))} /></Form.Item></Space></> : null}
        <Space><Button type="primary" htmlType="submit" loading={operation.busy}>{draft.mode === "publish" ? t("Publish summary", "发布汇总") : t("Save", "保存")}</Button><Button onClick={() => setDraft(null)}>{t("Cancel", "取消")}</Button></Space>
      </Form></section> : null}
        <section id="task-upload" tabIndex={-1} className="data-surface session-record archive-upload" aria-labelledby="archive-upload-heading">
          <div className="activity-heading"><Typography.Title id="archive-upload-heading" level={2}>{t("Archive test artifacts", "归档测试产物")}</Typography.Title></div>
          <div className="archive-upload-workflow"><div className="archive-destination-field"><label htmlFor="archive-target">{t("Destination", "归档位置")}</label><Select id="archive-target" className="archive-target" value={target} onChange={(value) => { setTarget(value); setVersion(undefined); setSubmissionId(undefined); }} options={[{ value: "", label: t("Task root (no Subtask ID)", "任务根空间（无需子任务 ID）") }, ...children.map((c) => ({ value: c.id, label: `${c.title} · ${c.id}` }))]} /></div>
          <ArchivePrompt projectId={projectId} taskId={taskId} subtaskId={target || undefined} taskInputs={{ sut_repository_url: task.sut_repository_url, test_framework_repository_url: task.test_framework_repository_url, sut_branch: task.sut_branch, framework_branch: task.framework_branch }} />
          <Link className="archive-install-link" href={`/cli-authorizations?projectId=${projectId}#cli-install`}>{t("CLI installation prompt & authorization", "CLI 安装 Prompt 与授权")}</Link></div>
        </section>
        <section id="task-subtasks" tabIndex={-1} className="session-task-section" aria-labelledby="archive-children-heading">
          <div className="activity-heading"><Typography.Title id="archive-children-heading" level={2}>{t("Optional subtasks", "可选子任务")} ({children.length})</Typography.Title><Button onClick={() => open("subtask")} disabled={operation.blocked}>{t("Add subtask", "添加子任务")}</Button></div>
          <div className="data-surface"><Table size="small" rowKey="id" dataSource={children} pagination={false} scroll={{ x: 680 }} locale={{ emptyText: t("No subtasks. Uploads can go directly to the task root.", "没有子任务，可直接上传到任务根空间。") }} columns={[
            { title: t("Subtask", "子任务"), key: "title", render: (_, row) => <><Button type="link" onClick={() => viewSnapshot(row.id)}>{row.title}</Button><div><Typography.Text code copyable>{row.id}</Typography.Text></div></> },
            { title: t("Archive version", "归档版本"), dataIndex: "archive_version", render: (v: number) => `v${v}` },
            { title: t("Status", "状态"), dataIndex: "status", render: label }, { title: t("Reported result", "报告结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> },
          ]} /></div>
        </section>
        <section id="task-artifacts" tabIndex={-1} className="data-surface session-record" aria-labelledby="archive-version-heading">
          <div className="activity-heading archive-version-heading"><Typography.Title id="archive-version-heading" level={2}>{submissionId ? t("Submission snapshot", "提交时的固定快照") : t("Artifact versions", "产物版本")}</Typography.Title><Space className="archive-version-controls" size={12}><label htmlFor="archive-version">{t("Version", "版本")}</label><InputNumber className="archive-version-input" id="archive-version" min={1} max={submissionId ? undefined : latestVersion} precision={0} value={submissionId ? snapshot.data?.archive_version : version || latestVersion} disabled={Boolean(submissionId)} onChange={(value) => { if (value) setVersion(value); }} />{submissionId ? <Button onClick={() => setSubmissionId(undefined)}>{t("Back to destination", "返回当前目标")}</Button> : null}</Space></div>
          <Typography.Paragraph className="muted">{snapshotTitle} · {t("The plan, cases and reports below belong to this exact archive version.", "以下计划、用例与报告均来自此固定归档版本。")}</Typography.Paragraph>
          {submissionId ? <Typography.Text code copyable>{submissionId}</Typography.Text> : null}
          {snapshot.isError ? <Alert type="error" showIcon message={t("The complete snapshot could not be loaded", "无法读取完整快照")} description={errorText(snapshot.error, locale)} action={<Button onClick={() => void snapshot.refetch()}>{t("Retry", "重试")}</Button>} /> : null}
          {snapshot.isFetching ? <Typography.Paragraph role="status" className="muted">{t("Loading artifact version…", "正在读取产物版本…")}</Typography.Paragraph> : null}
        </section>
        <section id="task-plan" tabIndex={-1} className="data-surface session-record" aria-labelledby="task-plan-heading">
          <Typography.Title id="task-plan-heading" level={2}>{t("Test plan", "测试计划")}{plans.length > 1 ? ` (${plans.length})` : ""}</Typography.Title>
          {plans.length ? plans.map((item) => <article key={item.id} className="archive-plan-record"><Typography.Title level={3}>{item.title}</Typography.Title><ArchiveAssetMetadata item={item} /><pre className="artifact-content session-markdown">{typeof item.markdown === "string" ? item.markdown : ""}</pre></article>) : <Empty description={snapshot.isError ? t("Plan unavailable for this version.", "无法读取此版本的计划。") : t("No test plan in this version.", "此版本尚无测试计划。")} />}
        </section>
        <section id="task-cases" tabIndex={-1} className="session-task-section" aria-labelledby="task-cases-heading">
          <Typography.Title id="task-cases-heading" level={2}>{t("Test cases", "测试用例")} ({cases.length})</Typography.Title>
          <div className="data-surface"><Table rowKey="id" dataSource={cases} loading={snapshot.isFetching} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 680 }} expandable={{ expandedRowRender: (item) => <ArchiveCaseContent item={item} />, expandRowByClick: true }} columns={[
            { title: t("Case", "用例"), key: "case", render: (_, item) => <><span className="entity-key">{item.stable_key}</span><div>{item.title}</div></> },
            { title: t("Reported result", "报告结果"), dataIndex: "reported_result", width: 160, render: (result) => <ReportedResultTag result={result} /> },
            { title: t("Revision", "修订"), dataIndex: "revision", width: 80 },
            { title: t("Accepted", "接受时间"), dataIndex: "accepted_at", width: 180, render: formatDate },
          ]} locale={{ emptyText: snapshot.isError ? t("Cases unavailable for this version.", "无法读取此版本的用例。") : t("No cases in this version.", "此版本尚无测试用例。") }} /></div>
        </section>
        <section id="task-reports" tabIndex={-1} className="session-task-section" aria-labelledby="task-reports-heading">
          <Typography.Title id="task-reports-heading" level={2}>{t("Original test reports", "原始测试报告")} ({reports.length})</Typography.Title>
          {reports.length ? reports.map((item) => <ArchiveReport key={item.id} item={item} />) : <div className="data-surface session-task-empty"><Empty description={snapshot.isError ? t("Reports unavailable for this version.", "无法读取此版本的报告。") : t("No reports in this version.", "此版本尚无测试报告。")} /></div>}
        </section>
        <section id="task-publications" tabIndex={-1} className="session-task-section" aria-labelledby="task-publications-heading">
          <div className="activity-heading"><Typography.Title id="task-publications-heading" level={2}>{t("Task summaries", "任务汇总")}</Typography.Title><Button onClick={() => open("publish")} disabled={operation.blocked}>{t("Publish summary", "发布汇总")}</Button></div>
          {query.data?.publications.length ? query.data.publications.map((publication) => <article className="data-surface session-record" key={publication.id}>
            <Space wrap><Typography.Text strong>{t("Management version", "管理版本")} {publication.task_version}</Typography.Text><Tag>{label(publication.status)}</Tag><ReportedResultTag result={publication.reported_result} /><Typography.Text className="muted">{formatDate(publication.created_at)}</Typography.Text></Space>
            <pre className="archive-summary">{publication.summary}</pre><Typography.Paragraph>{t("Root", "根空间")} v{publication.root_archive_version} · {t("Included subtasks", "纳入子任务")}: {publication.subtask_versions.length}</Typography.Paragraph>
            <Typography.Paragraph className="muted">{t("Excluded", "未纳入")}: {(publication.omitted_subtask_ids || []).map((id) => children.find((c) => c.id === id)?.title || id).join(", ") || t("None", "无")} · {t("Unfinished at publication", "发布时未完成")}: {(publication.incomplete_subtask_ids || []).map((id) => children.find((c) => c.id === id)?.title || id).join(", ") || t("None", "无")}</Typography.Paragraph>
            <Space wrap><Button onClick={() => viewSnapshot("", publication.root_archive_version)}>{t("Read frozen root", "查看固定根版本")}</Button>{publication.subtask_versions.map((ref) => <Button key={ref.subtask_id} onClick={() => viewSnapshot(ref.subtask_id, ref.archive_version)}>{children.find((c) => c.id === ref.subtask_id)?.title || ref.subtask_id} · v{ref.archive_version}</Button>)}</Space>
            {task.archive_version > publication.root_archive_version || children.some((c) => { const ref = publication.subtask_versions.find((r) => r.subtask_id === c.id); return !ref || c.archive_version > ref.archive_version; }) ? <Typography.Paragraph className="muted">{t("Newer or excluded material exists; this published summary keeps its original versions.", "存在更新或未纳入的材料；此汇总保留发布时的版本。")}</Typography.Paragraph> : null}
          </article>) : <div className="data-surface session-task-empty"><Empty description={t("No task summary has been published", "尚未发布任务汇总")} /></div>}
        </section>
        <section id="task-submissions" tabIndex={-1} className="session-task-section" aria-labelledby="task-submissions-heading">
          <Typography.Title id="task-submissions-heading" level={2}>{t("Upload history", "上传历史")} ({query.data?.submission_history.length || 0})</Typography.Title>
          <div className="data-surface"><Table rowKey={(row) => String(row.submission_id)} dataSource={query.data?.submission_history || []} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 680 }} columns={[
            { title: t("Submission", "提交"), key: "id", render: (_, row) => <Typography.Text code copyable>{String(row.submission_id)}</Typography.Text> },
            { title: t("Destination", "目标"), key: "target", render: (_, row) => children.find((c) => c.id === row.subtask_id)?.title || String(row.subtask_id || t("Task root", "任务根空间")) },
            { title: t("Outcome", "归档结果"), dataIndex: "outcome" }, { title: t("Accepted version", "接受版本"), dataIndex: "accepted_version" },
            { title: t("Original snapshot", "原固定快照"), key: "open", render: (_, row) => <Button onClick={() => viewSnapshot(String(row.subtask_id || ""), undefined, String(row.submission_id))}>{t("Read snapshot", "查看快照")}</Button> },
          ]} /></div>
        </section>
        <section id="task-management" tabIndex={-1} className="session-task-section" aria-labelledby="task-management-heading">
          <Typography.Title id="task-management-heading" level={2}>{t("Management history", "管理历史")} ({query.data?.management_history.length || 0})</Typography.Title>
          <div className="data-surface"><Table rowKey={(row) => String(row.operation_id)} dataSource={query.data?.management_history || []} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 680 }} expandable={{ expandedRowRender: (row) => <pre className="artifact-content">{JSON.stringify(row.request_payload, null, 2)}</pre> }} columns={[
            { title: t("Operation", "操作"), dataIndex: "operation" }, { title: t("Management version", "管理版本"), dataIndex: "task_version" }, { title: t("Original request key", "原请求标识"), key: "key", render: (_, row) => <Typography.Text code copyable>{String(row.idempotency_key)}</Typography.Text> },
          ]} /></div>
        </section>
      </div>
    </div>
  </main>;
}

function ArchiveAssetMetadata({ item }: { item: ArchiveAsset }) {
  const { t, formatDate } = useI18n();
  return <>
    <Space wrap className="muted"><Typography.Text code copyable>{item.stable_key}</Typography.Text><span>{t("Revision", "修订")} {item.revision}</span><span>{formatDate(item.accepted_at)}</span></Space>
    {item.kind === "REPORT" ? <Typography.Paragraph>{t("Report asset revision ID", "报告资产修订 ID")}: <Typography.Text code copyable>{item.id}</Typography.Text></Typography.Paragraph> : null}
    <details className="session-history archive-asset-source"><summary>{t("Uploader and declared source", "上传者与声明来源")}</summary><Typography.Paragraph>{t("Authenticated uploader", "认证上传者")}: <Typography.Text code>{String(item.uploader_actor_ref || "—")}</Typography.Text></Typography.Paragraph><pre className="artifact-content">{JSON.stringify(item.origin || {}, null, 2)}</pre></details>
  </>;
}

function ArchiveCaseContent({ item }: { item: ArchiveAsset }) {
  const { t } = useI18n();
  return <div className="session-case-content">
    <ArchiveAssetMetadata item={item} />
    <Typography.Title level={5}>{t("Steps", "测试步骤")}</Typography.Title>
    {Array.isArray(item.steps) && item.steps.length ? <ol>{item.steps.map((step, index) => <li key={index}>{String(step)}</li>)}</ol> : <p className="muted">{t("No steps supplied.", "未提供步骤。")}</p>}
    <Typography.Title level={5}>{t("Expected result", "预期结果")}</Typography.Title><p className="session-literal">{String(item.expected || t("Not supplied", "未提供"))}</p>
    <Typography.Title level={5}>{t("Reported observation", "报告观察")}</Typography.Title><p className="session-literal">{String(item.actual || t("Not supplied", "未提供"))}</p>
    {item.implementation_ref ? <p>{t("Test implementation reference", "测试实现引用")}: <span className="session-literal">{String(item.implementation_ref)}</span></p> : null}
  </div>;
}

function ArchiveReport({ item }: { item: ArchiveAsset }) {
  const { t, formatDate } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const markdown = typeof item.markdown === "string" ? item.markdown : "";
  return <details className="data-surface session-record session-history" open={expanded} onToggle={(event) => { if (event.target === event.currentTarget) setExpanded(event.currentTarget.open); }}>
    <summary><strong>{item.title}</strong> · <span className="entity-key">{item.stable_key}</span> · <ReportedResultTag result={item.reported_result} /> · {t("Revision", "修订")} {item.revision} · {formatDate(item.accepted_at)}</summary>
    {expanded ? <div className="session-report-content"><ArchiveAssetMetadata item={item} /><Typography.Text copyable={{ text: markdown }}>{t("Copy original report", "复制原始报告")}</Typography.Text><pre className="artifact-content session-markdown" aria-label={t("Original report", "原始报告")}>{markdown}</pre></div> : null}
  </details>;
}
