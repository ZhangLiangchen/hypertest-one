import "antd/dist/reset.css";
import "./globals.css";

import { ExperimentOutlined } from "@ant-design/icons";
import { Layout, Typography } from "antd";
import Link from "next/link";

import { Providers } from "@/app/providers";

const { Header, Content } = Layout;

export const metadata = {
  title: "HyperTest One",
  description: "One Input. One Mission. One Complete Test Cycle.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Layout className="app-shell">
            <Header className="topbar">
              <Link href="/" className="brand">
                <ExperimentOutlined />
                <span>HyperTest One</span>
              </Link>
              <Typography.Text className="slogan">
                One Input. One Mission. One Complete Test Cycle.
              </Typography.Text>
            </Header>
            <Content className="page-container">{children}</Content>
          </Layout>
        </Providers>
      </body>
    </html>
  );
}
