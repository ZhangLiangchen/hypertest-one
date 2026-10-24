"use client";

import { AppstoreOutlined, ExperimentOutlined, GlobalOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import { Button, Drawer, Select, Steps, Typography } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";

export function SiteHeader() {
  const { locale, setLocale, t } = useI18n();
  const path = usePathname();
  const [guideOpen, setGuideOpen] = useState(false);
  const location = path.startsWith("/cloud-tasks/") ? t("Cloud task", "云端任务")
    : path.startsWith("/runs/") ? t("Test run", "测试运行")
      : path.startsWith("/tasks/") ? t("Local task", "本地任务")
        : path.endsWith("/tasks/new") ? t("Create test task", "创建测试任务")
          : path.endsWith("/memory") ? t("Project experience", "项目经验")
            : path.endsWith("/cloud") ? t("Cloud testing", "云端测试")
              : t("Project workspace", "项目工作区");
  return <><a href="#main-content" className="skip-link">{t("Skip to content", "跳转到内容")}</a><header className="topbar">
    <Link href="/" className="brand"><ExperimentOutlined /><span>HyperTest One</span></Link>
    <nav className="topbar-nav" aria-label={t("Main navigation", "主导航")}>
      <Link href="/" aria-current={path === "/" ? "page" : undefined}><AppstoreOutlined aria-hidden /> {t("Projects", "项目")}</Link>
      {path !== "/" && <span className="header-location">/ {location}</span>}
    </nav>
    <div className="topbar-actions">
      <Button className="guide-button" type="text" icon={<QuestionCircleOutlined aria-hidden />} onClick={() => setGuideOpen(true)} aria-label={t("Workflow guide", "使用指南")}><span>{t("Guide", "使用指南")}</span></Button>
      <Select
        className="locale-select"
        id="interface-language"
        aria-label={t("Interface language", "界面语言")}
        value={locale}
        onChange={setLocale}
        suffixIcon={<GlobalOutlined />}
        options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]}
        popupMatchSelectWidth={120}
      />
    </div>
  </header><Drawer title={t("Manage Codex testing work", "管理 Codex 测试工作")} open={guideOpen} onClose={() => setGuideOpen(false)} width={440}>
    <Typography.Paragraph>{t("One Input. One Mission. One Complete Test Cycle.", "一次输入，一个使命，完整测试闭环。")}</Typography.Paragraph>
    <Steps direction="vertical" current={-1} items={[
      { title: t("Choose a project", "选择测试项目"), description: t("Keep each project's tasks, cases and reports together.", "集中管理项目的任务、用例和报告。") },
      { title: t("Work in Codex", "在 Codex 中测试"), description: t("Use one Codex session for one task. Codex analyzes, designs, implements and calls the project's existing tests.", "一个 Codex 会话对应一个任务，由 Codex 分析、设计、实现并调用项目已有测试。") },
      { title: t("Sync the work", "同步测试产物"), description: t("Sync the task, plan, cases and original reports from the session.", "从会话同步任务、计划、用例和原始报告。") },
      { title: t("Review results and history", "查看结果与历史"), description: t("Read Codex's reported results, original reports and revisions. Task progress and test results are shown separately.", "查看 Codex 报告结果、原始报告和修订。任务进度与测试结果分别展示。") },
    ]} />
    <Typography.Paragraph className="muted">{t("Existing managed test runs and their execution records remain available under each project's history.", "既有受管测试运行及其执行记录仍可在项目历史入口查看。")}</Typography.Paragraph>
  </Drawer></>;
}
