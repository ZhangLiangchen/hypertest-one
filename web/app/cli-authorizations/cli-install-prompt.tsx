"use client";
import { CopyOutlined } from "@ant-design/icons";
import { Alert, Button, Space, Typography } from "antd";
import { useEffect, useId, useState } from "react";
import { cliInstallPrompt, cliServerOrigin } from "@/lib/cli-install-prompt";
import { copyText } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n";

/** `server` is the deployment-configured CLI HTTPS origin; a plain-HTTP site cannot supply it. */
export function CliInstallPrompt({ projectId, server, caCertificate }: { projectId?: string; server?: string; caCertificate?: string }) {
  const { t, locale } = useI18n(); const id = useId();
  const [site, setSite] = useState<string>();
  const [expanded, setExpanded] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => { setSite(window.location.origin); }, []);
  useEffect(() => { setCopyState("idle"); }, [server, site, projectId, caCertificate, locale]);
  const target = cliServerOrigin(server, site);
  let prompt: string | null = null, invalid = false;
  try { prompt = cliInstallPrompt({ locale, server: target, projectId, caCertificate }); } catch { invalid = true; }
  async function copy() {
    if (!prompt) return;
    try { await copyText(prompt); setCopyState("copied"); }
    catch { setCopyState("failed"); setExpanded(true); }
  }
  return <div className="cli-install-prompt">
    <Typography.Paragraph>{t("Copy this prompt to your local Agent to install or upgrade the CLI and archive Skill. Existing authorized profiles are reused without pairing again; new clients require approval here.", "将 Prompt 复制给本地 Agent，安装或升级 CLI 与归档 Skill。已有获准 profile 直接复用，无需重新配对；新客户端在此核对短码并批准。")}</Typography.Paragraph>
    {invalid ? <Alert type="warning" showIcon message={t("Installation prompt could not be prepared", "无法生成安装 Prompt")} description={t("The current page context is invalid. Refresh and try again, or open the page from the configured HyperTest One address.", "当前页面上下文无效。请刷新后重试，或通过配置的 HyperTest One 地址打开页面。")} /> : !prompt ? <Alert type="info" showIcon message={t("The CLI installation prompt is not available yet", "CLI 安装 Prompt 暂未提供")} description={t("A published CLI release is required. Contact the deployment operator.", "需要已发布的 CLI 版本，请联系部署管理员。")} /> : <>
      <Space className="cli-install-prompt-actions" size={16} wrap>
        <Button type="primary" icon={<CopyOutlined aria-hidden />} onClick={() => void copy()}>{t("Copy install / upgrade prompt", "复制安装 / 升级 Prompt")}</Button>
        <span role="status" aria-live="polite" className="muted">{copyState === "copied" ? t("Copied. Paste it into your local Agent conversation.", "已复制，请粘贴到本地 Agent 会话。") : t("Install once · available across projects and sessions", "安装一次 · 跨项目与会话使用")}</span>
      </Space>
      {copyState === "failed" ? <Alert type="warning" showIcon className="archive-operation-notice" message={t("Clipboard access failed", "无法写入剪贴板")} description={t("Select the prompt below and copy it manually.", "请选中下方 Prompt，手动复制。")} /> : null}
      <details className="cli-install-prompt-details" open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>{t("Read or manually copy the prompt", "查看或手动复制 Prompt")}</summary>
        <textarea id={`${id}-prompt`} aria-label={t("CLI installation prompt", "CLI 安装 Prompt")} className="cli-install-prompt-text" readOnly value={prompt} rows={14} spellCheck={false} onFocus={(event) => event.currentTarget.select()} />
      </details>
    </>}
  </div>;
}
