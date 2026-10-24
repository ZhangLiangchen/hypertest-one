"use client";

import { AppstoreOutlined, ExperimentOutlined, GlobalOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import { Button, Select } from "antd";
import Link from "next/link";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useI18n } from "@/lib/i18n";

const WorkflowGuide = dynamic(() => import("./workflow-guide").then((module) => module.WorkflowGuide));

export function SiteHeader() {
  const { locale, setLocale, t } = useI18n();
  const path = usePathname();
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideOpened, setGuideOpened] = useState(false);
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
      <Button className="guide-button" type="text" icon={<QuestionCircleOutlined aria-hidden />} onClick={() => { setGuideOpened(true); setGuideOpen(true); }} aria-label={t("Workflow guide", "使用指南")}><span>{t("Guide", "使用指南")}</span></Button>
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
  </header>{guideOpened && <WorkflowGuide open={guideOpen} onClose={() => setGuideOpen(false)} />}</>;
}
