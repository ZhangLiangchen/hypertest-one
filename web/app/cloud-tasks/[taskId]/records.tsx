"use client";

import { useState } from "react";
import { Alert, Button, Descriptions, Empty, Modal, Space, Table, Tag, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { cloudProgressTone, cloudRequest } from "@/lib/cloud";
import type { CloudAsset, CloudDocument, CloudRecord } from "@/lib/cloud";
import { ReportedResultTag } from "@/app/tasks/task-records";

const literal = (value: unknown): string => typeof value === "string" ? value : value === null || value === undefined ? "—" : JSON.stringify(value, null, 2);

export function CloudTaskRecords({ document }: { document: CloudDocument }) {
  const { t, label, formatDate } = useI18n(); const [original, setOriginal] = useState<{ filename: string; content: string } | null>(null);
  const [reading, setReading] = useState<string | null>(null); const [readError, setReadError] = useState(false);
  async function readArtifact(id: string) {
    setReading(id); setReadError(false);
    try { setOriginal(await cloudRequest<{ filename: string; content: string }>(`tasks/${document.task.id}/artifacts/${id}?project_id=${document.task.project_id}&readback=complete`)); }
    catch { setReadError(true); } finally { setReading(null); }
  }
  function assetBody(asset: CloudAsset) {
    return <div style={{ padding: "12px 0" }}>
      <Typography.Paragraph className="muted">{t("Revision", "修订")}: {asset.revision} · {t("Task version", "任务版本")}: {asset.task_version} · <span className="entity-key">{asset.attempt_id}</span></Typography.Paragraph>
      {asset.kind === "CASE" ? <Descriptions column={1} items={[
        { key: "steps", label: t("Steps", "步骤"), children: <pre className="session-literal">{literal(asset.details.steps)}</pre> },
        { key: "expected", label: t("Expected", "预期"), children: <pre className="session-literal">{literal(asset.details.expected)}</pre> },
        { key: "actual", label: t("Reported observation", "报告观察"), children: <pre className="session-literal">{literal(asset.details.actual)}</pre> },
      ]} /> : null}
      {asset.markdown ? <pre className="artifact-content session-markdown" aria-label={t("Original testing artifact", "原始测试产物")}>{asset.markdown}</pre> : null}
      {asset.kind === "IMPLEMENTATION" ? <Descriptions column={1} items={[
        { key: "sha", label: t("Framework baseline", "框架基线"), children: <span className="entity-key">{literal(asset.details.framework_sha)}</span> },
        { key: "cwd", label: t("Working directory", "工作目录"), children: literal(asset.details.cwd) },
        { key: "changes", label: t("Changed / new files", "变更 / 新增文件"), children: <pre className="session-literal">{literal({ changed: asset.details.dirty_files, new_files: asset.details.untracked_files })}</pre> },
      ]} /> : null}
      {asset.artifact_id ? <Button onClick={() => void readArtifact(asset.artifact_id!)} loading={reading === asset.artifact_id}>{t("Read original attachment", "读取原始附件")}</Button> : null}
    </div>;
  }
  return <Space direction="vertical" size={28} style={{ width: "100%" }}>
    <section aria-labelledby="cloud-assets-title"><Typography.Title id="cloud-assets-title" level={2}>{t("Test artifacts and revision history", "测试产物与修订历史")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("Analysis, design, cases, code and reports retain each accepted revision. A later PASS does not remove earlier FAIL results.", "分析、设计、用例、代码和报告保留每个接受修订；后续通过不会删除此前失败。 ")}</Typography.Paragraph>
      <div className="data-surface"><Table rowKey="id" dataSource={document.assets || []} scroll={{ x: 780 }} pagination={{ pageSize: 20, hideOnSinglePage: true }} expandable={{ expandedRowRender: assetBody }} locale={{ emptyText: <Empty description={t("No formal artifacts have been accepted yet.", "尚无已接受的正式产物。 ")} /> }} columns={[
        { title: t("Artifact", "产物"), key: "title", render: (_, row) => <><strong>{row.title}</strong><div className="entity-key">{row.key}</div></> },
        { title: t("Kind", "类型"), dataIndex: "kind" }, { title: t("Revision", "修订"), dataIndex: "revision" },
        { title: t("Reported result", "报告结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> },
      ]} /></div>
    </section>
    <section aria-labelledby="cloud-runs-title"><Typography.Title id="cloud-runs-title" level={2}>{t("Every framework execution", "每轮框架执行")}</Typography.Title>
      <div className="data-surface"><Table rowKey={(row) => String(row.id)} dataSource={document.runs || []} scroll={{ x: 750 }} pagination={{ pageSize: 20, hideOnSinglePage: true }} locale={{ emptyText: t("No execution has been reported. SDK activity does not create a test run.", "尚无已报告执行；SDK 活动不会生成测试执行记录。 ") }}
        columns={[{ title: t("Run key", "执行标识"), dataIndex: "run_key", render: (value) => <span className="entity-key">{literal(value)}</span> },
          { title: t("Source", "来源"), key: "source", render: (_, row) => literal((row.execution as CloudRecord)?.source) },
          { title: t("Command", "执行命令"), key: "command", render: (_, row) => <span className="session-literal">{literal((row.execution as CloudRecord)?.entrypoint)}</span> },
          { title: t("Result", "结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> }]}
        expandable={{ expandedRowRender: (row) => { const execution = row.execution as CloudRecord || {}; const cases = document.run_cases?.filter((item) => item.run_id === row.id) || []; return <>
          <Descriptions column={1} items={[{ key: "build", label: t("Observed SUT build", "观察到的被测版本"), children: literal(execution.actual_sut_build) },
            { key: "framework", label: t("Framework SHA", "框架 SHA"), children: <span className="entity-key">{literal(execution.framework_sha)}</span> },
            { key: "start", label: t("Started", "开始时间"), children: typeof execution.started_at === "string" ? formatDate(execution.started_at) : "—" },
            { key: "finish", label: t("Finished / exit", "结束 / 退出码"), children: `${typeof execution.finished_at === "string" ? formatDate(execution.finished_at) : literal(execution.unobserved_reason)} · ${literal(execution.exit_code)}` },
          ]} />
          <Table rowKey={(item) => String(item.id)} size="small" pagination={false} dataSource={cases} scroll={{ x: 560 }} columns={[
            { title: t("Case revision", "用例修订"), dataIndex: "case_revision_id", render: (value) => <span className="entity-key">{literal(value)}</span> },
            { title: t("Actual observation", "实际观察"), dataIndex: "actual", render: (value) => <span className="session-literal">{literal(value)}</span> },
            { title: t("Result", "结果"), dataIndex: "reported_result", render: (value) => <ReportedResultTag result={value} /> },
          ]} />
        </>; } }} /></div>
    </section>
    <section aria-labelledby="cloud-attachments-title"><Typography.Title id="cloud-attachments-title" level={2}>{t("Original reports, logs and code attachments", "原始报告、日志与代码附件")}</Typography.Title>
      {readError ? <Alert showIcon type="error" message={t("Original bytes could not be verified. Retry the same attachment.", "无法核验原始字节，请重试读取同一附件。 ")} style={{ marginBottom: 16 }} /> : null}
      <div className="data-surface"><Table rowKey={(row) => String(row.id)} dataSource={document.artifacts || []} pagination={{ pageSize: 20, hideOnSinglePage: true }} scroll={{ x: 600 }} columns={[
        { title: t("File", "文件"), dataIndex: "filename" }, { title: t("Bytes", "字节数"), dataIndex: "byte_count" },
        { title: "SHA-256", dataIndex: "sha256", render: (value) => <span className="entity-key">{literal(value)}</span> },
        { title: t("Action", "操作"), key: "read", render: (_, row) => <Button loading={reading === row.id} onClick={() => void readArtifact(String(row.id))}>{t("Read original", "读取原文")}</Button> },
      ]} /></div>
    </section>
    <section aria-labelledby="cloud-delegations-title"><Typography.Title id="cloud-delegations-title" level={2}>{t("Delegation observations", "委派观察")}</Typography.Title>
      <Typography.Paragraph className="muted">{t("These are runtime-reported contributions. The original child artifact and the reported run remain the sources for each task; these observations alone do not prove independent authorship or test PASS.", "以下为运行时报告的贡献记录。请核对各任务的子代理原件与执行报告；观察记录本身不证明独立作者身份或测试通过。")}</Typography.Paragraph>
      <div className="data-surface"><Table rowKey={(row) => String(row.id)} dataSource={document.delegations || []} pagination={false} scroll={{ x: 600 }} locale={{ emptyText: t("No delegation has been reported for this task.", "此任务尚无已报告的委派。") }} columns={[
        { title: "Provider", dataIndex: "provider" }, { title: t("Responsibility", "责任"), dataIndex: "responsibility" },
        { title: t("Observed state", "观察状态"), dataIndex: "status", render: (value: string) => <Tag color={cloudProgressTone(value)}>{label(value)}</Tag> },
      ]} /></div>
    </section>
    <Modal open={original !== null} onCancel={() => setOriginal(null)} footer={null} title={original?.filename} width={900}>
      <pre className="artifact-content session-markdown">{original?.content}</pre>
    </Modal>
  </Space>;
}
