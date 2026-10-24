"use client";

import { useEffect, useRef, useState } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Descriptions, Empty, Form, Input, InputNumber, Radio, Space, Table, Tabs, Tag, Typography } from "antd";
import { ProjectNavigation, WorkspaceHeading, WorkspaceLoading } from "@/app/workspace-ui";
import { getProject } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { memoryEntry, memoryProject, memoryQuery, memoryRequest } from "@/lib/memory";
import type { MemoryAction, MemoryEntry, MemoryMutation, MemorySource } from "@/lib/memory";
import { useMemoryOperation } from "@/lib/memory-operation";

const UUID = /^(?:[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})$/;
type Editor = { action: "CREATE_CANDIDATE" | "PUBLISH" | "REVISE" | "RETRACT"; entry?: MemoryEntry };
type Fields = { title: string; content: string; applicability?: string; observed_at?: string; expires_at?: string; mode: "LOCAL" | "CLOUD"; task_id: string; task_version: number; report_id?: string; attempt_id?: string; asset_revision_id?: string; publication_note: string; reviewed: boolean };

export function MemoryEditor({ editor, blocked, busy, onSubmit, onClose }: { editor: Editor; blocked: boolean; busy: boolean; onSubmit: (fields: Omit<MemoryMutation, "project_id" | "operation_key">) => Promise<boolean>; onClose: () => void }) {
  const { t } = useI18n(); const [form] = Form.useForm<Fields>();
  const mode = Form.useWatch("mode", form) || "LOCAL";
  const creating = editor.action === "CREATE_CANDIDATE", retracting = editor.action === "RETRACT";
  const title = creating ? t("Save a private candidate", "保存私有候选") : retracting ? t("Withdraw shared experience", "撤回共享经验") : editor.action === "REVISE" ? t("Append a shared revision", "追加共享修订") : t("Review and publish", "审阅并发布");
  const required = { required: true, whitespace: true, message: t("Complete this field.", "请填写此项。") };
  const referenceRules = [required, { pattern: UUID, message: t("Enter a complete UUID.", "请输入完整 UUID。") }];
  async function finish(values: Fields) {
    const fields: Omit<MemoryMutation, "project_id" | "operation_key"> = { operation: editor.action, expected_version: editor.entry?.version || 0 };
    if (editor.entry) fields.entry_id = editor.entry.id;
    if (!retracting) {
      Object.assign(fields, { title: values.title, content: values.content, applicability: values.applicability || "" });
      if (values.observed_at?.trim()) fields.observed_at = values.observed_at.trim();
      if (values.expires_at?.trim()) fields.expires_at = values.expires_at.trim();
    }
    if (creating) fields.source = { mode: values.mode, task_id: values.task_id, task_version: values.task_version,
      ...(values.mode === "LOCAL" ? { report_id: values.report_id } : { attempt_id: values.attempt_id, asset_revision_id: values.asset_revision_id }) } as MemorySource;
    else fields.publication_note = values.publication_note;
    await onSubmit(fields);
  }
  return <section className="workspace-panel" aria-labelledby="memory-editor-title" style={{ marginTop: 24 }}>
    <Typography.Title id="memory-editor-title" level={2}>{title}</Typography.Title>
    {!creating && !retracting ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Only the reviewed text below will be shared", "仅共享下方经过审阅的正文")} description={t("Remove credentials, personal data, private URLs and report excerpts that should stay private. Private source references are not included in shared search results. Publishing records your review; it does not verify a test result.", "请移除凭据、个人信息、私有地址及不应共享的报告片段。共享检索不会附带私有来源引用。发布记录你的审阅，不构成测试结果验证。")} /> : null}
    {retracting ? <Typography.Paragraph>{t("Withdrawal removes this experience from new shared retrievals. Earlier revisions and operation receipts remain in history.", "撤回后，新的共享检索不再返回此经验。历史修订与操作回执继续保留。")}</Typography.Paragraph> : null}
    <Form form={form} layout="vertical" disabled={blocked} requiredMark="optional" initialValues={{ mode: "LOCAL", task_version: 1, ...editor.entry, reviewed: false }} onFinish={finish}
      onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}>
      {creating ? <div className="form-section">
        <Typography.Title level={3}>{t("Accepted report source", "已接受的报告来源")}</Typography.Title>
        <Typography.Paragraph className="muted">{t("Write a selected lesson and identify an accepted report at an exact task version. No conversation, prompt, file or raw report is scanned or uploaded by this form. Candidates remain private until explicitly published.", "手工填写选定经验，并引用确切任务版本的已接受报告。此表单不会扫描或上传会话、prompt、文件或原始报告。候选在显式发布前保持私有。")}</Typography.Paragraph>
        <Form.Item name="mode" label={t("Source mode", "来源模式")}><Radio.Group options={[{ value: "LOCAL", label: "Local" }, { value: "CLOUD", label: "Cloud" }]} /></Form.Item>
        <div className="form-grid">
        <Form.Item name="task_id" label={t("Source task ID", "来源任务 ID")} rules={referenceRules}><Input maxLength={36} autoComplete="off" /></Form.Item>
        <Form.Item name="task_version" label={t("Accepted task version", "已接受的任务版本")} rules={[{ required: true, type: "number", min: 1, message: t("Use a positive version number.", "请填写大于零的版本号。") }]}><InputNumber min={1} precision={0} /></Form.Item>
        {mode === "LOCAL" ? <Form.Item name="report_id" label={t("Source report ID", "来源报告 ID")} rules={referenceRules}><Input maxLength={36} autoComplete="off" /></Form.Item> : <>
          <Form.Item name="attempt_id" label={t("Source attempt ID", "来源 Attempt ID")} rules={referenceRules}><Input maxLength={36} autoComplete="off" /></Form.Item>
          <Form.Item name="asset_revision_id" label={t("Source report asset revision ID", "来源报告资产修订 ID")} rules={referenceRules}><Input maxLength={36} autoComplete="off" /></Form.Item>
        </>}
        </div>
      </div> : null}
      {!retracting ? <div className="form-section">
        <Typography.Title level={3}>{t("Experience and applicability", "经验与适用条件")}</Typography.Title>
        <Form.Item name="title" label={t("Experience title", "经验标题")} rules={[required, { max: 255 }]}><Input maxLength={255} /></Form.Item>
        <Form.Item name="content" label={t("Experience text", "经验正文")} rules={[required, { max: 16000 }]}><Input.TextArea rows={8} showCount maxLength={16000} /></Form.Item>
        <Form.Item name="applicability" label={t("When this applies", "适用条件")} rules={[{ max: 2000 }]} extra={t("Describe the framework, version or conditions where this lesson was observed. It remains historical reference.", "说明观察到此经验时的框架、版本及条件；经验仍是历史参考。 ")}><Input.TextArea rows={3} showCount maxLength={2000} /></Form.Item>
        <div className="form-grid">
        <Form.Item name="observed_at" label={t("Observed at (optional, with timezone)", "观察时间（可选，含时区）")} rules={[{ validator: async (_, value) => { if (value && (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || Number.isNaN(Date.parse(value)))) throw new Error(t("Use an ISO timestamp with a timezone, for example 2026-10-23T10:00:00+08:00.", "请填写含时区的 ISO 时间，例如 2026-10-23T10:00:00+08:00。")); } }]}><Input maxLength={40} placeholder="2026-10-23T10:00:00+08:00" autoComplete="off" /></Form.Item>
        <Form.Item name="expires_at" label={t("Expires at (optional, with timezone)", "有效期至（可选，含时区）")} rules={[{ validator: async (_, value) => { if (value && (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || Number.isNaN(Date.parse(value)))) throw new Error(t("Use an ISO timestamp with a timezone.", "请填写含时区的 ISO 时间。")); } }]}><Input maxLength={40} autoComplete="off" /></Form.Item>
        </div>
      </div> : null}
      {!creating ? <div className="form-section">
        <Form.Item name="publication_note" label={t("Review or withdrawal reason", "审阅或撤回原因")} rules={[required, { max: 2000 }]}><Input.TextArea rows={3} showCount maxLength={2000} /></Form.Item>
        <Form.Item name="reviewed" valuePropName="checked" rules={[{ validator: (_, value) => value ? Promise.resolve() : Promise.reject(new Error(t("Confirm your review before continuing.", "请先确认审阅。"))) }]}><Checkbox>{retracting ? t("I confirm withdrawal of this shared experience.", "我确认撤回此共享经验。") : t("I reviewed this text and its sharing scope, and removed sensitive information.", "我已审阅正文与共享范围，并移除敏感信息。")}</Checkbox></Form.Item>
      </div> : null}
      <Space wrap><Button type="primary" danger={retracting} htmlType="submit" loading={busy} disabled={blocked}>{title}</Button><Button onClick={onClose} disabled={busy}>{t("Close editor", "关闭编辑")}</Button></Space>
    </Form>
    <Typography.Paragraph className="muted" style={{ marginTop: 16, marginBottom: 0 }}>{t("The draft stays on this page while you work. The durable recovery journal keeps only the original operation key and recovery metadata, without experience text.", "操作期间草稿保留在当前页面。持久恢复账本仅保存原操作 key 与恢复元数据，不保存经验正文。")}</Typography.Paragraph>
  </section>;
}

