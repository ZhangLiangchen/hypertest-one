"use client";

import "@ant-design/v5-patch-for-react-19";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ConfigProvider } from "antd";
import type { ThemeConfig } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { I18nProvider, useI18n } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";

// Stable tokens prevent a second component style set after hydration.
const workspaceTheme: ThemeConfig = {
    token: {
      // Server and browser use the same tokens; CSS keeps hover and press feedback.
      motion: false,
      colorPrimary: "#2563eb", colorPrimaryBorder: "#2563eb", colorPrimaryHover: "#1d4ed8", colorPrimaryActive: "#1e40af",
      colorLink: "#2563eb", colorLinkHover: "#1d4ed8", colorLinkActive: "#1e40af",
      colorInfo: "#0e7490", colorInfoText: "#0e7490", colorInfoBg: "#e7f6fb", colorInfoBorder: "#8cc6d8",
      colorSuccess: "#22734c",
      colorWarning: "#94620b", colorWarningBg: "#fffcf3", colorWarningBorder: "#e7ddc2", colorWarningText: "#805507",
      colorError: "#b53f40", colorText: "#172338",
      colorTextSecondary: "#526177", colorTextDescription: "#526177", colorTextPlaceholder: "#5f6f85", colorBorder: "#8190a5", colorBgLayout: "#f2f5fa",
      borderRadius: 10, borderRadiusLG: 16, fontSize: 14, controlHeight: 38,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    components: {
      Button: { primaryShadow: "0 3px 8px rgb(37 99 235 / 16%)", defaultShadow: "none", fontWeight: 500 },
      Table: { headerBg: "#f7f9fc", headerColor: "#526177", rowHoverBg: "#f3f7ff", cellPaddingBlock: 16, cellPaddingInline: 20 },
      Tabs: { titleFontSize: 14, horizontalItemGutter: 26, itemSelectedColor: "#1e40af", itemHoverColor: "#1d4ed8", itemActiveColor: "#1e40af" },
      Card: { headerFontSize: 17, headerHeight: 56, paddingLG: 24 },
      Form: { itemMarginBottom: 24, labelColor: "#172338" },
      Descriptions: { labelBg: "#f7f9fc", titleMarginBottom: 20, itemPaddingBottom: 16 },
      Segmented: { trackBg: "#edf1f7", itemSelectedBg: "#ffffff", itemSelectedColor: "#1e40af" },
      Modal: { borderRadiusLG: 20 }, Drawer: { paddingLG: 24 },
    },
  };

function LocalizedProviders({ children }: { children: React.ReactNode }) {
  const { locale } = useI18n();
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5_000, refetchOnWindowFocus: false },
        },
      }),
  );

  return <ConfigProvider locale={locale === "zh" ? zhCN : enUS} theme={workspaceTheme}>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  </ConfigProvider>;
}

export function Providers({ children, initialLocale }: { children: React.ReactNode; initialLocale: Locale }) {
  return <I18nProvider initialLocale={initialLocale}><LocalizedProviders>{children}</LocalizedProviders></I18nProvider>;
}
