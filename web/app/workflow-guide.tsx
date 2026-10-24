"use client";

import { Drawer, Steps, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

export function WorkflowGuide({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  return <Drawer title={t("Manage Codex testing work", "管理 Codex 测试工作")} open={open} onClose={onClose} width={440}>
    <Typography.Paragraph>{t("One Input. One Mission. One Complete Test Cycle.", "一次输入，一个使命，完整测试闭环。")}</Typography.Paragraph>
    <Steps direction="vertical" current={-1} items={[
      { title: t("Choose a project", "选择测试项目"), description: t("Keep each project's tasks, cases and reports together.", "集中管理项目的任务、用例和报告。") },
      { title: t("Work in Codex", "在 Codex 中测试"), description: t("Use one Codex session for one task. Codex analyzes, designs, implements and calls the project's existing tests.", "一个 Codex 会话对应一个任务，由 Codex 分析、设计、实现并调用项目已有测试。") },
      { title: t("Sync the work", "同步测试产物"), description: t("Sync the task, plan, cases and original reports from the session.", "从会话同步任务、计划、用例和原始报告。") },
      { title: t("Review results and history", "查看结果与历史"), description: t("Read Codex's reported results, original reports and revisions. Task progress and test results are shown separately.", "查看 Codex 报告结果、原始报告和修订。任务进度与测试结果分别展示。") },
    ]} />
    <Typography.Paragraph className="muted">{t("Existing managed test runs and their execution records remain available under each project's history.", "既有受管测试运行及其执行记录仍可在项目历史入口查看。")}</Typography.Paragraph>
  </Drawer>;
}
