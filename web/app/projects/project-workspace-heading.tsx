"use client";

import { PlusOutlined } from "@ant-design/icons";
import { Button, Space, Tag } from "antd";
import { WorkspaceHeading } from "@/app/workspace-ui";
import { useI18n } from "@/lib/i18n";
import type { Project } from "@/lib/types";
import { ProjectActions } from "./project-actions";

/** Both task views share project identity and differ only in their creation target. */
export function ProjectWorkspaceHeading({ project, projectId, mode }: { project?: Project; projectId: string; mode: "local" | "cloud" }) {
  const { t, label } = useI18n();
  const disabled = !project || Boolean(project.deleted_at);
  return <WorkspaceHeading backHref="/" backLabel={t("Projects", "项目")}
    title={project?.name || t("Project", "项目")}
    description={project?.description || t("Project testing workspace", "项目测试工作台")}
    actions={<Space wrap>{project ? <ProjectActions project={project} /> : null}<Button type="primary" icon={<PlusOutlined aria-hidden />}
      href={disabled ? undefined : `/projects/${projectId}/tasks/new?mode=${mode}`} disabled={disabled}>
      {mode === "local" ? t("Create local test task", "创建本地测试任务") : t("Create cloud test task", "创建云端测试任务")}
    </Button></Space>}
    metadata={project ? <>
      <span className="muted">{t("Project key", "项目标识")}: <span className="entity-key">{project.key}</span></span>
      <Tag color="blue">{label(project.status)}</Tag>
      {project.repository_url ? <Tag style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{t("SUT", "被测对象")}: {project.repository_url}</Tag> : null}
      {project.test_framework_repository_url ? <Tag style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{t("Test framework", "测试框架")}: {project.test_framework_repository_url}</Tag> : null}
    </> : undefined} />;
}
