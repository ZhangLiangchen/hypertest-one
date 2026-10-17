"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Space, Spin, Typography } from "antd";
import { useState } from "react";

import { getConfigurationContent, getPolicySnapshot, getPrdContent, getSourceSnapshot } from "@/lib/api";

export function RunInputs({ sourceId, policyId }: { sourceId: string; policyId: string }) {
  const [open, setOpen] = useState(false);
  const source = useQuery({ queryKey: ["source-snapshot", sourceId], queryFn: () => getSourceSnapshot(sourceId), enabled: open });
  const policy = useQuery({ queryKey: ["policy-snapshot", policyId], queryFn: () => getPolicySnapshot(policyId), enabled: open });
  const prd = useQuery({ queryKey: ["prd", sourceId], queryFn: () => getPrdContent(sourceId), enabled: open, retry: false });
  const configuration = useQuery({ queryKey: ["configuration", sourceId], queryFn: () => getConfigurationContent(sourceId), enabled: open, retry: false });
  return <>
    <Button onClick={() => setOpen(true)}>Run inputs</Button>
    <Drawer title="Immutable run inputs" open={open} width={820} onClose={() => setOpen(false)}>
      <Typography.Paragraph className="muted">This run uses a fixed source revision, requirements and policy. New inputs belong to a new test run.</Typography.Paragraph>
      <Typography.Title level={4}>Source snapshot</Typography.Title>
      {source.isLoading ? <Spin /> : source.error ? <Alert type="error" message="Unable to load the source snapshot" description={String(source.error)} /> : source.data && <Descriptions bordered column={1} size="small" items={[
        { key: "repository", label: "Repository", children: <Typography.Text copyable>{source.data.repository_url}</Typography.Text> },
        { key: "commit", label: "Commit", children: <Typography.Text code copyable>{source.data.commit_sha}</Typography.Text> },
        { key: "branch", label: "Branch", children: source.data.branch || "—" },
        { key: "prd", label: "Requirements SHA-256", children: <Typography.Text code copyable>{source.data.prd_sha256}</Typography.Text> },
        { key: "config", label: "Configuration SHA-256", children: <Typography.Text code copyable>{source.data.configuration_sha256}</Typography.Text> },
      ]} />}
      <Typography.Title level={4}>Product requirements</Typography.Title>
      {prd.isLoading ? <Spin /> : prd.error ? <Alert type="warning" message="Requirements artifact unavailable" description={String(prd.error)} /> : <pre className="artifact-content">{prd.data}</pre>}
      <Typography.Title level={4}>Testing configuration</Typography.Title>
      {configuration.isLoading ? <Spin /> : configuration.error ? <Alert type="warning" message="Configuration artifact unavailable" description={String(configuration.error)} /> : <pre className="artifact-content">{configuration.data || "(empty configuration)"}</pre>}
      <Typography.Title level={4}>Policy snapshot</Typography.Title>
      {policy.isLoading ? <Spin /> : policy.error ? <Alert type="error" message="Unable to load the policy snapshot" description={String(policy.error)} /> : policy.data && <>
        <Space direction="vertical" style={{ width: "100%" }}><Typography.Text strong>{policy.data.policy_name} · {policy.data.policy_version}</Typography.Text><Typography.Text code copyable>{policy.data.content_sha256}</Typography.Text></Space>
        <pre className="artifact-content">{JSON.stringify(policy.data.compiled_policy, null, 2)}</pre>
      </>}
    </Drawer>
  </>;
}
