"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Space, Typography } from "antd";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { createProject, errorText } from "@/lib/api";
import { ClientModal as Modal } from "@/app/client-modal";
import { useI18n } from "@/lib/i18n";
import { createUuid } from "@/lib/uuid";
import type { Project } from "@/lib/types";

type ProjectFormValues = {
  key: string;
  name: string;
  description?: string;
  repository_url?: string;
  default_branch: string;
};

export function CreateProjectDialog({ open, onClose, projects }: { open: boolean; onClose: () => void; projects: Project[] }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<ProjectFormValues>();
  useEffect(() => {
    if (!open) return;
    const invalid = form.getFieldsError().filter((field) => field.errors.length).map((field) => field.name);
    if (invalid.length) void form.validateFields(invalid, { recursive: true }).catch(() => undefined);
  }, [locale, form, open]);
  const enteredKey = Form.useWatch("key", form);
  const existingProject = projects.find((project) => project.key === enteredKey?.trim().toUpperCase());
  const creation = useMutation({
    mutationFn: (values: ProjectFormValues) => createProject({
      key: values.key.trim().toUpperCase(),
      name: values.name.trim(),
      description: values.description?.trim() || undefined,
      repository_url: values.repository_url?.trim() || undefined,
      default_branch: values.default_branch.trim(),
    }),
    onSuccess: (project) => {
      queryClient.setQueryData(["project", project.id], project);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${project.id}`);
    },
    onError: () => {
      // A response can be lost after creation. Refresh the list so the existing project is reachable.
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const suggestKey = () => {
    if (form.getFieldValue("key")) return;
    const name = String(form.getFieldValue("name") || "");
    const suggested = name.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 64);
    form.setFieldValue("key", suggested.length >= 2 ? suggested : `PROJECT_${createUuid().slice(0, 8).toUpperCase()}`);
  };
  return (
      <Modal
        title={t("Create project", "创建项目")}
        open={open}
        forceRender
        onCancel={onClose}
        footer={null}
        closable={!creation.isPending}
        maskClosable={!creation.isPending}
        keyboard={!creation.isPending}
        width={600}
      >
        <Typography.Paragraph className="muted">
          {t("A project groups Codex testing tasks, plans, cases and reports. After creation, sync the testing work from its Codex sessions.", "项目集中管理 Codex 测试任务、计划、用例和报告。创建后，从所属 Codex 会话同步测试工作。")}
        </Typography.Paragraph>
        {creation.isError ? (
          <Alert
            type="error"
            showIcon
            message={t("Project could not be created", "项目创建失败")}
            description={errorText(creation.error, locale)}
            style={{ marginBottom: 20 }}
          />
        ) : null}
        {existingProject && !creation.isSuccess ? (
          <Alert
            type="info"
            showIcon
            message={existingProject.deleted_at ? t("This key belongs to a deleted project. Restore it to reuse it.", "此标识属于已删除项目，请恢复原项目继续使用。") : t("This project key is already in use.", "此项目标识已被使用。")}
            description={<Link href={`/projects/${existingProject.id}`}>{existingProject.deleted_at ? t("Open project to restore", "打开项目并恢复") : t("Open the existing project", "打开已有项目")}: {existingProject.name}</Link>}
            style={{ marginBottom: 20 }}
          />
        ) : null}
        {creation.isSuccess ? (
          <Alert type="success" showIcon message={t("Project created. Opening your workspace…", "项目已创建，正在打开工作台…")} style={{ marginBottom: 20 }} />
        ) : null}
        <Form
          name="create-project"
          form={form}
          layout="vertical"
          initialValues={{ default_branch: "main" }}
          onFinish={(values) => creation.mutate(values)}
          onFinishFailed={({ errorFields }) => { if (errorFields[0]) form.scrollToField(errorFields[0].name, { focus: true }); }}
          onValuesChange={() => { if (creation.isError) creation.reset(); }}
          disabled={creation.isPending || creation.isSuccess}
          requiredMark="optional"
        >
          <Form.Item
            name="name"
            label={t("Project name", "项目名称")}
            rules={[{ required: true, whitespace: true, message: t("Enter a project name.", "请输入项目名称。") }, { max: 255, message: t("Use at most 255 characters.", "最多输入 255 个字符。") }]}
          >
            <Input placeholder={t("Payments service", "例如：支付服务")} maxLength={255} autoFocus onBlur={() => { if (form.getFieldValue("name")?.trim()) suggestKey(); }} />
          </Form.Item>
          <Form.Item
            name="key"
            label={t("Project key", "项目标识")}
            normalize={(value: string) => value.trim().toUpperCase()}
            extra={t("A unique 2–64 character identifier. A suggestion is filled from the project name; you can edit it.", "唯一的 2–64 位标识。会根据项目名自动建议，你也可以修改；支持大写字母、数字、下划线和连字符。")}
            rules={[
              { required: true, message: t("Enter a project key.", "请输入项目标识。") },
              { min: 2, max: 64, message: t("Use 2–64 characters.", "请输入 2–64 个字符。") },
              { pattern: /^[A-Z0-9_-]+$/, message: t("Use uppercase letters, numbers, underscores or hyphens.", "仅支持大写字母、数字、下划线或连字符。") },
              { validator: async (_, value: string) => { if (projects.some((project) => project.key === value?.trim().toUpperCase())) throw new Error(t("This key is taken. Choose another key or open the existing project above.", "此标识已被使用，请修改标识，或通过上方链接打开已有项目。")); } },
            ]}
          >
            <Input placeholder="PAYMENTS" maxLength={64} autoComplete="off" />
          </Form.Item>
          <Form.Item name="description" label={t("Description", "项目描述")}>
            <Input.TextArea rows={2} placeholder={t("What does this project do?", "描述项目的用途与测试范围")} />
          </Form.Item>
          <Form.Item
            name="repository_url"
            label={t("Repository origin", "仓库源地址（origin）")}
            extra={<>{t("Optional. Use the repository's origin address, not its checkout folder. In an existing checkout, run: ", "可选，用于预填新测试运行。填写仓库的 origin 地址，不是检出目录。在已有 Git 检出中执行：")}<Typography.Text code copyable>git remote get-url origin</Typography.Text>{t(". A local Git source path is valid only when it is the origin value itself. Choose the Worker checkout directory after creating a run.", "。本地 Git 源路径只有与 origin 输出本身一致时才有效；Worker 工作目录将在创建运行后选择。")}</>}
            rules={[{ max: 2048, message: t("Use at most 2,048 characters for the repository address.", "仓库地址最多 2,048 个字符。") }]}
          >
            <Input placeholder="https://github.com/your-team/your-repository" maxLength={2048} />
          </Form.Item>
          <Form.Item
            name="default_branch"
            label={t("Default branch", "默认分支")}
            rules={[{ required: true, whitespace: true, message: t("Enter the default branch.", "请输入默认分支。") }]}
          >
            <Input placeholder="main" />
          </Form.Item>
          <Typography.Paragraph className="muted">{t("Closing keeps your draft while you stay on this page.", "关闭窗口会保留当前页面内的草稿。")}</Typography.Paragraph>
          <Space style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button onClick={onClose}>{t("Close", "关闭")}</Button>
            <Button type="primary" htmlType="submit" aria-label={t("Create project", "创建项目")} loading={creation.isPending || creation.isSuccess}>
              {t("Create project", "创建项目")}
            </Button>
          </Space>
        </Form>
      </Modal>
  );
}
