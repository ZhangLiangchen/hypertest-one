"use client";

import { Alert, Form, Input, Radio, Typography } from "antd";
import { useMemo, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { TASK_BINDING_CLIENT_SOURCE_COMMIT, taskBindingClientCommands } from "@/lib/task-binding-client";

function Command({ title, command }: { title: string; command: string }) {
  return <div style={{ marginBlock: 16 }}><Typography.Paragraph strong copyable={{ text: command }}>{title}</Typography.Paragraph><pre className="artifact-content" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{command}</pre></div>;
}

export function SourceClientUpgrade() {
  const { t } = useI18n();
  const [sourceCommit, setSourceCommit] = useState(TASK_BINDING_CLIENT_SOURCE_COMMIT);
  const [venvDirectory, setVenvDirectory] = useState("");
  const [installDirectory, setInstallDirectory] = useState("");
  const [clientConfig, setClientConfig] = useState("");
  const commands = useMemo(() => {
    try { return taskBindingClientCommands({ sourceCommit, venvDirectory, installDirectory, clientConfig, harness: "codex" }); }
    catch { return null; }
  }, [sourceCommit, venvDirectory, installDirectory, clientConfig]);
  return <details style={{ marginBlock: 20 }}>
    <summary>{t("Upgrade this Project's existing Local client", "升级此项目已有的 Local 客户端")}</summary>
    <Typography.Paragraph style={{ marginTop: 16 }}>{t("Use the full pushed source commit supplied with this deployment. The commands create a separate private Python 3.13 environment and upgrade only the installation you explicitly select. They reuse its owned host, Hooks and artifact-policy settings; the browser neither reads your files nor runs these commands.", "使用本次部署提供的、已推送的完整源码提交 SHA。以下命令创建独立私有 Python 3.13 环境，只升级明确选择的原安装；复用其已有宿主、Hooks 和产物策略配置。浏览器不读取这些文件，也不执行命令。")}</Typography.Paragraph>
    <Form layout="vertical">
      <Form.Item label={t("Matching source commit (full 40-character SHA)", "匹配此次部署的源码提交（完整40位 SHA）")} extra={t("The matching commit is prefilled. Keep it unless the deployment provides a newer full commit.", "已填入匹配的提交；仅在部署提供更新的完整提交时更换。") }><Input aria-label={t("Matching source commit", "匹配源码提交")} value={sourceCommit} onChange={(event) => setSourceCommit(event.target.value.trim().toLowerCase())} maxLength={40} autoComplete="off" spellCheck={false} /></Form.Item>
      <Form.Item label={t("Host for new Task ID binding", "新任务 ID 绑定宿主")} extra={t("New binding supports Codex CLI 0.144.6 only. Existing Claude Code and DeepSeek task sync remains compatible.", "新绑定仅支持 Codex CLI 0.144.6，Claude Code 和 DeepSeek 的已有任务同步不受影响。") }><Radio.Group aria-label={t("Upgrade Agent host", "升级的 Agent 宿主")} value="codex" options={[{ value: "codex", label: "Codex CLI 0.144.6" }, { value: "claude-code", label: t("Claude Code: new binding unsupported", "Claude Code：暂不支持新绑定"), disabled: true }, { value: "deepseek-harness", label: t("DeepSeek: new binding unsupported", "DeepSeek：暂不支持新绑定"), disabled: true }]} /></Form.Item>
      <Form.Item label={t("New private virtual environment directory", "新的私有虚拟环境目录")}><Input aria-label={t("New private virtual environment directory", "新的私有虚拟环境目录")} value={venvDirectory} onChange={(event) => setVenvDirectory(event.target.value)} placeholder="/absolute/private/hypertest-binding-client" autoComplete="off" spellCheck={false} /></Form.Item>
      <Form.Item label={t("Existing Local installation record directory", "原 Local 安装记录目录")}><Input aria-label={t("Existing Local installation record directory", "原 Local 安装记录目录")} value={installDirectory} onChange={(event) => setInstallDirectory(event.target.value)} placeholder="/absolute/private/hypertest-local/install" autoComplete="off" spellCheck={false} /></Form.Item>
      <Form.Item label={t("Existing private client configuration path", "原私有客户端配置路径")} extra={t("Enter the path only. Do not paste its content or token.", "仅填写路径，不粘贴配置内容或 token。") }><Input aria-label={t("Existing private client configuration path", "原私有客户端配置路径")} value={clientConfig} onChange={(event) => setClientConfig(event.target.value)} placeholder="/absolute/private/hypertest-local/config.json" autoComplete="off" spellCheck={false} /></Form.Item>
    </Form>
    {commands ? <>
      <Command title={t("Create the private source-client environment", "准备私有源码客户端环境")} command={commands.prepare} />
      <Alert showIcon type="info" message={t("Settle pending work before stopping the daemon", "停止 daemon 前先处理未决请求")} description={t("Keep original keys, journals, native sessions and snapshots. Finish or reconcile pending writes before continuing; an UNKNOWN request must not be deleted or replayed.", "保留原 key、账本、原生会话及快照。继续前先完成写入或按原 key 对账；不能删除或重放 UNKNOWN 请求。") } />
      <Command title={t("Stop only this profile's current daemon", "仅停止此配置对应的当前 daemon")} command={commands.stop} />
      <Command title={t("Upgrade the selected owned installation", "升级所选的已有安装")} command={commands.upgrade} />
      <Command title={t("Check this daemon's local binding configuration", "检查此 daemon 的本地绑定配置")} command={commands.capabilities} />
      <Typography.Paragraph>{t("After the check passes, reload this Project's MCP configuration and start a new primary session in Codex CLI 0.144.6. Use MCP in that Agent to bind the task. CONFIGURATION_SUPPORTED confirms configuration only; it does not mean binding succeeded.", "检查通过后，重载此项目 MCP 配置，并在 Codex CLI 0.144.6 中新建主会话，再由 Agent 调用 MCP 绑定。CONFIGURATION_SUPPORTED 只表示配置支持，不代表绑定成功。")}</Typography.Paragraph>
    </> : <Typography.Paragraph className="muted" role="status">{t("Provide the matching full commit and private absolute paths to generate the pinned commands. An existing owned installation is required; no credential or authorization is created here.", "填写匹配的完整提交及私有绝对路径后生成固定源码命令。此升级需要已有的原安装记录；这里不会创建凭据或授权。")}</Typography.Paragraph>}
  </details>;
}
