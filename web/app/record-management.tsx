"use client";

import { DeleteOutlined, DownOutlined, EditOutlined, ReloadOutlined, UndoOutlined } from "@ant-design/icons";
import { Alert, Button, Dropdown, Space, Typography } from "antd";
import type { ReactNode } from "react";

import { ClientModal } from "@/app/client-modal";
import { ApiError, errorText } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export type ManagementMode = "edit" | "status" | "delete" | "restore";

export function ManagementButtons({ deleted, compact, subject, onAction }: {
  deleted: boolean; compact?: boolean; subject: string; onAction: (mode: ManagementMode) => void;
}) {
  const { t } = useI18n();
  if (deleted) return <Button size={compact ? "small" : "middle"} icon={<UndoOutlined aria-hidden />} onClick={() => onAction("restore")} aria-label={`${t("Restore", "恢复")} ${subject}`}>{t("Restore", "恢复")}</Button>;
  if (compact) return <Dropdown menu={{ items: [
    { key: "edit", label: t("Edit", "编辑"), icon: <EditOutlined aria-hidden /> },
    { key: "status", label: t("Change status", "修改状态") },
    { key: "delete", label: t("Delete", "删除"), danger: true, icon: <DeleteOutlined aria-hidden /> },
  ], onClick: ({ key }) => onAction(key as ManagementMode) }} trigger={["click"]}>
    <Button size="small" aria-label={`${t("Manage", "管理")} ${subject}`}>{t("Manage", "管理")} <DownOutlined aria-hidden /></Button>
  </Dropdown>;
  return <Space wrap>
    <Button icon={<EditOutlined aria-hidden />} onClick={() => onAction("edit")}>{t("Edit", "编辑")}</Button>
    <Button onClick={() => onAction("status")}>{t("Change status", "修改状态")}</Button>
    <Button danger icon={<DeleteOutlined aria-hidden />} onClick={() => onAction("delete")}>{t("Delete", "删除")}</Button>
  </Space>;
}

export function ManagementDialog({ open, title, version, mode, pending, error, onRefresh, onCancel, onConfirm, children }: {
  open: boolean; title: string; version?: number; mode?: ManagementMode; pending: boolean; error: unknown;
  onRefresh: () => void; onCancel: () => void; onConfirm: () => void; children: ReactNode;
}) {
  const { t, locale } = useI18n();
  const conflict = error instanceof ApiError && error.status === 409 && /version is stale/i.test(error.detail);
  const confirmLabel = mode === "delete" ? t("Move to recycle bin", "移入回收站") : mode === "restore" ? t("Restore", "恢复") : t("Save changes", "保存修改");
  return <ClientModal open={open} title={title} width={680} onCancel={onCancel} onOk={onConfirm}
    confirmLoading={pending} closable={!pending} maskClosable={false} keyboard={!pending} cancelButtonProps={{ disabled: pending, "aria-label": t("Cancel", "取消") }}
    okButtonProps={{ danger: mode === "delete", disabled: pending, "aria-label": confirmLabel }} cancelText={t("Cancel", "取消")} okText={confirmLabel}>
    {error ? <Alert type="error" showIcon message={t("Changes could not be saved", "操作未能保存")}
      description={<>{errorText(error, locale)}{conflict ? <p>{t("Your input is preserved. Refresh the record, then cancel and reopen this dialog to review the latest version before saving again.", "已保留当前输入。请刷新记录，再取消并重新打开窗口，核对最新版本后保存。")}</p> : null}</>}
      action={<Button size="small" icon={<ReloadOutlined aria-hidden />} onClick={onRefresh}>{t("Refresh record", "刷新记录")}</Button>}
      style={{ marginBottom: 20 }} /> : null}
    {children}
    {version !== undefined ? <Typography.Paragraph className="muted management-version">{t("Editing version", "当前操作版本")} {version}</Typography.Paragraph> : null}
  </ClientModal>;
}
