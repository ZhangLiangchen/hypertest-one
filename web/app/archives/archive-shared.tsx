"use client";
import { Alert, Button, Typography } from "antd";
import { errorText } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { LocalWebPending } from "@/lib/archive-operation";
export function ArchiveOperationNotice({ operation, onAccepted }: { operation: { pending: LocalWebPending | null; ready: boolean; busy: boolean; error: unknown; reconcile: () => Promise<unknown> }; onAccepted?: (value: unknown) => void }) {
  const { t, locale } = useI18n();
  if (operation.pending) return <Alert className="archive-operation-notice" type="warning" showIcon message={t("Result pending — query the original request", "结果未决，请查询原请求")} description={<><Typography.Paragraph>{t("This browser retains the original request. Querying will not submit it again. Keep site data until reconciliation completes.", "本浏览器保留原请求。查询不会重新提交，请在确认结果前保留网站数据。")}</Typography.Paragraph><Typography.Text code copyable>{operation.pending.operation_key}</Typography.Text>{operation.error ? <Typography.Paragraph type="danger">{errorText(operation.error, locale)}</Typography.Paragraph> : null}</>} action={<Button loading={operation.busy} onClick={() => void operation.reconcile().then((value) => { if (value) onAccepted?.(value); })}>{t("Query original request", "查询原请求")}</Button>} />;
  if (operation.error) return <Alert className="archive-operation-notice" type="error" showIcon message={t("Operation could not be confirmed", "操作未能确认")} description={errorText(operation.error, locale)} />;
  return null;
}
