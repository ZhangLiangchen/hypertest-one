"use client";

import { Alert, Descriptions, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";
import type { MissionAttempt } from "@/lib/types";

function attemptColor(status: string) {
  if (status === "ACCEPTED") return "green";
  if (["REJECTED", "FAILED", "ERROR"].includes(status)) return "red";
  if (status === "CANCELLED") return "gold";
  if (["DISPATCHED", "RUNNING", "SUBMITTED", "VERIFYING"].includes(status)) return "blue";
  return "default";
}

function RecordedValue({ value }: { value: unknown }) {
  const { t } = useI18n();
  if (value == null || value === "" || (Array.isArray(value) && value.length === 0)) {
    return <Typography.Paragraph type="secondary">{t("No content was reported in this field.", "此字段未报告内容。")}</Typography.Paragraph>;
  }
  if (typeof value === "string") {
    return <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 260, overflowY: "auto" }}>{value}</Typography.Paragraph>;
  }
  return <pre className="artifact-content" style={{ maxHeight: 260, overflowY: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(value, null, 2)}</pre>;
}

function AttemptDetails({ attempt }: { attempt: MissionAttempt }) {
  const { t, label, formatDate } = useI18n();
  const [rawOpen, setRawOpen] = useState(false);
  const payload = attempt.result_payload;
  const active = ["CREATED", "DISPATCHED", "RUNNING", "SUBMITTED", "VERIFYING"].includes(attempt.status);

  if (!payload) {
    return <Alert
      type={attempt.error_code || attempt.error_message || attempt.status === "CANCELLED" ? "warning" : "info"}
      showIcon
      message={t("No Agent result is recorded for this attempt", "此尝试尚无已保存的 Agent 结果")}
      description={<Space direction="vertical" size={8} style={{ width: "100%" }}>
        <span>{attempt.error_code || attempt.error_message
          ? t("An error was recorded. Review the reported error below; no result summary is available.", "已记录错误。请查看下方错误原文；本次没有可展示的结果摘要。")
          : active ? t("This attempt is in progress. A final structured result has not been recorded yet.", "本次尝试仍在进行，尚未记录最终结构化结果。")
          : attempt.status === "CANCELLED" ? t("The attempt was cancelled without a recorded structured result.", "本次尝试已取消，未记录结构化结果。")
          : t("No structured result payload was saved. Review this attempt's recorded status and error history.", "未保存结构化结果载荷，请核对本次尝试的状态与错误历史。")}</span>
        {attempt.error_code ? <Typography.Text code>{attempt.error_code}</Typography.Text> : null}
        {attempt.error_message ? <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{attempt.error_message}</span> : null}
        <span>{t("Started: ", "开始时间：")}{formatDate(attempt.started_at)} · {t("Finished: ", "结束时间：")}{formatDate(attempt.finished_at)}</span>
      </Space>}
    />;
  }

  // TMP uses `unresolved`; preserve additional raw fields from historical/provider envelopes too.
  const narrativeFields = [
    ["unresolved", t("Unresolved items reported by Agent", "Agent 报告的未决事项")],
    ["unresolved_items", t("Additional unresolved items", "附加未决事项（unresolved_items）")],
    ["risks", t("Risks reported by Agent", "Agent 报告的风险说明")],
    ["warnings", t("Agent warnings", "Agent 警告说明")],
    ["limitations", t("Agent limitations", "Agent 局限说明")],
    ["notes", t("Agent notes", "Agent 备注")],
  ].filter(([key]) => Object.prototype.hasOwnProperty.call(payload, key));

  return <Space direction="vertical" size={16} style={{ width: "100%", padding: "8px 0" }}>
    <Alert
      type="info"
      showIcon
      message={t("Agent explanations are supporting context", "Agent 说明仅作辅助参考")}
      description={t("The text below is the original Agent result, not an official test outcome. An Agent reporting COMPLETED does not mean its proposals were accepted. HyperTest's proposal acceptance and trusted Runner evidence determine canonical facts; the quality gate records the verdict.", "以下为 Agent 原始说明，不代表正式测试结果。Agent 自报完成不等于提议已被接受。正式事实以 HyperTest 的提议接受状态及可信 Runner 证据为准，质量结论由门禁记录。")}
    />
    <Descriptions bordered size="small" column={1} items={[
      { key: "attempt", label: t("Attempt status", "尝试状态"), children: <Tag title={attempt.status} color={attemptColor(attempt.status)}>{label(attempt.status)}</Tag> },
      { key: "reported", label: t("Agent-reported result status", "Agent 自报结果状态"), children: typeof payload.status === "string" ? <Tag title={payload.status}>{label(payload.status)}</Tag> : "—" },
      { key: "proposals", label: t("Submitted proposals", "提交的提议数"), children: Array.isArray(payload.proposals) ? payload.proposals.length : "—" },
      { key: "started", label: t("Started", "开始时间"), children: formatDate(attempt.started_at) },
      { key: "finished", label: t("Finished", "结束时间"), children: formatDate(attempt.finished_at) },
    ]} />
    <div style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginTop: 0 }}>{t("Agent summary · original text", "Agent 摘要 · 原文")}</Typography.Title>
      {Object.prototype.hasOwnProperty.call(payload, "summary") ? <RecordedValue value={payload.summary} /> : <Typography.Paragraph type="secondary">{t("No summary was recorded in the result payload. Inspect the full result below.", "结果载荷中未记录摘要，可展开下方完整结果查看。")}</Typography.Paragraph>}
    </div>
    {narrativeFields.map(([key, title]) => <div key={key} style={{ width: "100%" }}>
      <Typography.Title level={5} style={{ marginTop: 0 }}>{title}</Typography.Title>
      <RecordedValue value={payload[key]} />
    </div>)}
    <details style={{ width: "100%" }} onToggle={(event) => setRawOpen(event.currentTarget.open)}>
      <summary style={{ cursor: "pointer" }}>{t("Full original result JSON (including proposals)", "完整原始结果 JSON（含提议）")}</summary>
      {rawOpen ? <pre className="artifact-content" style={{ maxHeight: 420, overflowY: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(payload, null, 2)}</pre> : null}
    </details>
  </Space>;
}

