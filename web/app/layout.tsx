import "antd/dist/reset.css";
import "./globals.css";

import { cookies } from "next/headers";
import { AntdRegistry } from "@ant-design/nextjs-registry";

import { Providers } from "@/app/providers";
import { SiteHeader } from "@/app/site-header";

export const metadata = {
  title: "HyperTest One",
  description: "One Input. One Mission. One Complete Test Cycle.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const initialLocale = (await cookies()).get("hypertest_locale")?.value === "en" ? "en" : "zh";
  return (
    <html lang={initialLocale === "zh" ? "zh-CN" : "en"}>
      <body>
        <AntdRegistry>
          <Providers initialLocale={initialLocale}>
            <div className="app-shell">
              <SiteHeader />
              <div id="main-content" tabIndex={-1} className="page-container">{children}</div>
            </div>
          </Providers>
        </AntdRegistry>
      </body>
    </html>
  );
}
