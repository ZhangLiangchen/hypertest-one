"use client";

import { ExperimentOutlined, GlobalOutlined } from "@ant-design/icons";
import { Select } from "antd";
import Link from "next/link";

import { useI18n } from "@/lib/i18n";

export function SiteHeader() {
  const { locale, setLocale, t } = useI18n();
  return <header className="topbar">
    <Link href="/" className="brand"><ExperimentOutlined /><span>HyperTest One</span></Link>
    <div className="topbar-actions">
      <span className="slogan">{t("One Input. One Mission. One Complete Test Cycle.", "一次输入，一个使命，完整测试闭环。")}</span>
      <Select
        className="locale-select"
        aria-label={t("Interface language", "界面语言")}
        value={locale}
        onChange={setLocale}
        suffixIcon={<GlobalOutlined />}
        options={[{ value: "zh", label: "中文" }, { value: "en", label: "English" }]}
        popupMatchSelectWidth={120}
      />
    </div>
  </header>;
}
