"use client";

import { LaptopOutlined } from "@ant-design/icons";
import { Button, Typography } from "antd";
import { useId, useState } from "react";

import { LocalSetupContent } from "@/app/tasks/source-client-upgrade";
import { useI18n } from "@/lib/i18n";

/** Installs no software in the browser and reads no local profile or credentials. */
export function LocalModeGuide({ projectId, initiallyOpen = false }: { projectId: string; initiallyOpen?: boolean }) {
  const { t } = useI18n();
  const id = useId();
  const [open, setOpen] = useState(initiallyOpen);
  return <div style={{ marginBlock: 16 }}>
    <Button icon={<LaptopOutlined aria-hidden />} aria-expanded={open} aria-controls={`${id}-guide`} onClick={() => setOpen((value) => !value)}>
      {open ? t("Hide local mode setup", "收起本地模式接入") : t("Set up local mode", "接入本地模式")}
    </Button>
    {open ? <section id={`${id}-guide`} aria-labelledby={`${id}-heading`} className="data-surface" style={{ marginTop: 12, padding: 24 }}>
      <Typography.Title id={`${id}-heading`} level={3} style={{ marginTop: 0 }}>{t("Connect this project's local Agent", "接入此项目的本地 Agent")}</Typography.Title>
      <Typography.Paragraph>{t("Target Project", "目标项目")}: <Typography.Text code>{projectId}</Typography.Text></Typography.Paragraph>
      <LocalSetupContent projectId={projectId} />
      <Typography.Paragraph style={{ marginTop: 24, maxWidth: "75ch" }}>{t("After setup, open the intended task and copy its binding or collaboration request to the real parent Agent session. Installation preserves sync history; it does not bind a task or start tests.", "接入完成后，打开目标任务，将绑定或协作请求交给真实父会话中的 Agent。安装会保留同步历史，不会绑定任务或启动测试。")}</Typography.Paragraph>
    </section> : null}
  </div>;
}
