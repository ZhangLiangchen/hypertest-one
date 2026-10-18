import type { EnvironmentCatalog, EnvironmentDefinition, EnvironmentProfileId, EnvironmentRequest, ExecutionEnvironmentProfile, RunCreate, ServiceRequest } from "@/lib/types";

export const environmentProfiles = ["python-pytest-v1", "python-api-v1"] as const;
export type EnvironmentFormValues = {
  environment_profile_id: EnvironmentProfileId;
  service_app: string;
  service_health_path: string;
  service_startup_timeout_seconds: number;
};
export function defaultEnvironmentValues(): EnvironmentFormValues {
  return { environment_profile_id: "python-pytest-v1", service_app: "", service_health_path: "/health", service_startup_timeout_seconds: 30 };
}
export function isEnvironmentProfile(value: unknown): value is EnvironmentProfileId {
  return environmentProfiles.includes(value as EnvironmentProfileId);
}
export function validServiceApp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 256 && /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$/.test(value);
}
export function validHealthPath(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 256 && /^\/[A-Za-z0-9_./~-]*$/.test(value) && !value.includes("//") && !value.includes("..") && !value.includes("%");
}
export function validStartupTimeout(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 120;
}
export function environmentInputIssue(values: EnvironmentFormValues): "profile" | "app" | "health" | "timeout" | null {
  if (!isEnvironmentProfile(values.environment_profile_id)) return "profile";
  if (values.environment_profile_id === "python-pytest-v1") return null;
  if (!validServiceApp(values.service_app)) return "app";
  if (!validHealthPath(values.service_health_path)) return "health";
  if (!validStartupTimeout(values.service_startup_timeout_seconds)) return "timeout";
  return null;
}
export function buildEnvironmentRequest(values: EnvironmentFormValues): EnvironmentRequest {
  if (environmentInputIssue(values)) throw new Error("Choose a valid controlled execution environment.");
  return values.environment_profile_id === "python-pytest-v1" ? { profile_id: values.environment_profile_id } : {
    profile_id: values.environment_profile_id,
    service: { app: values.service_app, health_path: values.service_health_path, startup_timeout_seconds: values.service_startup_timeout_seconds },
  };
}
export function selectedEnvironmentProfile(catalog: EnvironmentCatalog | undefined, selected: unknown): ExecutionEnvironmentProfile | undefined {
  if (!isEnvironmentProfile(selected) || !Array.isArray(catalog?.profiles)) return undefined;
  return catalog.profiles.find((profile) => profile && profile.profile_id === selected && profile.network === "none" && profile.kind === (selected === "python-api-v1" ? "asgi" : "pytest"));
}
export function canUseEnvironment(catalog: EnvironmentCatalog | undefined, selected: unknown, failed: boolean): boolean {
  return !failed && selectedEnvironmentProfile(catalog, selected)?.available === true;
}
export function executionBackend(environment: unknown, selected: "docker" | "local"): "docker" | "local" {
  return environment === null || environment === undefined ? selected : "docker";
}
export function runInputSignature(projectId: string, input: Omit<RunCreate, "idempotency_key">): string {
  // Reference labels do not change source identity. The controlled environment does.
  return JSON.stringify({ project_id: projectId, ...input, branch: undefined });
}

const digest = /^[0-9a-f]{64}$/;
const imageId = /^sha256:[0-9a-f]{64}$/;
export function safeHash(value: unknown): string | null { return typeof value === "string" && digest.test(value) ? value : null; }
export function safeImageId(value: unknown): string | null { return typeof value === "string" && imageId.test(value) ? value : null; }
export function visibleDependencies(value: unknown): Array<[string, string]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).filter((entry): entry is [string, string] => /^[A-Za-z0-9_.-]{1,128}$/.test(entry[0]) && typeof entry[1] === "string" && /^[A-Za-z0-9_.+!-]{1,128}$/.test(entry[1])).sort(([a], [b]) => a.localeCompare(b)).slice(0, 100);
}
function visibleRequest(value: unknown): EnvironmentRequest | null {
  if (!value || typeof value !== "object") return null;
  const request = value as Record<string, unknown>;
  if (request.profile_id === "python-pytest-v1") return { profile_id: request.profile_id };
  if (request.profile_id !== "python-api-v1" || !request.service || typeof request.service !== "object") return null;
  const service = request.service as Partial<ServiceRequest>;
  if (!validServiceApp(service.app) || !validHealthPath(service.health_path) || !validStartupTimeout(service.startup_timeout_seconds)) return null;
  return { profile_id: request.profile_id, service: { app: service.app, health_path: service.health_path, startup_timeout_seconds: service.startup_timeout_seconds } };
}
export function visibleEnvironmentDefinition(value: unknown): EnvironmentDefinition | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const request = visibleRequest(item.request);
  if (item.schema_version !== "hypertest.environment/v1" || !request || !safeImageId(item.image_id) || !safeHash(item.dependency_lock_sha256) || !safeHash(item.launcher_sha256)) return null;
  return {
    schema_version: "hypertest.environment/v1", request, image_id: item.image_id as string,
    image_os: ["linux", "windows"].includes(item.image_os as string) ? item.image_os as string : "—",
    image_architecture: ["amd64", "arm64", "arm", "386"].includes(item.image_architecture as string) ? item.image_architecture as string : "—",
    dependencies: Object.fromEntries(visibleDependencies(item.dependencies)),
    dependency_lock_sha256: item.dependency_lock_sha256 as string, launcher_sha256: item.launcher_sha256 as string,
  };
}
export function visibleExecutionIdentity(spec: Record<string, unknown> | null | undefined) {
  const environment = spec?.environment && typeof spec.environment === "object" ? spec.environment as Record<string, unknown> : {};
  const definition = spec?.environment_definition == null ? environment.environment_definition : spec.environment_definition;
  return {
    image_id: safeImageId(environment.image_id),
    definition: visibleEnvironmentDefinition(definition),
    network: environment.network === "none" ? "none" : null,
  };
}
