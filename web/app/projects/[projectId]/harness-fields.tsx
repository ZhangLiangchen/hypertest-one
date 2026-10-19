"use client";

import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Popconfirm, Radio, Select, Space, Typography } from "antd";
import type { FormInstance } from "antd";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { createUuid } from "@/lib/uuid";

type Node = { id: string; node_key: string; display_name: string; presence: string; registration_status: string };
type Scope = { id: string; project_id: string; capability: string; constraints: Record<string, unknown>; status: string };

export function HarnessFields({ form, projectId }: { form: FormInstance; projectId: string }) {
  const { t } = useI18n();
  const mode = Form.useWatch("harness_mode", { form, preserve: true }) || "SERVER_HOST";
  const nodeId = Form.useWatch("harness_node_id", { form, preserve: true });
  const origin = Form.useWatch("repository_url", { form, preserve: true }) || "";
  const commit = Form.useWatch("commit_sha", { form, preserve: true }) || "";
  const accepted = Form.useWatch("source_bundle_transfer_id", { form, preserve: true });
  const [operatorKey, setOperatorKey] = useState("");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [name, setName] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const signature = JSON.stringify([nodeId, origin.trim(), commit.trim().toLowerCase()]);
  useEffect(() => {
    const saved = form.getFieldValue("harness_source_signature");
    if (saved && saved !== signature) form.setFieldsValue({ source_bundle_transfer_id: undefined, harness_source_signature: undefined });
  }, [form, signature]);

  async function request<T>(path: string, body?: unknown): Promise<T> {
    if (!operatorKey) throw new Error(t("Enter the device management key.", "请输入设备管理密钥。"));
    const response = await fetch(`/api/v1${path}`, { method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Hypertest-Operator-Key": operatorKey },
      body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : t("The device request was rejected. Check the service configuration and authorization.", "设备请求被拒绝，请检查服务配置与授权。"));
    return result as T;
  }
  const action = useMutation({ mutationFn: async (operation: "load" | "pair" | "rotate" | "revoke" | "source") => {
    if (operation === "pair") {
      if (!name.trim()) throw new Error(t("Enter a device name.", "请输入设备名称。"));
      const paired = await request<{ node: Node; device_token: string }>("/harness-nodes/pair", { node_key: `local-${createUuid()}`, display_name: name.trim() });
      setToken(paired.device_token);
      form.setFieldsValue({ harness_node_id: paired.node.id });
    } else if (operation === "rotate") {
      const rotated = await request<{ device_token: string }>(`/harness-nodes/${nodeId}/rotate`, {});
      setToken(rotated.device_token);
    } else if (operation === "revoke") {
      await request(`/harness-nodes/${nodeId}/revoke`, {});
      form.setFieldsValue({ harness_node_id: undefined, source_bundle_transfer_id: undefined });
      setToken(null);
    } else if (operation === "source") {
      if (!nodeId || !origin.trim() || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(commit.trim())) throw new Error(t("Choose a device, repository and full SHA first.", "请先选择设备，填写仓库地址及完整 SHA。"));
      const scopes = await request<Scope[]>(`/harness-nodes/${nodeId}/capabilities`);
      for (const capability of ["harness", "source_acquisition"]) {
        const existing = scopes.find((item) => item.project_id === projectId && item.capability === capability && item.status === "ACTIVE");
        if (!existing) await request(`/harness-nodes/${nodeId}/capabilities`, { project_id: projectId, capability,
          policy_version: "operator-v1", constraints: capability === "source_acquisition" ? { allowed_origins: [origin.trim()], policy_version: "operator-v1" } : {} });
        else if (capability === "source_acquisition" && !(Array.isArray(existing.constraints.allowed_origins) && existing.constraints.allowed_origins.includes(origin.trim()))) throw new Error(t("This device's source grant does not include this repository. Review its project authorization first.", "此设备的源码授权不包含当前仓库，请先核对项目授权。"));
      }
      const transfer = await request<{ id: string }>(`/projects/${projectId}/source-transfers`, { request_id: createUuid(), node_id: nodeId,
        idempotency_key: `web-source:${createUuid()}`, origin: origin.trim(), commit_sha: commit.trim().toLowerCase(), policy_version: "operator-v1" });
      const result = await request<{ status: string }>(`/source-transfers/${transfer.id}/dispatch`, {});
      if (result.status !== "ACCEPTED") throw new Error(t("Source has not been accepted. Inspect the transfer before retrying.", "源码尚未验收，请检查传输状态后再重试。"));
      form.setFieldsValue({ source_bundle_transfer_id: transfer.id, harness_source_signature: signature });
    }
    setNodes(await request<Node[]>("/harness-nodes"));
  } });

  return <>
    <Form.Item name="harness_mode" label={t("Agent location", "Agent 运行位置")} initialValue="SERVER_HOST">
      <Radio.Group onChange={() => form.setFieldsValue({ source_bundle_transfer_id: undefined, source_mode: "sha" })} options={[
        { value: "SERVER_HOST", label: t("Server", "服务器") }, { value: "LOCAL_CONNECTOR", label: t("My computer", "我的电脑") },
      ]} />
    </Form.Item>
    {mode === "LOCAL_CONNECTOR" && <>
      <Typography.Paragraph className="muted">{t("The local Connector uses your existing sign-ins. Source is sent to the platform for verified execution. Your computer must stay online; an offline device is never replaced automatically.", "本地 Connector 复用已有登录，源码会交付平台校验并执行。电脑需要保持在线；设备离线不会自动改用服务器。")}</Typography.Paragraph>
      <Form.Item required label={t("Device management key", "设备管理密钥")} extra={t("Used only for these device actions. It is kept in this view's memory.", "仅用于当前设备操作，只保存在此视图的内存中。") }>
        <Input.Password autoComplete="off" value={operatorKey} onChange={(event) => setOperatorKey(event.target.value)} />
      </Form.Item>
      <Space wrap style={{ marginBottom: 16 }}>
        <Button onClick={() => action.mutate("load")} loading={action.isPending}>{t("Refresh devices", "刷新设备")}</Button>
        <Input aria-label={t("New device name", "新设备名称")} placeholder={t("Device name", "设备名称")} value={name} onChange={(event) => setName(event.target.value)} maxLength={128} />
        <Button disabled={action.isPending || !name.trim()} onClick={() => action.mutate("pair")}>{t("Pair device", "配对设备")}</Button>
      </Space>
      <Form.Item name="harness_node_id" label={t("Local device", "本地设备")} rules={[{ required: true, message: t("Choose a paired device.", "请选择已配对设备。") }]}>
        <Select options={nodes.filter((node) => node.registration_status === "ACTIVE").map((node) => ({ value: node.id, label: `${node.display_name} · ${node.presence === "ONLINE" ? t("Online", "在线") : t("Offline", "离线")}` }))} />
      </Form.Item>
      {token && <Alert type="info" showIcon message={t("Save this device token on your computer", "请将设备令牌保存到本机")} description={<><Typography.Paragraph>{t("Shown once. Use a protected token file with the Connector startup instructions. Git and issue-platform tokens stay on your computer.", "仅显示一次。请按 Connector 启动说明将其保存到受保护的令牌文件。Git 和问题单平台凭据继续留在本机。")}</Typography.Paragraph><Typography.Text code copyable>{token}</Typography.Text></>} />}
      <Space wrap style={{ marginBlock: 16 }}>
        <Button disabled={!nodeId || action.isPending} onClick={() => action.mutate("rotate")}>{t("Rotate token", "轮换令牌")}</Button>
        <Popconfirm title={t("Revoke this device? Existing calls will lose authorization.", "撤销此设备？现有调用将失去授权。 ")} onConfirm={() => action.mutate("revoke")}>
          <Button danger disabled={!nodeId || action.isPending}>{t("Revoke device", "撤销设备")}</Button>
        </Popconfirm>
      </Space>
      <Form.Item name="source_bundle_transfer_id" hidden rules={[{ required: true, message: t("Receive and verify local source before continuing.", "请先接收并验证本地源码。") }]}><Input /></Form.Item>
      <Form.Item name="harness_source_signature" hidden><Input /></Form.Item>
      <Button loading={action.isPending} disabled={!nodeId || action.isPending || nodes.find((node) => node.id === nodeId)?.presence !== "ONLINE"} onClick={() => action.mutate("source")}>{t("Authorize this repository and receive source", "授权此仓库并接收源码")}</Button>
      {accepted && <Alert type="success" showIcon message={t("Pinned source verified", "固定源码已验证")} style={{ marginBlock: 16 }} />}
      {action.isError && <Alert type="error" showIcon message={t("Local device action failed", "本地设备操作失败")} description={action.error.message} style={{ marginBlock: 16 }} />}
    </>}
  </>;
}
