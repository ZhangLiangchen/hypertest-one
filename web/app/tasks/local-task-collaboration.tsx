"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Empty, Input, Select, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { errorText, getTaskCollaboration } from "@/lib/api";
import { collaborationProfile } from "@/lib/local-collaboration";
import type { CollaborationDocument, CollaborationOperation, CollaborationRequest, TaskContribution, TaskParticipant } from "@/lib/local-collaboration";
import { useCollaborationOperation } from "@/lib/local-collaboration-operation";
import { useI18n } from "@/lib/i18n";
import type { ReportedResult, SessionTask } from "@/lib/types";
import { createUuid } from "@/lib/uuid";
import { ReportedResultTag } from "./task-records";

type Draft = { operation: CollaborationOperation; version: number; generation: number; provider: string; session: string; assignment: string; participant: string; materials: string; unresolved: string };
const results = ["NOT_RUN", "PASS", "FAIL", "ERROR", "SKIPPED", "UNKNOWN", "BLOCKED"];
const lines = (value: string) => value.split("\n").map((line) => line.trim()).filter(Boolean);

export function LocalTaskCollaboration({ task }: { task: SessionTask }) {
  const { t, locale, formatDate } = useI18n();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["task-collaboration", task.id, task.version], queryFn: () => getTaskCollaboration(task.id), retry: false });
  const operation = useCollaborationOperation(task.project_id, task.id);
  const [draft, setDraft] = useState<Draft | null>(null), [invalid, setInvalid] = useState(false);
  const [success, setSuccess] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const doc = query.data, state = doc?.collaboration;
  const currentTask = doc?.task || task;
  const canManage = false; // ADR-027 retires new legacy writes; original-key read recovery stays available.
  const primary = state?.participants.find((item) => item.id === state.primary_participant_id && item.status === "ACTIVE");
  const name = (value: string) => ({ ENABLE: t("Enable collaboration", "启用多会话协作"), AUTHORIZE: t("Authorize session", "授权会话加入"), REVOKE: t("Revoke session", "撤销会话权限"), HANDOFF: t("Hand off primary role", "交接主会话"), JOIN: t("Session joined", "会话已加入"), CONTRIBUTE: t("Contribution accepted", "贡献已接受"), PUBLISH: t("Summary published", "汇总已发布") }[value] || value);
  function open(action: CollaborationOperation, participant = "") {
    setDraft({ operation: action, version: currentTask.version, generation: state?.primary_generation || 0, provider: "codex", session: "", assignment: "", participant, materials: "", unresolved: "" });
    setInvalid(false); setSuccess(false);
  }
  async function accepted(result: CollaborationDocument | null) {
    if (!result) return;
    queryClient.setQueryData(["task-collaboration", task.id, task.version], result);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["session-task", task.id] }),
      queryClient.invalidateQueries({ queryKey: ["task-collaboration", task.id] }),
      queryClient.invalidateQueries({ queryKey: ["project-tasks", task.project_id] }),
    ]);
    setDraft(null); setInvalid(false); setSuccess(true);
  }
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft) return;
    if ((draft.operation === "AUTHORIZE" && (!draft.provider.trim() || !draft.session.trim() || !task.owner_actor_ref))
      || (["REVOKE", "HANDOFF"].includes(draft.operation) && !draft.participant)) { setInvalid(true); return; }
    const payload: CollaborationRequest = { profile: collaborationProfile, operation: draft.operation, expected_version: draft.version, idempotency_key: createUuid() };
    if (draft.operation === "AUTHORIZE") Object.assign(payload, { actor_ref: task.owner_actor_ref, provider: draft.provider.trim(), session_id: draft.session.trim(), assignment: draft.assignment });
    if (["REVOKE", "HANDOFF"].includes(draft.operation)) payload.participant_id = draft.participant;
    if (draft.operation === "HANDOFF") Object.assign(payload, { expected_primary_generation: draft.generation, handoff: { materials: lines(draft.materials), unresolved_items: lines(draft.unresolved), private_journals_observed: false } });
    setSuccess(false); await accepted(await operation.submit(payload));
  }
  const update = (value: Partial<Draft>) => { if (draft) setDraft({ ...draft, ...value }); };
  const fieldId = (field: string) => `collaboration-${task.id}-${field}`;
  const participantLabel = (item: TaskParticipant) => `${item.provider} · ${item.session_id}`;
  return <section id="task-collaboration" tabIndex={-1} className="data-surface session-record session-collaboration" aria-labelledby="local-collaboration-heading">
    <div className="session-collaboration-heading">
      <div><Typography.Title id="local-collaboration-heading" level={2}>{t("Session collaboration", "会话协作")}</Typography.Title>
        <Typography.Paragraph className="muted">{t("Legacy session participation, contributions and published summaries retain their original sources and reported results. New work uses explicit CLI archives.", "旧会话参与关系、贡献与汇总保留原始来源和报告结果。新的工作使用 CLI 显式归档。")}</Typography.Paragraph></div>
      <Space wrap>
        <Button onClick={() => void query.refetch()} loading={query.isFetching}>{t("Refresh sessions", "刷新会话")}</Button>
        {canManage && state && !draft ? <Button type="primary" disabled={operation.blocked} onClick={() => open(state.enabled ? "AUTHORIZE" : "ENABLE")}>{state.enabled ? name("AUTHORIZE") : name("ENABLE")}</Button> : null}
      </Space>
    </div>
    {query.isLoading ? <Typography.Paragraph role="status">{t("Loading session collaboration…", "正在读取会话协作…")}</Typography.Paragraph> : null}
    {query.isError ? <Alert type="warning" showIcon message={t("Unable to refresh collaboration", "无法刷新协作记录")} description={errorText(query.error, locale)} style={{ marginBottom: 16 }} /> : null}
    {state ? <>
      <Descriptions column={3} layout="vertical" items={[
        { key: "enabled", label: t("Collaboration", "协作状态"), children: <Tag color={state.enabled ? "blue" : undefined}>{state.enabled ? t("Enabled", "已启用") : t("Single session", "单会话")}</Tag> },
        { key: "primary", label: t("Current primary session", "当前主会话"), children: primary ? <span className="entity-key">{participantLabel(primary)}</span> : state.enabled ? t("No primary; overall publishing is paused", "暂无主会话，整体汇总暂停") : t("No primary recorded", "未记录主会话") },
        { key: "generation", label: t("Primary generation", "主会话代次"), children: state.enabled ? state.primary_generation : "—" },
      ]} />
      {state.enabled ? <Table<TaskParticipant> rowKey="id" size="small" dataSource={state.participants} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 960 }} columns={[
        { title: t("Session and authorization", "会话与授权"), key: "source", width: 300, render: (_, item) => <><strong>{item.provider}</strong>{item.initial_binding ? <Tag style={{ marginLeft: 8 }}>{t("Initial source", "初始来源")}</Tag> : null}<div className="entity-key">{item.session_id}</div><div className="muted entity-key">{item.actor_ref}</div></> },
        { title: t("Participation", "参与状态"), key: "status", width: 170, render: (_, item) => <Space direction="vertical" size={4}><Tag color={item.status === "ACTIVE" ? "green" : item.status === "AUTHORIZED" ? "gold" : undefined}>{item.status === "ACTIVE" ? t("Joined", "已加入") : item.status === "AUTHORIZED" ? t("Authorized; awaiting JOIN", "已授权，待加入") : t("Revoked", "已撤销")}</Tag><span>{item.role === "PRIMARY" && item.status === "ACTIVE" ? t("Primary", "主会话") : t("Contributor", "贡献会话")}</span></Space> },
        { title: t("Assignment", "分工"), dataIndex: "assignment", render: (value) => <span className="session-literal">{value || t("Not specified", "未指定")}</span> },
        { title: t("Joined / revoked", "加入 / 撤销时间"), key: "time", width: 190, render: (_, item) => item.status === "REVOKED" ? formatDate(item.revoked_at) : item.status === "AUTHORIZED" ? t("Awaiting real session JOIN", "等待真实会话加入") : item.joined_at ? formatDate(item.joined_at) : t("Initial binding retained", "沿用初始绑定") },
        { title: t("Actions", "操作"), key: "actions", width: 180, render: (_, item) => canManage && item.status !== "REVOKED" ? <Space direction="vertical" size={4}>
          {item.status === "ACTIVE" && item.id !== state.primary_participant_id ? <Button size="small" disabled={operation.blocked || !!draft} onClick={() => open("HANDOFF", item.id)}>{t("Make primary", "设为主会话")}</Button> : null}
          <Button size="small" danger disabled={operation.blocked || !!draft} onClick={() => open("REVOKE", item.id)}>{t("Revoke access", "撤销权限")}</Button>
        </Space> : "—" },
      ]} locale={{ emptyText: t("No participants have joined.", "暂无参与会话。") }} /> : <Typography.Paragraph className="muted">{task.binding_state === "UNBOUND" ? t("No session was bound to this historical task.", "此历史任务未绑定会话。") : t("This task retained its single-session history.", "此任务保留原单会话历史。")}</Typography.Paragraph>}
    </> : null}
    {operation.storageError ? <Alert type="error" showIcon message={t("Private operation journal unavailable", "私有操作账本不可用")} description={t("New changes are blocked. Restore browser storage access and reload; keep this browser's pending requests.", "当前禁止新变更。请恢复浏览器存储访问后刷新，并保留此浏览器中的未决请求。") } style={{ marginBlock: 16 }} /> : null}
    {operation.pending ? <Alert type="warning" showIcon message={t("A frozen operation is awaiting confirmation", "一项已冻结操作正在等待确认")} description={<>
      <p>{name(operation.pending.operation)} · {t("Expected version", "预期版本")} {operation.pending.expected_version}</p><Typography.Text code copyable>{operation.pending.idempotency_key}</Typography.Text>
      <p>{t("Only the original key is queried, including when no receipt is found. No automatic resubmission occurs.", "仅查询原 key；即使尚未找到回执，也不会自动重新提交。")}</p>
    </>} action={<Button loading={operation.busy} onClick={() => void operation.reconcile().then(accepted)}>{t("Query original request", "查询原请求")}</Button>} style={{ marginBlock: 16 }} /> : null}
    {operation.error ? <Alert type="error" showIcon message={t("Operation is not confirmed", "操作尚未确认")} description={<>{errorText(operation.error, locale)} {!operation.pending ? <p>{t("Your input is preserved. Refresh the sessions and review the latest version before a new submission.", "当前输入已保留。请刷新会话记录，核对最新版本后再提交新意图。")}</p> : null}</>} style={{ marginBlock: 16 }} /> : null}
    {success ? <Alert type="success" showIcon message={t("Change confirmed at its accepted version", "已按固定接受版本确认变更")} style={{ marginBlock: 16 }} /> : null}
    {draft ? <form className="session-collaboration-form" onSubmit={(event) => void submit(event)}>
      <Typography.Title level={3}>{name(draft.operation)}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Expected task version", "预期任务版本")}: {draft.version}{draft.operation === "HANDOFF" ? ` · ${t("Primary generation", "主会话代次")}: ${draft.generation}` : ""}</Typography.Paragraph>
      {draft.operation === "ENABLE" ? <Typography.Paragraph>{t("The initial bound session becomes primary. Additional sessions must receive an exact authorization and JOIN from their supported local client. This action does not start Agents or tests.", "初始绑定会话成为主会话。其他会话须先获得精确授权，再由受支持本地客户端完成 JOIN。此操作不会启动 Agent 或测试。")}</Typography.Paragraph> : null}
      {draft.operation === "AUTHORIZE" ? <>
        <Typography.Paragraph>{t("Task owner client", "任务所属客户端")}: <Typography.Text code>{task.owner_actor_ref || t("Unavailable", "不可用")}</Typography.Text></Typography.Paragraph>
        <div className="session-collaboration-fields">
          <label htmlFor={fieldId("provider")}>{t("Exact provider", "精确 Provider")}<Input id={fieldId("provider")} required pattern="[a-z][a-z0-9_-]{0,63}" maxLength={64} value={draft.provider} disabled={operation.blocked} onChange={(event) => update({ provider: event.target.value })} /></label>
          <label htmlFor={fieldId("session")}>{t("Exact root session ID", "精确根会话 ID")}<Input id={fieldId("session")} required maxLength={512} value={draft.session} disabled={operation.blocked} onChange={(event) => update({ session: event.target.value })} /></label>
        </div>
        <label htmlFor={fieldId("assignment")}>{t("Assignment", "分工")}<Input.TextArea id={fieldId("assignment")} value={draft.assignment} maxLength={16000} rows={3} disabled={operation.blocked} onChange={(event) => update({ assignment: event.target.value })} /></label>
        <Typography.Paragraph className="muted">{t("Authorization records an intended source. The session is a participant only after its client verifies the real caller and JOIN succeeds.", "授权只登记拟加入来源。须由客户端核对真实调用来源并成功 JOIN，才显示为已加入的参与会话。")}</Typography.Paragraph>
      </> : null}
      {["REVOKE", "HANDOFF"].includes(draft.operation) ? <label htmlFor={fieldId("participant")}>{t("Participant", "参与会话")}<Select id={fieldId("participant")} aria-label={t("Participant", "参与会话")} style={{ width: "100%" }} value={draft.participant || undefined} disabled={operation.blocked}
        options={state?.participants.filter((item) => draft.operation === "HANDOFF" ? item.status === "ACTIVE" && item.id !== state.primary_participant_id : item.status !== "REVOKED").map((item) => ({ value: item.id, label: participantLabel(item) }))} onChange={(value) => update({ participant: value })} /></label> : null}
      {draft.operation === "REVOKE" ? <Typography.Paragraph>{t("Revocation blocks new work from this session and preserves its contributions and receipts. Revoking the primary pauses overall publishing until another primary is selected.", "撤销后禁止该会话提交新工作，原贡献与回执继续保留。撤销主会话后，整体汇总暂停，直到选定新的主会话。")}</Typography.Paragraph> : null}
      {draft.operation === "HANDOFF" ? <>
        <label htmlFor={fieldId("materials")}>{t("Handoff materials (one per line)", "交接材料（每行一项）")}<Input.TextArea id={fieldId("materials")} value={draft.materials} rows={3} disabled={operation.blocked} onChange={(event) => update({ materials: event.target.value })} /></label>
        <label htmlFor={fieldId("unresolved")}>{t("Unresolved items (one per line)", "未决事项（每行一项）")}<Input.TextArea id={fieldId("unresolved")} value={draft.unresolved} rows={3} disabled={operation.blocked} onChange={(event) => update({ unresolved: event.target.value })} /></label>
        <Typography.Paragraph className="muted">{t("The platform has not inspected the previous session's private journals. An empty list does not prove that no operation is pending. Handoff changes responsibility; it does not restart sessions or tests.", "平台未检查旧会话的私有账本。列表为空不能证明没有未决操作。交接只变更汇总责任，不会重启会话或测试。")}</Typography.Paragraph>
      </> : null}
      {invalid ? <Alert type="error" showIcon message={t("Complete the required exact session or participant fields.", "请填写必需的精确会话信息或选择参与会话。") } /> : null}
      <Space wrap>
        <Button htmlType="submit" type="primary" loading={operation.busy} disabled={operation.blocked || !canManage}>{t("Confirm change", "确认变更")}</Button>
        <Button disabled={operation.busy || !!operation.pending} onClick={() => { setDraft(null); setInvalid(false); }}>{t("Cancel", "取消")}</Button>
        {draft.version !== currentTask.version && !operation.pending ? <Button disabled={operation.blocked} onClick={() => update({ version: currentTask.version, generation: state?.primary_generation || 0 })}>{t("Use reviewed latest version", "使用已核对的最新版本")} {currentTask.version}</Button> : null}
      </Space>
    </form> : null}
    {state?.enabled ? <>
      <Typography.Title level={3}>{t("Original contributions", "原始贡献")}</Typography.Title>
      <Table<TaskContribution> rowKey="id" size="small" dataSource={state.contributions} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 900 }} expandable={{ expandedRowRender: (item) => <pre className="artifact-content" aria-label={t("Original contribution content", "原始贡献内容")}>{JSON.stringify(item.content, null, 2)}</pre> }} columns={[
        { title: t("Contribution / revision", "贡献 / 修订"), key: "key", render: (_, item) => <><span className="entity-key">{item.kind} · {item.stable_key}</span><div>{t("Revision", "修订")} {item.revision} · {t("Task version", "任务版本")} {item.task_version}</div></> },
        { title: t("Original source", "原始来源"), key: "source", render: (_, item) => <><span className="entity-key">{item.provider} · {item.session_id}</span><div className="entity-key muted">{item.actor_ref}</div><div className="muted">{state.participants.find((p) => p.id === item.participant_id)?.assignment}</div></> },
        { title: t("Original reported result", "原始报告结果"), key: "result", width: 180, render: (_, item) => results.includes(String(item.content.reported_result)) ? <ReportedResultTag result={item.content.reported_result as ReportedResult} /> : t("Not supplied", "未提供") },
        { title: t("Accepted", "接受时间"), dataIndex: "created_at", width: 190, render: formatDate },
      ]} locale={{ emptyText: <Empty description={t("No contributions accepted yet.", "尚未接受协作贡献。") } /> }} />
      <details className="session-history" open={historyOpen} onToggle={(event) => { if (event.target === event.currentTarget) setHistoryOpen(event.currentTarget.open); }}><summary>{t("Collaboration and handoff history", "协作与交接历史")} ({doc?.operation_history.length || 0})</summary>{historyOpen ? <CollaborationHistory document={doc!} /> : null}</details>
      <Typography.Paragraph className="muted" style={{ marginTop: 16 }}>{t("Participant activity and reported results do not establish a verified verdict or complete the task automatically.", "成员活动与报告结果不会自动完成任务，也不代表独立验证的质量判定。")}</Typography.Paragraph>
    </> : null}
  </section>;
}

function CollaborationHistory({ document }: { document: CollaborationDocument }) {
  const { t, formatDate } = useI18n();
  return <Table size="small" rowKey="id" dataSource={document.operation_history} pagination={{ pageSize: 20, hideOnSinglePage: true }} columns={[
    { title: t("Operation", "操作"), dataIndex: "operation" },
    { title: t("Task version", "任务版本"), dataIndex: "task_version" },
    { title: t("Source", "来源"), key: "source", render: (_, item) => <span className="entity-key">{[item.provider, item.session_id, item.actor_ref].filter(Boolean).join(" · ")}</span> },
    { title: t("Accepted", "接受时间"), dataIndex: "created_at", render: formatDate },
  ]} expandable={{ expandedRowRender: (item) => <pre className="artifact-content">{JSON.stringify(item.request_payload, null, 2)}</pre> }} />;
}
