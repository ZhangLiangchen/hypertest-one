"use client";
import { LaptopOutlined } from "@ant-design/icons";
import { Button, Typography } from "antd";
import Link from "next/link";
import { useId, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { CliInstallPrompt } from "@/app/cli-authorizations/cli-install-prompt";
export function LocalModeGuide({ projectId, initiallyOpen = false }: { projectId: string; initiallyOpen?: boolean }) {
  const { t } = useI18n(); const id = useId(); const [open, setOpen] = useState(initiallyOpen);
  return <div style={{ marginBlock: 16 }}><Button icon={<LaptopOutlined aria-hidden />} aria-expanded={open} aria-controls={`${id}-guide`} onClick={() => setOpen(!open)}>{t("CLI installation prompt & archive guide", "CLI 安装 Prompt 与归档指引")}</Button>
    {open ? <section id={`${id}-guide`} className="data-surface" style={{ marginTop: 12, padding: 24 }} aria-labelledby={`${id}-heading`}>
      <Typography.Title id={`${id}-heading`} level={3}>{t("Archive after local testing", "本地测试结束后归档")}</Typography.Title>
      <CliInstallPrompt projectId={projectId} />
      <ol className="archive-guide-steps"><li><Link href={`/cli-authorizations?projectId=${projectId}#cli-install`}>{t("Install and authorize the CLI once", "安装 CLI 并完成一次授权")}</Link>{t(" for all projects.", "，默认允许全部项目。")}</li><li>{t("Create a task and optional subtasks, then copy its archive instruction.", "创建任务与可选子任务，复制任务中的归档指令。")}</li><li>{t("Explicitly invoke hypertest-archive with the approved file paths. The CLI uploads, verifies the accepted version, then exits.", "显式调用 hypertest-archive 并提供获准文件路径。CLI 上传并核对接受版本后退出。")}</li></ol>
      <Typography.Paragraph>{t("Project ID", "项目 ID")}: <Typography.Text code copyable>{projectId}</Typography.Text></Typography.Paragraph>
      <Typography.Paragraph className="muted">{t("Testing needs no platform connection or background sync. Without a Subtask ID, artifacts go directly to the task root.", "测试期间无需连接平台或后台同步。未指定子任务 ID 时，产物直接归档到任务本身。")}</Typography.Paragraph>
    </section> : null}</div>;
}
