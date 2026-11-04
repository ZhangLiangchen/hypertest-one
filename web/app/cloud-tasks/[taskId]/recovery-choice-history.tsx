"use client";

import { Typography } from "antd";
import type { CloudRecoveryChoice } from "@/lib/cloud";
import { useI18n } from "@/lib/i18n";

/** An immutable historical decision records intent at its own acceptance time. */
export function RecoveryChoiceHistory({ attemptId, choices }: {
  attemptId: string; choices?: CloudRecoveryChoice[];
}) {
  const { t, formatDate } = useI18n();
  const entries = (choices || []).filter((choice) => choice.attempt_id === attemptId);
  if (!entries.length) return null;
  const labels: Record<CloudRecoveryChoice["choice"], string> = {
    CONTINUE_ORIGINAL_SESSION: t("Continue the original session", "继续原会话"),
    RETEST: t("Run a new test", "重新测试"),
    END_EXECUTION: t("End this execution", "结束本次执行"),
  };
  return <section aria-label={t("Recorded recovery decisions", "已记录的恢复选择")}>
    <Typography.Title level={4}>{t("Recorded recovery decisions", "已记录的恢复选择")}</Typography.Title>
    {entries.map((entry) => <div key={entry.operation_key} style={{ marginBottom: 16 }}>
      <strong>{labels[entry.choice] || entry.choice}</strong> · {formatDate(entry.recorded_at)} · {entry.actor_ref}
      {entry.note ? <Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 4 }}>{entry.note}</Typography.Paragraph> : null}
      <Typography.Text type="secondary">{entry.identity_anchor === "MISSING"
        ? t("The earlier session identity was not recorded.", "缺少早期会话身份记录。")
        : entry.identity_anchor === "RECORDED"
          ? t("An earlier session identity record exists; it does not by itself verify the session.", "已有早期会话身份记录，但这本身不能核实会话身份。")
          : t("Earlier session identity status is unknown.", "早期会话身份记录情况未知。")}</Typography.Text>
      <div><Typography.Text type="secondary">{t("The selected action had not started when this choice was recorded.", "记录选择时，所选操作尚未开始。")}</Typography.Text></div>
    </div>)}
  </section>;
}