export function MemoryWorkspace({ projectId }: { projectId: string }) {
  const { t, formatDate } = useI18n(); const operation = useMemoryOperation(projectId);
  const [editor, setEditor] = useState<Editor | null>(null), [selected, setSelected] = useState<MemoryEntry | null>(null);
  const [query, setQuery] = useState(""), [tab, setTab] = useState("shared"), [historyVersion, setHistoryVersion] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const requestedStatus = tab === "candidates" ? "CANDIDATE" : tab === "history" ? "RETRACTED" : "PUBLISHED";
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId, true) });
  const setup = useQuery({ queryKey: ["memory-web-setup"], queryFn: () => memoryRequest<{ configured: boolean }>("setup") });
  const records = useQuery({ queryKey: ["memory", projectId, requestedStatus, page], queryFn: () => memoryProject(projectId, requestedStatus, (page - 1) * 20), enabled: setup.data?.configured === true, retry: false });
  const search = useMutation({ mutationFn: (text: string) => memoryQuery(projectId, text) });
  const selectedId = useRef<string | null>(null);
  const history = useMutation({ mutationFn: ({ id, version }: { id: string; version: number }) => memoryEntry(projectId, id, version), onSuccess: (entry) => { if (selectedId.current === entry.id) setSelected(entry); } });
  const enabled = setup.data?.configured === true && records.data?.enabled === true && records.data?.configuration.enabled === true;
  const canEdit = enabled && project.isSuccess && !project.isError && !project.data?.deleted_at;
  useEffect(() => { if (operation.receipt) void records.refetch(); }, [operation.receipt]);
  const entries = records.data?.entries || [];
  const displayed = entries;
  async function submit(fields: Omit<MemoryMutation, "project_id" | "operation_key">) { const response = await operation.submit(fields); if (response) { setEditor(null); await records.refetch(); return true; } return false; }
  const statusText = (status: string) => ({ CANDIDATE: t("Private candidate", "私有候选"), PUBLISHED: t("Shared", "已共享"), RETRACTED: t("Withdrawn", "已撤回"), PENDING: t("Awaiting reconciliation", "待对账"), SUPERSEDED: t("Superseded revision", "已被后续修订替代"), EXPIRED: t("Expired reference", "已过期参考") })[status] || status;
  const actionText = (action: MemoryAction) => ({ CONFIGURE: t("Project memory settings", "项目经验配置"), CREATE_CANDIDATE: t("Save candidate", "保存候选"), PUBLISH: t("Publish", "发布"), REVISE: t("Append revision", "追加修订"), RETRACT: t("Withdraw", "撤回") })[action];
  function show(entry: MemoryEntry) { selectedId.current = entry.id; history.reset(); setSelected(entry); setHistoryVersion(entry.version); }
  const columns = [
    { title: t("Experience", "经验"), key: "title", render: (_: unknown, entry: MemoryEntry) => <Button type="link" style={{ padding: 0, whiteSpace: "normal", textAlign: "start", height: "auto" }} onClick={() => show(entry)}>{entry.title}</Button> },
    { title: t("Visibility", "可见范围"), key: "status", render: (_: unknown, entry: MemoryEntry) => <Tag color={entry.status === "CANDIDATE" ? "gold" : undefined}>{statusText(entry.status)}</Tag> },
    { title: t("Revision", "修订"), dataIndex: "version", key: "version" },
    { title: t("Updated", "更新时间"), key: "updated", render: (_: unknown, entry: MemoryEntry) => entry.updated_at ? formatDate(entry.updated_at) : "—" },
    { title: t("Actions", "操作"), key: "actions", render: (_: unknown, entry: MemoryEntry) => <Space wrap>
      {entry.status === "CANDIDATE" ? <Button size="small" disabled={!canEdit || operation.blocked} onClick={() => setEditor({ action: "PUBLISH", entry })}>{t("Review and publish", "审阅并发布")}</Button> : null}
      {["PUBLISHED", "EXPIRED"].includes(entry.status) ? <><Button size="small" disabled={!canEdit || operation.blocked} onClick={() => setEditor({ action: "REVISE", entry })}>{t("Append revision", "追加修订")}</Button><Button size="small" danger disabled={!canEdit || operation.blocked} onClick={() => setEditor({ action: "RETRACT", entry })}>{t("Withdraw", "撤回")}</Button></> : null}
    </Space> },
  ];
  return <main className="workspace-page">
    <WorkspaceHeading title={<>{project.data?.name || t("Project", "项目")} · {t("Project experience", "项目经验")}</>}
      backHref={`/projects/${projectId}`} backLabel={t("Project workspace", "项目工作台")}
      description={t("Select a lesson from an accepted report, review it privately, then publish a reusable reference for this project.", "从已接受报告中选取经验，私下审阅后，发布为本项目可复用的参考。")}
      actions={<Button icon={<ReloadOutlined aria-hidden />} loading={records.isFetching} onClick={() => { void setup.refetch(); void records.refetch(); }}>{t("Refresh", "刷新")}</Button>} />
    <ProjectNavigation projectId={projectId} active="memory" />
    <Alert showIcon type="info" message={t("Historical reference, requiring current verification", "历史参考，需要结合当前环境核验")} description={t("Experience can contain outdated or untrusted statements. It grants no execution permission and never changes task state, reported results or verified evidence. Task synchronization remains available when memory is unavailable.", "经验可能包含过时或不可信表述，不授予执行权限，也不会改变任务状态、报告结果或已验证证据。经验不可用时，任务同步仍可继续。 ")} style={{ marginBottom: 20 }} />
    {setup.isPending || (setup.data?.configured && records.isPending) ? <WorkspaceLoading label={t("Loading project experience", "正在读取项目经验")} /> : null}
    {setup.isError || setup.data?.configured === false || records.isError ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Project experience is unavailable", "项目经验暂不可用")} description={t("Loaded records and your draft are retained. Refresh to check independent memory access; return to the project workspace to continue task work.", "保留已加载记录与草稿。请刷新核对独立经验访问权限；可返回项目工作台继续处理任务。 ")} /> : null}
    {project.data?.deleted_at || project.isError ? <Alert showIcon type="warning" style={{ marginBottom: 20 }} message={t("Project changes are unavailable", "暂不能修改项目")} description={t("Check project access or restore the project before changing experience.", "请核对项目权限或恢复项目后，再修改经验。 ")} /> : null}
    {records.data ? <section className="workspace-panel" aria-labelledby="memory-settings-title" style={{ marginBottom: 24 }}><div className="activity-heading"><div><Typography.Title id="memory-settings-title" level={2}>{t("Project memory access", "项目经验访问")}</Typography.Title><Typography.Paragraph className="muted" style={{ marginBottom: 0 }}>{t("Uses a separate project scope and memory permissions. Local and Cloud task grants do not authorize memory access.", "使用独立项目空间与经验权限；Local 与 Cloud 任务授权不包含经验访问。 ")}</Typography.Paragraph></div><Button disabled={operation.blocked || project.isError || !project.data || Boolean(project.data.deleted_at) || records.data.enabled === false} loading={operation.busy} onClick={() => void submit({ operation: "CONFIGURE", expected_version: records.data!.configuration.version, enabled: !records.data!.configuration.enabled })}>{records.data.configuration.enabled ? t("Disable project memory", "停用项目经验") : t("Enable project memory", "启用项目经验")}</Button></div><Space wrap><Tag>{records.data.configuration.enabled ? t("Enabled", "已启用") : t("Disabled", "已停用")}</Tag><Typography.Text className="muted">{t("Configuration revision: ", "配置修订：")}{records.data.configuration.version}</Typography.Text></Space></section> : null}
    {operation.pending ? <Alert type="warning" showIcon style={{ marginBottom: 20 }} message={t("An original memory operation needs reconciliation", "一项原始经验操作需要对账")} description={<Space direction="vertical" size={8}><Typography.Text>{actionText(operation.pending.operation)} · {operation.pending.state}</Typography.Text><Typography.Text code copyable style={{ overflowWrap: "anywhere" }}>{operation.pending.operation_key}</Typography.Text><Typography.Text>{t("Only this original key will be queried. A missing receipt, lost response or unknown upstream outcome does not permit a replacement POST. Fixed accepted revision readback must complete before this stream is released.", "只会查询此原 key。回执暂缺、响应丢失或上游结果未知，都不会换 key 或再次 POST；固定接受修订完整读回后才释放此操作流。 ")}</Typography.Text></Space>} action={<Button loading={operation.busy} onClick={() => void operation.reconcile()}>{t("Query original receipt", "查询原回执")}</Button>} /> : null}
    {records.data?.operations?.length ? <section className="workspace-panel" aria-labelledby="memory-unresolved-title" style={{ marginBottom: 24 }}><Typography.Title id="memory-unresolved-title" level={2}>{t("Unresolved memory operations", "未决经验操作")}</Typography.Title><Typography.Paragraph className="muted">{t("Recover a previously sent operation by its original key. Recovery only queries its receipt; it never sends its request again.", "按原 key 恢复已发送操作。恢复仅查询回执，不会再次发送原请求。 ")}</Typography.Paragraph><Space direction="vertical" style={{ width: "100%" }}>{records.data.operations.map((row) => <Space wrap key={row.operation_key}><Typography.Text>{actionText(row.operation)} · {row.status}</Typography.Text><Typography.Text code copyable style={{ overflowWrap: "anywhere" }}>{row.operation_key}</Typography.Text><Button disabled={operation.blocked} onClick={() => void operation.recoverOriginal(row)}>{t("Recover original receipt", "恢复原回执")}</Button></Space>)}</Space></section> : null}
    {operation.issue && !operation.pending ? <Alert type="error" showIcon style={{ marginBottom: 20 }} message={operation.issue === "MEMORY_STORAGE_UNAVAILABLE" ? t("Memory recovery storage is unavailable; nothing was submitted", "经验恢复存储不可用，未提交请求") : t("Memory operation was rejected", "经验操作被拒绝")} description={t("Keep your draft. Check browser storage, project access and the current accepted version before submitting a new intention.", "请保留草稿，核对浏览器存储、项目权限与当前接受版本后，再提交新的操作意图。 ")} /> : null}
    {operation.receipt ? <Alert showIcon type="success" style={{ marginBottom: 20 }} message={t("Memory operation read back at its accepted revision", "经验操作已按固定接受修订完整读回")} description={`${actionText(operation.receipt.operation)} · ${t("revision", "修订")} ${operation.receipt.accepted_version}`} /> : null}
    <section className="workspace-panel" aria-labelledby="memory-search-title"><Typography.Title id="memory-search-title" level={2}>{t("Search shared experience", "检索共享经验")}</Typography.Title>
      <Input.Search value={query} onChange={(event) => { setQuery(event.target.value); search.reset(); }} maxLength={1000} aria-label={t("Explicit experience query", "显式经验查询")} placeholder={t("Describe the issue or framework to look up", "输入需要查找的问题或框架")} enterButton={t("Search", "检索")} loading={search.isPending} disabled={!enabled} onSearch={(value) => { if (value.trim()) search.mutate(value.trim()); }} />
      <Typography.Paragraph className="muted" style={{ marginTop: 8 }}>{t("Only this explicit query is sent. Current prompts and conversations are never attached. Retrieval returns published, active experience from this project.", "仅发送此显式查询，不附带当前 prompt 或会话。检索仅返回本项目已发布且有效的经验。 ")}</Typography.Paragraph>
      {search.isError && search.variables === query.trim() ? <Alert showIcon type="warning" message={t("Search is unavailable. Your query is retained; retry when the service is available.", "检索暂不可用。查询内容已保留，请在服务恢复后重试。 ")} /> : null}
      {search.data && search.variables === query.trim() ? <><Typography.Paragraph>{search.data.degraded ? t("The external index is unavailable; results use the accepted local reference index.", "外部索引不可用，当前结果使用已接受的本地参考索引。") : t("Search results", "检索结果")}</Typography.Paragraph><Table<MemoryEntry> rowKey="id" dataSource={search.data.results} columns={columns.slice(0, 3)} pagination={false} scroll={{ x: 520 }} locale={{ emptyText: <Empty description={t("No published experience matches this query.", "没有匹配此查询的已发布经验。 ")} /> }} /></> : null}
    </section>
    <section className="workspace-panel" aria-labelledby="memory-list-title"><div className="activity-heading"><Typography.Title id="memory-list-title" level={2}>{t("Experience records", "经验记录")}</Typography.Title><Button type="primary" disabled={!canEdit || operation.blocked} onClick={() => setEditor({ action: "CREATE_CANDIDATE" })}>{t("Add private candidate", "新增私有候选")}</Button></div>
      <Tabs className="workspace-tabs" activeKey={tab} onChange={(value) => { setTab(value); setPage(1); }} animated={false} items={[{ key: "shared", label: t("Shared", "已共享") }, { key: "candidates", label: t("Private candidates", "私有候选") }, { key: "history", label: t("Withdrawn", "已撤回") }]} />
      <Table<MemoryEntry> rowKey="id" loading={records.isPending && setup.data?.configured === true} dataSource={displayed} columns={columns} scroll={{ x: 750 }} pagination={false} locale={{ emptyText: <Empty description={tab === "candidates" ? t("No private candidates. Add a selected lesson with a fixed report reference.", "暂无私有候选。可添加选定经验，并引用固定版本报告。 ") : tab === "history" ? t("No withdrawn experience.", "暂无已撤回经验。") : t("No shared experience yet. Review and publish a private candidate to share it.", "暂无共享经验。审阅并发布私有候选后即可共享。 ")} /> }} />
      <Space wrap style={{ marginTop: 16 }}><Button disabled={page <= 1 || records.isFetching} onClick={() => setPage((value) => value - 1)}>{t("Previous page", "上一页")}</Button><Typography.Text>{t("Page", "第")} {page}</Typography.Text><Button disabled={!records.data?.has_more || records.isFetching} onClick={() => setPage((value) => value + 1)}>{t("Next page", "下一页")}</Button></Space>
    </section>
    {editor ? <MemoryEditor key={`${editor.action}:${editor.entry?.id || "new"}:${editor.entry?.version || 0}`} editor={editor} blocked={!canEdit || operation.blocked} busy={operation.busy} onSubmit={submit} onClose={() => setEditor(null)} /> : null}
    {selected ? <section className="workspace-panel" aria-labelledby="memory-detail-title" style={{ marginTop: 24, overflowWrap: "anywhere" }}><div className="activity-heading"><Typography.Title id="memory-detail-title" level={2}>{selected.title}</Typography.Title><Button onClick={() => { selectedId.current = null; setSelected(null); }}>{t("Close details", "关闭详情")}</Button></div><Space wrap style={{ marginBottom: 16 }}><Tag>{statusText(selected.status)}</Tag><Typography.Text>{t("Revision", "修订")} {selected.version}</Typography.Text><Typography.Text code copyable>{selected.id}</Typography.Text></Space><Typography.Paragraph style={{ whiteSpace: "pre-wrap", maxWidth: "72ch" }}>{selected.content}</Typography.Paragraph>
      <Descriptions column={1} size="small"><Descriptions.Item label={t("When this applies", "适用条件")}>{selected.applicability || "—"}</Descriptions.Item><Descriptions.Item label={t("Observed", "观察时间")}>{selected.observed_at ? formatDate(selected.observed_at) : t("Not specified", "未指定")}</Descriptions.Item><Descriptions.Item label={t("Expires", "有效期至")}>{selected.expires_at ? formatDate(selected.expires_at) : t("Not specified", "未指定")}</Descriptions.Item><Descriptions.Item label={t("Review note", "审阅说明")}>{selected.publication_note || "—"}</Descriptions.Item></Descriptions>
      {selected.source ? <details style={{ marginTop: 16 }}><summary>{t("Authorized provenance reference", "获授权的来源引用")}</summary><pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(selected.source, null, 2)}</pre></details> : null}
      <Space wrap style={{ marginTop: 20 }}><label htmlFor="memory-history-version">{t("Read fixed revision", "读取固定修订")}</label><InputNumber id="memory-history-version" min={1} precision={0} value={historyVersion} onChange={setHistoryVersion} /><Button loading={history.isPending} disabled={!historyVersion} onClick={() => { if (historyVersion) history.mutate({ id: selected.id, version: historyVersion }); }}>{t("Read revision", "读取修订")}</Button></Space>{history.isError ? <Alert showIcon type="warning" style={{ marginTop: 16 }} message={t("This revision could not be read. The displayed revision is retained.", "无法读取此修订。当前显示的修订已保留。 ")} /> : null}
    </section> : null}
  </main>;
}
