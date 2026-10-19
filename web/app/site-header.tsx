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
  return <><a href="#main-content" className="skip-link">{t("Skip to content", "跳转到内容")}</a><header className="topbar">
    <Link href="/" className="brand"><ExperimentOutlined /><span>HyperTest One</span></Link>
    <nav className="topbar-nav" aria-label={t("Main navigation", "主导航")}>
      <Link href="/" aria-current={path === "/" ? "page" : undefined}><AppstoreOutlined aria-hidden /> {t("Projects", "项目")}</Link>
      {path !== "/" && <span className="header-location">/ {path.startsWith("/runs/") ? t("Test run", "测试运行") : t("Project workspace", "项目工作区")}</span>}
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
  </header><Drawer title={t("From input to a trusted verdict", "从输入到可信结论")} open={guideOpen} onClose={() => setGuideOpen(false)} width={440}>
    <Typography.Paragraph>{t("One Input. One Mission. One Complete Test Cycle.", "一次输入，一个使命，完整测试闭环。")}</Typography.Paragraph>
    <Steps direction="vertical" current={-1} items={[
      { title: t("Create a project", "创建项目"), description: t("Group requirements, test runs and evidence by repository.", "按仓库集中管理需求、测试运行和证据。") },
      { title: t("Pin the inputs", "固定测试输入"), description: t("Submit a PRD, an exact commit and a testing policy. Changed inputs need a new run.", "提交 PRD、完整提交 SHA 和测试策略。更换输入时创建新运行。") },
      { title: t("Run a test cycle", "运行完整测试周期"), description: t("The worker processes the saved task even after you leave the page.", "任务保存后由 Worker 处理，关闭页面不影响后台工作。") },
      { title: t("Follow the evidence", "追溯证据与判定"), description: t("Inspect execution facts, findings and the quality verdict. Task completion alone does not mean tests passed.", "查看正式执行、问题发现和质量判定。任务完成不代表测试通过。") },
    ]} />
  </Drawer></>;
}
