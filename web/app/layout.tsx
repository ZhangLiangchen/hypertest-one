import "antd/dist/reset.css";
import "./globals.css";

import { ExperimentOutlined } from "@ant-design/icons";
import Link from "next/link";

import { Providers } from "@/app/providers";

export const metadata = {
  title: "HyperTest One",
  description: "One Input. One Mission. One Complete Test Cycle.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="app-shell">
            <header className="topbar">
              <Link href="/" className="brand">
                <ExperimentOutlined />
                <span>HyperTest One</span>
              </Link>
              <span className="slogan">
                One Input. One Mission. One Complete Test Cycle.
              </span>
            </header>
            <div className="page-container">{children}</div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
