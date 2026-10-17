"use client";

import "@ant-design/v5-patch-for-react-19";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { I18nProvider, useI18n } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";

function LocalizedProviders({ children }: { children: React.ReactNode }) {
  const { locale } = useI18n();
  const [reducedMotion, setReducedMotion] = useState(false);
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(preference.matches);
    update();
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 5_000, refetchOnWindowFocus: false },
        },
      }),
  );

  return <ConfigProvider locale={locale === "zh" ? zhCN : enUS} theme={{
    token: {
      motion: !reducedMotion,
      colorPrimary: "#2563eb", colorPrimaryBorder: "#2563eb", colorPrimaryHover: "#1d4ed8", colorPrimaryActive: "#1e40af",
      colorLink: "#2563eb", colorLinkHover: "#1d4ed8", colorLinkActive: "#1e40af",
      colorInfo: "#0e7490", colorInfoText: "#0e7490", colorInfoBg: "#e7f6fb", colorInfoBorder: "#8cc6d8",
      colorSuccess: "#22734c",
      colorWarning: "#94620b", colorError: "#b53f40", colorText: "#172338",
      colorTextSecondary: "#526177", colorTextPlaceholder: "#5f6f85", colorBorder: "#8190a5", colorBgLayout: "#f3f6fb",
      borderRadius: 6, fontSize: 14, controlHeight: 36,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
    },
    components: {
      Button: { primaryShadow: "none", defaultShadow: "none", fontWeight: 500 },
      Table: { headerBg: "#f1f5fb", headerColor: "#526177", cellPaddingBlock: 16 },
      Tabs: { titleFontSize: 14, horizontalItemGutter: 26, itemSelectedColor: "#1e40af", itemHoverColor: "#1d4ed8", itemActiveColor: "#1e40af" },
      Modal: { borderRadiusLG: 12 }, Drawer: { paddingLG: 24 },
    },
  }}>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  </ConfigProvider>;
}

export function Providers({ children, initialLocale }: { children: React.ReactNode; initialLocale: Locale }) {
  return <I18nProvider initialLocale={initialLocale}><LocalizedProviders>{children}</LocalizedProviders></I18nProvider>;
}
