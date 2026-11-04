"use client";

import { Alert, Button, Form, Input, Select, Space, Typography } from "antd";
import { useState } from "react";
import type { CloudAttempt, CloudDocument, CloudRecord, CloudRecoveryChoice, CloudRecoverySummary } from "@/lib/cloud";
import { useI18n } from "@/lib/i18n";

type Choice = CloudRecoveryChoice["choice"];

/** Recording a choice is not execution; the existing safety gates still apply. */
export function RecoveryChoice({ attempt, document, recovery, blocked, onSubmit }: {
  attempt: CloudAttempt; document: CloudDocument; recovery?: CloudRecoverySummary;
  blocked: boolean; onSubmit: (fields: CloudRecord) => Promise<void>;
}) {
  const { t, formatDate } = useI18n();
  const [choice, setChoice] = useState<Choice | undefined>();
  const [note, setNote] = useState("");
  const runs = document.runs.filter((row) => row.attempt_id === attempt.id);
  const assets = document.assets.filter((row) => row.attempt_id === attempt.id);
  const attachments = document.artifacts.filter((row) => row.attempt_id === attempt.id);
  const choices = (document.recovery_choices || []).filter((row) => row.attempt_id === attempt.id);
  const labels: Record<Choice, string> = {
    CONTINUE_ORIGINAL_SESSION: t("Continue the original session", "继续原会话"),
    RETEST: t("Run a new test", "重新测试"),
    END_EXECUTION: t("End this execution", "结束本次执行"),
  };
  const canSave = !blocked && !!choice;
  async function save() {
    if (!canSave || !choice) return;
    await onSubmit({ operation: "RECORD_RECOVERY_CHOICE", attempt_id: attempt.id, choice, note: note.trim() });
  }
  return <section className="cloud-recovery-choice" aria-labelledby={`recovery-choice-${attempt.id}`}>
    <Typography.Title level={3} id={`recovery-choice-${attempt.id}`}>{t("Decide what happens next", "决定接下来怎么做")}</Typography.Title>
    <DescriptionsForRecovery runs={runs} cases={document.run_cases} assetCount={assets.length} attachmentCount={attachments.length} attempt={attempt} recovery={recovery} />
    {recovery?.identity_anchor === "MISSING" ? <Alert showIcon type="info" style={{ marginTop: 16 }}
      message={t("Earlier session identity was not recorded", "缺少早期会话身份记录")}
      description={t("Your decision will be recorded separately. It cannot recreate a historical identity record.", "你的选择会单独留痕，但不能补造过去的身份记录。")}/> : null}
    <Alert showIcon type="warning" style={{ margin: "16px 0" }}
      message={t("Review the unconfirmed work", "请先核对尚未确认的事项")}
      description={t("An interrupted session may have made external changes that were not recorded here. A missing record does not prove that an action did not happen. Known pending requests must be checked using their original references.", "中断的会话可能做过未登记的外部操作。没有记录不代表操作没有发生；已知未确认的请求需按原有记录核对。")}/>
    {choices.length ? <div aria-label={t("Recorded decisions", "已记录的选择")}>
      <Typography.Title level={4}>{t("Recorded decisions", "已记录的选择")}</Typography.Title>
      {choices.map((row) => <div key={row.operation_key} style={{ marginBottom: 16 }}>
        <strong>{labels[row.choice] || row.choice}</strong> · {formatDate(row.recorded_at)} · {row.actor_ref}
        {row.note ? <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 4 }}>{row.note}</Typography.Paragraph> : null}
        <Typography.Text type="secondary">{row.identity_anchor === "MISSING"
          ? t("The earlier session identity was not recorded. This decision is recorded separately.", "缺少早期会话身份记录，本次人工选择已单独留痕。")
          : t("An earlier session identity record exists; it does not by itself prove that continuation is safe.", "已有早期会话身份记录，但仍需核对是否可以安全续写。")}</Typography.Text>
        <div><Typography.Text type="secondary">{t("The action had not started when this choice was recorded.", "记录选择时，所选操作尚未开始。")}</Typography.Text></div>
      </div>)}
    </div> : null}
    <Form className="cloud-task-fields" layout="vertical" onFinish={() => void save()}>
      <Form.Item label={t("Your instructions or observations (optional)", "补充说明或观察（选填）")}>
        <Input.TextArea aria-label={t("Your instructions or observations", "补充说明或观察")} rows={3} maxLength={4096} value={note} onChange={(event) => setNote(event.target.value)} />
      </Form.Item>
      <Form.Item label={t("Choose the next step", "选择下一步")} required>
        <Select aria-label={t("Choose the next step", "选择下一步")} value={choice} onChange={setChoice} options={(Object.keys(labels) as Choice[]).map((value) => ({ value, label: labels[value] }))} />
      </Form.Item>
      <Space direction="vertical" size="small">
        <Typography.Text type="secondary">{t("Saving records your choice and instructions. It does not resume the session, start a new test, or end this execution. The chosen action still needs its own safety checks.", "保存只记录你的选择和说明，不会立即续写会话、重新测试或结束执行；实际操作仍需通过各自的安全检查。")}</Typography.Text>
        <Button htmlType="submit" type="primary" disabled={!canSave}>{t("Save choice", "保存选择")}</Button>
      </Space>
    </Form>
  </section>;
}

function DescriptionsForRecovery({ runs, cases, assetCount, attachmentCount, attempt, recovery }: {
  runs: CloudRecord[]; cases: CloudRecord[]; assetCount: number; attachmentCount: number; attempt: CloudAttempt; recovery?: CloudRecoverySummary;
}) {
  const { t } = useI18n();
  return <div>
    <Typography.Paragraph><strong>{t("Work already recorded", "已记录的工作")}：</strong>{t(`${runs.length} test execution(s), ${assetCount} accepted artifact revision(s), ${attachmentCount} attachment(s).`, `已有 ${runs.length} 次测试执行、${assetCount} 条已接受产物修订、${attachmentCount} 个附件。`)}</Typography.Paragraph>
    {runs.map((run) => {
      const recorded = cases.filter((item) => item.run_id === run.id);
      return <Typography.Paragraph key={String(run.id)}>{t("Execution result", "测试执行结果")}：{String(run.reported_result || t("Unknown", "未知"))}
        {recorded.length ? ` · ${t("Recorded cases", "已记录用例")} ${recorded.length} · ${t("Passed", "通过")} ${recorded.filter((item) => item.reported_result === "PASS").length} · ${t("Failed", "失败")} ${recorded.filter((item) => item.reported_result === "FAIL").length}` : ""}</Typography.Paragraph>;
    })}
    <Typography.Paragraph><strong>{t("Interruption reason", "中断原因")}：</strong>{attempt.reason === "WORKER_RUNTIME_FAILED" ? t("The worker stopped unexpectedly.", "执行程序异常中断。") : attempt.reason || t("Not recorded", "未记录")}</Typography.Paragraph>
    {recovery?.pending_operation_keys?.length ? <Typography.Paragraph>{t("Known requests awaiting confirmation", "已知待确认请求")}：{recovery.pending_operation_keys.join(", ")}</Typography.Paragraph> : null}
  </div>;
}
