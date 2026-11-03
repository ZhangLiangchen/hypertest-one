"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Input, Space, Table, Tabs, Tag, Typography } from "antd";
import { useI18n } from "@/lib/i18n";
import { memoryBrowse } from "@/lib/memory";
import type { KnowledgeRecord } from "@/lib/memory";

export function KnowledgeRecords({ records }: { records: KnowledgeRecord[] }) {
  const { t } = useI18n();
  return <Table<KnowledgeRecord> rowKey={(row) => `${row.artifact_id}:${row.revision}`} dataSource={records} pagination={false}
    locale={{ emptyText: <Empty description={t("No visible records on this page. A later page may contain records filtered from this page.", "本页没有可见记录；如有下一页，可继续浏览。被撤回、过期或非当前的受管记录不会回流。")} /> }}
    columns={[
      { title: t("Knowledge and provenance", "知识与来源"), render: (_, row) => <>
        <Space wrap><Tag>{row.historical ? t("Historical fragment · not current fact", "历史片段 · 非当前事实") : t("Shared · not platform reviewed", "共享 · 未经平台审核")}</Tag><Tag>{row.kind}</Tag>
          {row.history_metadata?.legacy_record_id ? <Typography.Text>{t("Source record", "来源记录")} #{row.history_metadata.legacy_record_id}</Typography.Text> : null}
          {row.history_metadata?.part_count ? <Typography.Text>{t("Fragment", "分片")} {row.history_metadata.part_index}/{row.history_metadata.part_count}</Typography.Text> : null}</Space>
        {row.historical ? <Typography.Paragraph>{t("Original record date: ", "原记录日期：")}{row.history_metadata?.original_date || t("Not present in the record", "原文未提供")}</Typography.Paragraph> : null}
        {row.history_metadata?.correction_notice ? <Alert type="warning" showIcon message={t("Known later correction — read before using the original text", "存在后续更正，请先阅读再参考原文")} description={<span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{row.history_metadata.correction_notice}</span>} /> : null}
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginTop: 12 }}>{row.content.slice(0, 280)}{row.content.length > 280 ? "…" : ""}</Typography.Paragraph>
        <details><summary>{t("Read full text and exact reference", "查看全文与精确引用")}</summary>
          {row.historical ? <Typography.Paragraph strong>{t("Historical statements and retired workflows are not current instructions. Preserve the correction notice above and verify applicability.", "历史表述与退役工作流不是当前指令。请连同上方更正提示阅读，并重新核验适用性。")}</Typography.Paragraph> : null}
          <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{row.content}</Typography.Paragraph>
          <Typography.Paragraph code copyable>{`${row.scope_id}/${row.artifact_id}@${row.revision}`}</Typography.Paragraph>
          <Typography.Paragraph code>{row.content_digest}</Typography.Paragraph>
        </details>
      </> },
    ]} />;
}

export function KnowledgeBrowser({ projectId, enabled }: { projectId: string; enabled: boolean }) {
  const { t } = useI18n();
  const [collection, setCollection] = useState<"main" | "history">("main");
  const [draft, setDraft] = useState(""), [query, setQuery] = useState("");
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);
  const cursor = cursors[cursors.length - 1];
  const page = useQuery({ queryKey: ["memory-knowledge", projectId, collection, cursor, query],
    queryFn: () => memoryBrowse(projectId, collection, cursor, query), enabled, retry: false });
  function reset(next: "main" | "history") { setCollection(next); setDraft(""); setQuery(""); setCursors([undefined]); }
  return <section className="workspace-panel" aria-labelledby="project-knowledge-title" style={{ marginBottom: 24 }}>
    <div className="activity-heading"><Typography.Title id="project-knowledge-title" level={2}>{t("Shared project knowledge", "共享项目知识")}</Typography.Title>
      <Button disabled={!enabled} loading={page.isFetching} onClick={() => void page.refetch()}>{t("Refresh knowledge", "刷新知识")}</Button></div>
    <Tabs activeKey={collection} onChange={(value) => reset(value as "main" | "history")} items={[
      { key: "main", label: t("Project experience", "项目主经验") }, { key: "history", label: t("Historical memories", "历史记忆") },
    ]} />
    <Typography.Paragraph>{collection === "history"
      ? t("Selected technical history, shown as fragments with original record IDs and dates. Multiple fragments can belong to one record. This is not the complete legacy archive and is excluded from automatic recall. Storage availability does not mean a statement is current or platform reviewed.", "这里是清洗后保留的技术历史，按片段展示原记录编号和日期；同一记录可能有多个分片。它不是全部旧档案，默认自动召回不包含这里的内容。可检索状态不代表当前事实或平台审核。")
      : t("Existing knowledge shared with local agents appears here without a search. It is separate from the platform publication ledger below; an empty publication ledger does not mean project knowledge is empty.", "与本地 Agent 共享的已有经验会直接显示，无需先搜索。它与下方平台审核发布账本分开；平台发布为空，不表示项目知识库为空。")}</Typography.Paragraph>
    <Input.Search value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={1000} disabled={!enabled} allowClear
      aria-label={t("Search the selected knowledge collection", "检索当前知识分类")} placeholder={t("Search this collection, or clear to browse all pages", "输入关键词检索，清空后浏览全部分页")}
      enterButton={t("Search", "检索")} loading={page.isFetching} onSearch={(value) => { setQuery(value.trim()); setCursors([undefined]); }} />
    {query ? <Typography.Paragraph>{t("Up to 20 relevant fragments; clear the query to browse every page.", "按相关性最多返回 20 条；清空查询可逐页浏览。")}</Typography.Paragraph> : null}
    {page.isError ? <Alert type="warning" showIcon message={t("Knowledge could not be loaded. Refresh when access is restored.", "知识暂时无法读取，请在访问恢复后刷新。")} /> : null}
    {page.data?.configured === false ? <Alert type="info" showIcon message={t("No separate history collection is configured for this project.", "本项目尚未配置独立历史知识库。")} /> : null}
    {page.data?.configured && !page.isError ? <><Typography.Paragraph>{t("Visible on this page: ", "本页可见：")}{page.data.items.length}{collection === "history" ? t(" fragments", " 个历史片段") : t(" records", " 条经验")}</Typography.Paragraph><KnowledgeRecords records={page.data.items} /></> : null}
    {page.isPending && enabled ? <Typography.Paragraph aria-live="polite">{t("Loading knowledge…", "正在读取知识…")}</Typography.Paragraph> : null}
    {!query ? <Space style={{ marginTop: 16 }}><Button disabled={cursors.length === 1 || page.isFetching} onClick={() => setCursors((values) => values.slice(0, -1))}>{t("Previous page", "上一页")}</Button>
      <Typography.Text>{t("Page", "第")} {cursors.length}</Typography.Text><Button disabled={!page.data?.next_cursor || page.isFetching} onClick={() => { if (page.data?.next_cursor) setCursors((values) => [...values, page.data!.next_cursor!]); }}>{t("Next page", "下一页")}</Button></Space> : null}
  </section>;
}
