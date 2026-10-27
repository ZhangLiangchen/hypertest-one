"use client";
import { CopyOutlined } from "@ant-design/icons";
import { Alert, Button, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { archiveSkillInstruction } from "@/lib/archive";
import { useI18n } from "@/lib/i18n";

export function ArchivePrompt({ projectId, taskId, subtaskId }: { projectId: string; taskId?: string; subtaskId?: string }) {
  const { t, locale } = useI18n();
  const [server, setServer] = useState<string>();
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => { setServer(window.location.origin); }, []);
  useEffect(() => { setCopied("idle"); }, [projectId, taskId, subtaskId, server, locale]);
  let prompt = "";
  try { prompt = archiveSkillInstruction(projectId, taskId, subtaskId, locale === "en", server); } catch { /* Invalid context must never become an upload instruction. */ }
  async function copy() {
    try { await navigator.clipboard.writeText(prompt); setCopied("copied"); }
    catch { setCopied("failed"); setExpanded(true); }
  }
  return <div className="archive-prompt">
    <Typography.Paragraph className="muted">{taskId ? t("Paste this prompt into the Agent conversation that performed the tests. The Agent identifies this task’s artifacts and reuses its existing CLI connection. The destination follows the selection above.", "直接粘贴到执行本次测试的 Agent 会话；Agent 会整理本次产物并复用已有 CLI 连接。归档目标随上方选择更新。") : t("Create the task, then copy the prompt from its detail page with the real Task ID. This preview lets the Agent prepare the artifacts and connection; it must clarify any missing destination before upload.", "建议创建后从任务详情页复制，自动带入真实 Task ID。此处也可复制预览，交给 Agent 整理产物和连接；缺少目标时须先明确再上传。")}</Typography.Paragraph>
    {prompt ? <>
      <Space wrap size={16}><Button type="primary" icon={<CopyOutlined aria-hidden />} onClick={() => void copy()}>{taskId ? t("Copy archive prompt", "复制归档 Prompt") : t("Copy archive template", "复制归档模板")}</Button><span role="status" aria-live="polite" className="muted">{copied === "copied" ? t("Copied. Paste into the Agent conversation that performed the tests.", "已复制，粘贴到执行本次测试的 Agent 会话即可。") : t("Explicit upload only · no background sync", "显式上传 · 无后台同步")}</span></Space>
      {copied === "failed" ? <Alert className="archive-operation-notice" type="warning" showIcon message={t("Clipboard access failed. Select and copy the template below.", "无法写入剪贴板，请选中下方模板手动复制。")} /> : null}
      <details className="cli-install-prompt-details" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>{t("View or manually copy the archive template", "查看或手动复制归档模板")}</summary><textarea className="cli-install-prompt-text" aria-label={t("Archive prompt template", "归档 Prompt 模板")} readOnly value={prompt} rows={16} spellCheck={false} onFocus={(event) => event.currentTarget.select()} /></details>
    </> : <Alert type="warning" showIcon message={t("Cannot prepare the template. Check the destination IDs and open the configured HTTPS address.", "无法生成模板，请核对目标 ID 并通过配置的 HTTPS 地址打开页面。")} />}
  </div>;
}
