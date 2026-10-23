import type { ProjectUpdate, SessionTaskStatus, SessionTaskUpdate } from "@/lib/types";

export const TASK_STATUSES: SessionTaskStatus[] = ["DRAFT", "IN_PROGRESS", "BLOCKED", "COMPLETED", "CANCELLED"];
export type ProjectEditValues = { name: string; description?: string; repository_url?: string; default_branch: string };
export type TaskEditValues = { title: string; objective: string; plan_markdown: string };

export function projectEditPayload(values: ProjectEditValues, expectedVersion: number): ProjectUpdate {
  return { expected_version: expectedVersion, name: values.name.trim(), description: values.description?.trim() || null,
    repository_url: values.repository_url?.trim() || null, default_branch: values.default_branch.trim() };
}

export function taskEditPayload(values: TaskEditValues, expectedVersion: number): SessionTaskUpdate {
  return { expected_version: expectedVersion, title: values.title.trim(), objective: values.objective, plan_markdown: values.plan_markdown };
}
