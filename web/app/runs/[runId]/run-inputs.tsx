"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Space, Spin, Typography } from "antd";
import { useState } from "react";

import { errorText, getConfigurationContent, getPolicySnapshot, getPrdContent, getSourceSnapshot } from "@/lib/api";

import { useI18n } from "@/lib/i18n";

export function RunInputs({ sourceId, policyId }: { sourceId: string; policyId: string }) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState(false);
  const source = useQuery({ queryKey: ["source-snapshot", sourceId], queryFn: () => getSourceSnapshot(sourceId), enabled: open });
  const policy = useQuery({ queryKey: ["policy-snapshot", policyId], queryFn: () => getPolicySnapshot(policyId), enabled: open });
  const prd = useQuery({ queryKey: ["prd", sourceId], queryFn: () => getPrdContent(sourceId), enabled: open, retry: false });
  const configuration = useQuery({ queryKey: ["configuration", sourceId], queryFn: () => getConfigurationContent(sourceId), enabled: open, retry: false });
  return <>
    <Button onClick={() => setOpen(true)}>{t("Run inputs", "运行输入")}</Button>
    <Drawer title={t("Immutable run inputs", "不可变运行输入")} open={open} width={820} onClose={() => setOpen(false)}>
      <Typography.Paragraph className="muted">{t("This run uses a fixed source revision, requirements and policy. New inputs belong to a new test run.", "本次运行固定使用同一源码版本、需求和策略。若输入变化，请创建新的测试运行。")}</Typography.Paragraph>
      <Typography.Title level={4}>{t("Source snapshot", "源码快照")}</Typography.Title>
      {source.isLoading ? <Spin /> : source.error ? <Alert type="error" message={t("Unable to load the source snapshot", "无法加载源码快照")} description={errorText(source.error, locale)} action={<Button onClick={() => void source.refetch()}>{t("Retry", "重试")}</Button>} /> : source.data && <Descriptions bordered column={1} size="small" items={[
        { key: "repository", label: t("Repository", "仓库"), children: <Typography.Text copyable>{source.data.repository_url}</Typography.Text> },
        { key: "commit", label: t("Commit", "提交"), children: <Typography.Text code copyable>{source.data.commit_sha}</Typography.Text> },
        { key: "branch", label: t("Branch", "分支"), children: source.data.branch || "—" },
        { key: "prd", label: t("Requirements SHA-256", "需求 SHA-256"), children: <Typography.Text code copyable>{source.data.prd_sha256}</Typography.Text> },
        { key: "config", label: t("Configuration SHA-256", "配置 SHA-256"), children: <Typography.Text code copyable>{source.data.configuration_sha256}</Typography.Text> },
      ]} />}
      <Typography.Title level={4}>{t("Product requirements", "产品需求")}</Typography.Title>
      {prd.isLoading ? <Spin /> : prd.error ? <Alert type="warning" message={t("Requirements artifact unavailable", "需求产物暂不可用")} description={errorText(prd.error, locale)} action={<Button onClick={() => void prd.refetch()}>{t("Retry", "重试")}</Button>} /> : <pre className="artifact-content">{prd.data}</pre>}
      <Typography.Title level={4}>{t("Testing configuration", "测试配置")}</Typography.Title>
      {configuration.isLoading ? <Spin /> : configuration.error ? <Alert type="warning" message={t("Configuration artifact unavailable", "配置产物暂不可用")} description={errorText(configuration.error, locale)} action={<Button onClick={() => void configuration.refetch()}>{t("Retry", "重试")}</Button>} /> : <pre className="artifact-content">{configuration.data || t("(empty configuration)", "（空配置）")}</pre>}
      <Typography.Title level={4}>{t("Policy snapshot", "策略快照")}</Typography.Title>
      {policy.isLoading ? <Spin /> : policy.error ? <Alert type="error" message={t("Unable to load the policy snapshot", "无法加载策略快照")} description={errorText(policy.error, locale)} action={<Button onClick={() => void policy.refetch()}>{t("Retry", "重试")}</Button>} /> : policy.data && <>
        <Space direction="vertical" style={{ width: "100%" }}><Typography.Text strong>{policy.data.policy_name} · {policy.data.policy_version}</Typography.Text><Typography.Text code copyable>{policy.data.content_sha256}</Typography.Text></Space>
        <pre className="artifact-content">{JSON.stringify(policy.data.compiled_policy, null, 2)}</pre>
      </>}
    </Drawer>
  </>;
}