export function AttemptHistory({ attempts }: { attempts: MissionAttempt[] }) {
  const { t, label, formatDate } = useI18n();
  return <Table<MissionAttempt>
    rowKey="id"
    size="small"
    dataSource={[...attempts].sort((first, second) => second.attempt_no - first.attempt_no)}
    pagination={{ pageSize: 10, hideOnSinglePage: true, showSizeChanger: false }}
    scroll={{ x: 850 }}
    locale={{ emptyText: t("No attempts have been recorded yet.", "尚无尝试记录。") }}
    columns={[
      { title: t("Attempt", "尝试序号"), dataIndex: "attempt_no", width: 80 },
      { title: t("Provider", "提供方"), dataIndex: "provider", width: 110, render: (value: string | null | undefined) => value || "—" },
      { title: t("Status", "状态"), dataIndex: "status", width: 130, render: (value: string) => <Tag title={value} color={attemptColor(value)}>{label(value)}</Tag> },
      { title: t("Started", "开始时间"), dataIndex: "started_at", width: 170, render: formatDate },
      { title: t("Finished", "结束时间"), dataIndex: "finished_at", width: 170, render: formatDate },
      { title: t("Error", "错误"), key: "error", render: (_: unknown, attempt: MissionAttempt) => attempt.error_code || attempt.error_message ? <Space direction="vertical" size={2}>
        {attempt.error_code ? <Typography.Text code>{attempt.error_code}</Typography.Text> : null}
        {attempt.error_message ? <Typography.Text type="danger" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{attempt.error_message}</Typography.Text> : null}
      </Space> : "—" },
    ]}
    expandable={{ expandedRowRender: (attempt) => <AttemptDetails attempt={attempt} /> }}
  />;
}
