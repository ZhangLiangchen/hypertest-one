"use client";

import { CopyOutlined, DownloadOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input, Radio, Space, Typography } from "antd";
import type { TextAreaRef } from "antd/es/input/TextArea";
import { useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { buildMcpInstallPrompt, MCP_RELEASE_MANIFEST, MCP_RELEASE_VERSION } from "@/lib/mcp-install";

export function McpInstallGuide({ projectId }: { projectId: string }) {
  const { t, locale } = useI18n();
  const [apiUrl, setApiUrl] = useState("");
  const [host, setHost] = useState<"generic" | "codex-desktop">("generic");
  const [copied, setCopied] = useState(false);
  const [copyFallback, setCopyFallback] = useState(false);
  const [preview, setPreview] = useState(false);
  const promptRef = useRef<TextAreaRef>(null);
  useEffect(() => { setApiUrl(`${window.location.origin}/api/v1`); }, []);
  const prompt = useMemo(() => {
    try { return buildMcpInstallPrompt({ apiUrl, projectId, host, locale }); } catch { return ""; }
  }, [apiUrl, projectId, host, locale]);
  useEffect(() => { setCopied(false); setCopyFallback(false); }, [prompt]);

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setCopyFallback(false);
    } catch {
      setPreview(true);
      setCopyFallback(true);
      requestAnimationFrame(() => { promptRef.current?.focus(); promptRef.current?.resizableTextArea?.textArea.select(); });
    }
  }

  return <section aria-label={t("Install MCP for your Agent", "为当前 Agent 安装 MCP")} style={{ marginBottom: 24 }}>
    <Typography.Title level={5} style={{ marginTop: 0 }}>{t("Use HyperTest from your Agent", "在当前 Agent 中使用 HyperTest")}</Typography.Title>
    <Typography.Paragraph className="muted">{t("Copy one installation prompt to your Agent. Pair this computer, then submit and follow tests through MCP in that Agent.", "将安装 Prompt 复制给当前 Agent，配对这台电脑后，即可在 Agent 中通过 MCP 提交任务、查看进度、证据和报告。")}</Typography.Paragraph>
    <ol style={{ paddingInlineStart: 22, lineHeight: 1.8, marginBottom: 0 }}>
      <li style={{ paddingInlineStart: 4, marginBottom: 18 }}>
        <Typography.Text strong>{t("Copy the installation prompt", "复制安装 Prompt")}</Typography.Text>
        <Form.Item label={t("Agent host", "Agent 宿主")} style={{ marginTop: 8, marginBottom: 8 }}>
          <Radio.Group aria-label={t("Agent host", "Agent 宿主")} value={host} onChange={(event) => setHost(event.target.value)} options={[
            { value: "generic", label: t("Other stdio Agents", "通用 stdio Agent") },
            { value: "codex-desktop", label: "Codex Desktop" },
          ]} />
        </Form.Item>
        <Typography.Paragraph className="muted" style={{ marginBottom: 10 }}>{t("macOS/Linux: generic Agents can submit, read, and request CLOUD execution. LOCAL execution in the current Agent requires the controlled Codex Desktop adapter. Windows is not supported in this release.", "首版支持 macOS/Linux：通用 Agent 可提交、读取和请求 CLOUD 执行；当前 Agent 的 LOCAL 执行需要受控 Codex Desktop 适配器。首版不支持 Windows。")}</Typography.Paragraph>
        <Space wrap>
          <Button type="primary" icon={<CopyOutlined />} disabled={!prompt} onClick={() => void copyPrompt()}>{copied ? t("Prompt copied", "已复制 Prompt") : t("Copy installation prompt", "复制安装 Prompt")}</Button>
          <Button type="link" onClick={() => setPreview((value) => !value)} aria-expanded={preview} aria-controls="mcp-install-prompt">{preview ? t("Hide prompt", "收起 Prompt") : t("Review prompt and address", "查看 Prompt 和平台地址")}</Button>
          <Typography.Link href={MCP_RELEASE_MANIFEST} target="_blank" rel="noopener noreferrer"><DownloadOutlined /> {MCP_RELEASE_VERSION}</Typography.Link>
        </Space>
        {preview && <div style={{ marginTop: 12 }}>
          <Form.Item label={t("Platform API URL", "平台 API 地址")} validateStatus={apiUrl && !prompt ? "error" : undefined} help={apiUrl && !prompt ? t("Use a complete HTTPS API address ending in /api/v1, without credentials, query, or fragment.", "请填写以 /api/v1 结尾的完整 HTTPS API 地址，不含凭据、查询参数或片段。") : t("Taken from this page. Correct it only if your deployment uses another public API address.", "默认使用当前页面地址；仅当部署使用另一个对外 API 地址时修改。") }>
            <Input aria-label={t("Platform API URL", "平台 API 地址")} value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} autoComplete="off" />
          </Form.Item>
          <Input.TextArea id="mcp-install-prompt" ref={promptRef} value={prompt} readOnly rows={8} aria-label={t("Installation prompt without credentials", "不含凭据的安装 Prompt")} style={{ fontSize: 13, lineHeight: 1.8 }} />
        </div>}
        {!prompt && apiUrl && !preview && <Typography.Paragraph type="danger" role="status" style={{ marginTop: 8 }}>{t("Check the HTTPS platform address before copying.", "复制前请展开并核对 HTTPS 平台地址。")}</Typography.Paragraph>}
        <div role="status" aria-live="polite">
          {copied && <Typography.Paragraph className="muted" style={{ marginTop: 8 }}>{t("Paste it into your Agent. It contains the platform address and project ID, with no credentials.", "请粘贴到当前 Agent；内容仅包含平台地址、项目 ID 和安装说明，不包含凭据。")}</Typography.Paragraph>}
          {copyFallback && <Alert type="info" showIcon style={{ marginTop: 10 }} message={t("Automatic copy is unavailable", "无法自动复制")} description={t("The prompt is selected below. Use your system Copy command, then paste it into your Agent.", "已展开并选中下方 Prompt，请使用系统复制命令后粘贴到 Agent。") } />}
        </div>
        <Typography.Paragraph className="muted" style={{ marginTop: 10, marginBottom: 0 }}>{t("Install only this fixed release after verifying its SHA-256. If the release link is unavailable, ask the deployment administrator to publish it; do not substitute main, latest, or an unverified download.", "仅安装此固定发行并校验 SHA-256。若发行链接不可用，请联系部署管理员发布，不要改用 main、latest 或未校验下载。")}</Typography.Paragraph>
      </li>
      <li style={{ paddingInlineStart: 4, marginBottom: 18 }}>
        <Typography.Text strong>{t("Get the device management key privately", "通过私密方式获取设备管理密钥")}</Typography.Text>
        <Typography.Paragraph style={{ marginTop: 6, marginBottom: 0 }}>{t("Ask the deployment administrator to provide the key from protected platform.env to a local file with permission 0600, or enter it directly at the standalone setup CLI's hidden terminal prompt. Ordinary users cannot download this key from the platform. It is not your Git, glab, or model API key. Never paste its value into Agent chat or the installation prompt.", "请由部署管理员将受保护 platform.env 中的密钥交付到本机权限 0600 的文件，或由您直接在独立 setup CLI 的隐藏终端提示中输入。普通用户无法从平台下载此密钥；它不是 Git、glab 或模型 API 密钥。不要将密钥值粘贴到 Agent 聊天或安装 Prompt。")}</Typography.Paragraph>
      </li>
      <li style={{ paddingInlineStart: 4 }}>
        <Typography.Text strong>{t("Pair, reload, and check the connection", "配对设备，重新加载并检查连接")}</Typography.Text>
        <Typography.Paragraph style={{ marginTop: 6, marginBottom: 0 }}>{t("The setup CLI pairs a new device, grants this project MCP access, and writes private configuration. Your Agent merges the generated stdio configuration without replacing other MCP servers. Run doctor, then reload or restart the Agent and query this project. A private CA uses a CA file; keep TLS verification enabled.", "setup CLI 会配对新设备、授予此项目 MCP 权限并写入私有配置；Agent 会将生成的 stdio 配置合并到现有 MCP 服务中。运行 doctor 后，重新加载或重启 Agent，再查询此项目确认连接。私有 CA 通过 CA 文件提供，始终保持 TLS 校验。")}</Typography.Paragraph>
      </li>
    </ol>
    <Alert type="info" showIcon style={{ marginTop: 18 }} message={t("Create MCP runs in your Agent", "MCP 运行由当前 Agent 发起")} description={t("Installing MCP does not change this form. This web form creates a managed Harness run; use the separate Connector controls below to continue here. After MCP installation, ask your Agent to create its own run through MCP.", "安装 MCP 不会改变此表单：网页创建的是受管 Harness 运行，继续使用此表单请配置下方 Connector。MCP 安装完成后，请在当前 Agent 中通过 MCP 发起独立运行。") } />
  </section>;
}
