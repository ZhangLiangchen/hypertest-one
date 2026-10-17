"use client";

import "@ant-design/v5-patch-for-react-19";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { I18nProvider, useI18n } from "@/lib/i18n";
import type { Locale } from "@/lib/i18n";

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

  return <ConfigProvider locale={locale === "zh" ? zhCN : enUS}>
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  </ConfigProvider>;
}

export function Providers({ children, initialLocale }: { children: React.ReactNode; initialLocale: Locale }) {
  return <I18nProvider initialLocale={initialLocale}><LocalizedProviders>{children}</LocalizedProviders></I18nProvider>;
}
