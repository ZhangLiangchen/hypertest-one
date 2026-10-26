"use client";

import { Alert, Form, Input, Radio, Space, Typography } from "antd";
import { useId, useMemo, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { buildLocalSetupPrompt, buildLocalUpdateCommand } from "@/lib/local-mode-install";
import type { LocalHarness, LocalUpdateChannel } from "@/lib/local-mode-install";

/** The browser generates public instructions; the local Agent resolves private configuration. */
export function LocalSetupContent({ projectId }: { projectId?: string }) {
  const { t, locale } = useI18n();
  const id = useId();
  const [harness, setHarness] = useState<LocalHarness>("codex");
  const [channel, setChannel] = useState<LocalUpdateChannel>("candidate");
  const [directory, setDirectory] = useState("");
  const [clientConfig, setClientConfig] = useState("");
  const [hostConfig, setHostConfig] = useState("");
  const generated = useMemo(() => {
    try {
      const options = { projectId, harness, channel, locale, directory, clientConfig, hostConfig };
      return { prompt: buildLocalSetupPrompt(options), command: buildLocalUpdateCommand(options) };
    } catch { return null; }
  }, [projectId, harness, channel, locale, directory, clientConfig, hostConfig]);

  return <div>
    <Typography.Paragraph style={{ maxWidth: "75ch" }}>{t("Copy one prompt to your local Agent. It detects an existing installation, downloads a matching verified release, installs or upgrades it, and checks the running client. Existing authorization, Hooks and pending sync records are preserved.", "复制一条 Prompt 给本地 Agent。它会识别已有安装，下载并校验匹配发行，完成安装或升级，再检查实际运行的客户端。已有授权、Hooks 和未决同步记录会保留。")}</Typography.Paragraph>
    <Form layout="vertical">
      <Form.Item label={t("Agent host", "Agent 宿主")}>
        <Radio.Group aria-label={t("Local Agent host", "本地 Agent 宿主")} value={harness} onChange={(event) => setHarness(event.target.value)}>
          <Space wrap><Radio value="codex">Codex</Radio><Radio value="claude-code">Claude Code</Radio><Radio value="deepseek-harness">DeepSeek harness</Radio></Space>
        </Radio.Group>
      </Form.Item>
      <Form.Item label={t("Release channel", "发行通道")} extra={t("The candidate includes Task ID binding and multi-session collaboration. New writes currently require Codex CLI 0.144.6; Claude/DeepSeek retain their existing sync scope.", "候选版包含任务 ID 绑定和多会话协作。新写入目前需要 Codex CLI 0.144.6；Claude/DeepSeek 保持已有同步范围。") }>
        <Radio.Group aria-label={t("Local release channel", "Local 发行通道")} value={channel} onChange={(event) => setChannel(event.target.value)} options={[{ value: "candidate", label: t("Candidate · new capabilities", "候选版 · 新能力") }, { value: "stable", label: t("Stable", "稳定版") }]} />
      </Form.Item>
    </Form>
    <Alert showIcon type={channel === "candidate" ? "info" : "warning"} style={{ marginBottom: 20 }} message={channel === "candidate" ? t("Candidate release; native-host acceptance pending", "候选发行，真实宿主验收待完成") : t("Current stable lacks new binding and collaboration", "当前稳定版尚不含新绑定与协作")}
      description={channel === "candidate" ? t("Installation and runtime checks confirm the local setup. Reload/trust actions required by your host remain explicit; a successful install does not prove task binding or testing.", "安装与运行时检查用于确认本地配置。宿主要求的重载或信任操作会明确列出；安装完成不代表任务已绑定或测试已执行。") : t("The updater requires a published release with update support. Existing stable local-v0.1.0 remains available as history; when no matching update-capable stable target exists, it reports a clear stop instead of selecting a candidate.", "updater 需要通道中已发布且支持更新的目标。原稳定版 local-v0.1.0 保留为历史；没有匹配的可更新稳定目标时会明确停止，不会自行切换候选通道。") } />
    {generated ? <>
      <Typography.Paragraph strong copyable={{ text: generated.prompt }}>{t("Copy install / upgrade prompt", "复制安装 / 升级 Prompt")}</Typography.Paragraph>
      <pre className="artifact-content" aria-label={t("Local install / upgrade prompt", "Local 安装 / 升级 Prompt")} style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{generated.prompt}</pre>
    </> : <Typography.Paragraph role="status" type="warning">{t("Check that optional paths are absolute. If they are empty, the published updater trust anchor must be configured before instructions are available.", "请检查可选路径是否为绝对路径。若路径为空，则需要先配置已发布 updater 的可信摘要，才能提供接入指令。")}</Typography.Paragraph>}
    <Typography.Paragraph className="muted" style={{ maxWidth: "75ch" }}>{t("A fresh installation reuses an existing private task:sync profile for this Project. If the Agent cannot find it, provide its local path only. This page never asks for a token or reads a local file.", "首次安装复用此项目已有的私有 task:sync 配置。Agent 找不到时，只需提供其本地路径。本页不索取 token，也不读取本机文件。")}</Typography.Paragraph>
    <details style={{ marginTop: 20 }}>
      <summary>{t("Optional paths and direct command", "可选路径与直接执行命令")}</summary>
      <Typography.Paragraph style={{ marginTop: 16 }}>{t("Leave paths empty for automatic discovery. Supply a legacy receipt directory only when your existing installation is outside the standard location. Private configuration paths are for a fresh install.", "留空即可自动识别。仅当旧安装不在标准目录时填写原收据目录；私有配置路径用于首次安装。")}</Typography.Paragraph>
      <Form layout="vertical">
        <Form.Item label={t("Existing Local receipt directory (optional)", "原 Local 收据目录（可选）")}><Input id={`${id}-directory`} aria-label={t("Existing Local receipt directory", "原 Local 收据目录")} value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="/absolute/private/hypertest-local/install" autoComplete="off" spellCheck={false} /></Form.Item>
        <Form.Item label={t("Private client configuration path (optional)", "私有客户端配置路径（可选）")}><Input aria-label={t("Private client configuration path", "私有客户端配置路径")} value={clientConfig} onChange={(event) => setClientConfig(event.target.value)} placeholder="/absolute/private/hypertest-local/client.json" autoComplete="off" spellCheck={false} /></Form.Item>
        <Form.Item label={t("Selected host configuration path (optional)", "选定宿主配置路径（可选）")}><Input aria-label={t("Selected host configuration path", "选定宿主配置路径")} value={hostConfig} onChange={(event) => setHostConfig(event.target.value)} placeholder={harness === "codex" ? "/absolute/path/.codex/config.toml" : "/absolute/path/host-config.json"} autoComplete="off" spellCheck={false} /></Form.Item>
      </Form>
      {generated ? <>
        <Typography.Paragraph strong copyable={{ text: generated.command }}>{t("Copy the single updater command", "复制单条更新命令")}</Typography.Paragraph>
        <pre className="artifact-content" aria-label={t("Local updater command", "Local 更新命令")} style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{generated.command}</pre>
        <Typography.Paragraph className="muted">{t("Run with a compatible Python 3 interpreter. Initial installation needs the existing authorized profile; the prompt above helps the Agent resolve its paths and any required Python target.", "使用兼容的 Python 3 解释器执行。首次安装需要已有授权配置；上方 Prompt 会引导 Agent 确认配置路径及所需 Python 目标。")}</Typography.Paragraph>
      </> : null}
    </details>
  </div>;
}

export function SourceClientUpgrade({ projectId }: { projectId?: string }) {
  const { t } = useI18n();
  return <details style={{ marginBlock: 20 }}>
    <summary>{t("Install or upgrade Local with one prompt", "一条 Prompt 安装或升级 Local")}</summary>
    <div style={{ marginTop: 16 }}><LocalSetupContent projectId={projectId} /></div>
  </details>;
}
