"use client";

import { ArrowRightOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Space, Spin, Tag, Timeline, Typography } from "antd";
import { errorText, getFindingHistory } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export function FindingHistory({ findingId }: { findingId: string }) {
  const { t, label, locale, formatDate } = useI18n();
  const history = useQuery({ queryKey: ["finding-history", findingId], queryFn: () => getFindingHistory(findingId), refetchInterval: 5_000 });
  return <section style={{ marginTop: 28 }} aria-label={t("Finding disposition history", "发现处置历史")}>
    <div className="section-heading"><h2>{t("Disposition history", "处置历史")}</h2><Button size="small" loading={history.isFetching} onClick={() => void history.refetch()}>{t("Refresh history", "刷新历史")}</Button></div>
    {history.error && <Alert type="warning" showIcon message={t("Disposition history could not be refreshed", "处置历史暂时无法刷新")} description={<>{errorText(history.error, locale)} {t("Loaded history and the current disposition draft remain available.", "已加载历史和当前处置草稿仍会保留。")}</>} action={<Button onClick={() => void history.refetch()}>{t("Retry", "重试")}</Button>} style={{ marginBottom: 16 }} />}
    {history.isLoading ? <Spin /> : history.data?.events.length ? <Timeline items={history.data.events.map((event) => ({
      key: event.id,
      children: <div>
        <Space wrap size={[4, 8]}><Typography.Text type="secondary">{formatDate(event.created_at)}</Typography.Text><Tag>{event.actor_type === "USER" ? t("User", "用户") : event.actor_type === "AGENT" ? t("Agent", "智能体") : t("HyperTest", "HyperTest")}</Tag></Space>
        <div style={{ marginBlock: 8 }}><Space wrap>{event.before?.status && <><Tag>{label(event.before.status)}</Tag><ArrowRightOutlined aria-label={t("Changed to", "变更为")} /></>}{event.after?.status ? <Tag>{label(event.after.status)}</Tag> : <Typography.Text type="secondary">{t("State not recorded", "未记录状态")}</Typography.Text>}{event.after?.row_version != null && <Typography.Text type="secondary">{t("Version", "版本")} {event.after.row_version}</Typography.Text>}</Space></div>
        {(event.before?.resolution || event.after?.resolution) && <Typography.Paragraph>{t("Resolution", "解决方式")}: {event.before?.resolution ? label(event.before.resolution) : t("Unresolved", "尚未解决")} <ArrowRightOutlined aria-hidden /> {event.after?.resolution ? label(event.after.resolution) : t("Unresolved", "尚未解决")}</Typography.Paragraph>}
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{event.reason || t("No reason was recorded for this event.", "此事件未记录原因。")}</Typography.Paragraph>
        {event.reason_truncated && <Typography.Paragraph type="secondary">{t("This historical reason is abbreviated in this view.", "此视图中的历史原因已截短。")}</Typography.Paragraph>}
      </div>,
    }))} /> : history.data && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("No disposition history has been recorded.", "尚无已记录的处置历史。")} />}
    {history.data?.truncated && <Typography.Paragraph type="secondary">{t("Showing the latest 50 recorded events. Earlier history remains in the audit records.", "当前显示最近 50 条事件。更早的历史仍保存在审计记录中。")}</Typography.Paragraph>}
  </section>;
}
