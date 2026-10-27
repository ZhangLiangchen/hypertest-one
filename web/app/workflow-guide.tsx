"use client";

import { Drawer, Steps, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

export function WorkflowGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return <Drawer title={t("Manage local and cloud testing work", "管理本地与云端测试工作")} open={open} onClose={onClose} width={440}>
    <Typography.Paragraph>{t("One Input. One Mission. One Complete Test Cycle.", "一次输入，一个使命，完整测试闭环。")}</Typography.Paragraph>
    <Steps direction="vertical" current={-1} items={[
      { title: t("Choose a project", "选择测试项目"), description: t("Keep each project's tasks, cases and reports together.", "集中管理项目的任务、用例和报告。") },
      { title: t("Choose a testing mode", "选择测试方式"), description: t("Test locally with Codex, Claude Code or DeepSeek Harness. Cloud testing supports DeepSeek Harness + Codex.", "本地可使用 Codex、Claude Code 或 DeepSeek Harness；云端支持 DeepSeek Harness + Codex 测试。") },
      { title: t("Collect testing artifacts", "归集测试产物"), description: t("Explicitly archive local artifacts with the CLI Skill after testing. Cloud artifacts remain under their Project, with sources and versions preserved.", "本地测试结束后显式调用 CLI Skill 归档产物；云端产物归集到所属项目，保留来源和版本。") },
      { title: t("Review results and history", "查看结果与历史"), description: t("Read Agent-reported results, original reports and revisions. Task progress and test results are shown separately.", "查看 Agent 报告结果、原始报告和修订。任务进度与测试结果分别展示。") },
    ]} />
    <Typography.Paragraph><Typography.Link href="/cli-authorizations#cli-install">{t("Get the CLI installation prompt for your Agent", "获取给 Agent 的 CLI 安装 Prompt")}</Typography.Link></Typography.Paragraph>
    <Typography.Paragraph className="muted">{t("Existing managed test runs and their execution records remain available under each project's history.", "既有受管测试运行及其执行记录仍可在项目历史入口查看。")}</Typography.Paragraph>
  </Drawer>;
}
