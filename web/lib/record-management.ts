import type { ProjectUpdate } from "@/lib/types";

export type ProjectEditValues = { name: string; description?: string; repository_url?: string; test_framework_repository_url?: string };

export function projectEditPayload(values: ProjectEditValues, expectedVersion: number): ProjectUpdate {
  return { expected_version: expectedVersion, name: values.name.trim(), description: values.description?.trim() || null,
    repository_url: values.repository_url?.trim() || null, test_framework_repository_url: values.test_framework_repository_url?.trim() || null };
}
