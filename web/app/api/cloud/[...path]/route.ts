/** Trusted single-operator Web boundary. Never serialize the server key. */
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { NextRequest, NextResponse } from "next/server";
import { cloudServerRequest, cloudServerTransportReady } from "@/lib/cloud-server-auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const UUID = "[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}";
const GET_PATH = new RegExp(`^(?:capabilities|projects/${UUID}/(?:configuration|credentials|tasks|task-directory)|projects/${UUID}/operations/[A-Za-z0-9_.:-]{1,128}|tasks/${UUID}(?:/summary|/artifacts/${UUID})?)$`);
const safeError = (status: number, detail: string) => NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });

/** Only known schema field names may leave a rejected request, never values or unknown keys. */
async function rejectedFormDetail(response: Response): Promise<string> {
  const fallback = "Cloud form was rejected. Check its fields and current authorization.";
  if (response.status !== 422) return fallback;
  try {
    const problem = await response.json();
    if (!Array.isArray(problem.detail)) return fallback;
    const fields = new Set("configuration sut framework environment url default_selector credential_version_id kind value checkout_strategy base_ref name connection host port user host_key network_requirements expected_deployment require_matching_deployment cloud_access_policy ssh_access title config_id inputs sut_selector framework_selector prd_markdown prd_version objective basic_flow test_scope expected_outputs framework_entrypoints authorization targets permitted_actions network_targets side_effect_limits expires_at budgets accounting_unit total_seconds total_cost_microunits max_attempts max_concurrency credential_id label purpose allowed_targets allowed_actions secret reason task_id attempt_id resolution_id question_id answer expected_version operation operation_key profile project_id reconciliation old_owner_fenced local_processes_stopped external_operations_reconciled checkpoint_verified observations".split(" "));
    const paths = problem.detail.slice(0, 8).map((issue: { loc?: unknown }) => Array.isArray(issue.loc)
      ? issue.loc.filter((part: unknown) => typeof part === "string" && fields.has(part)).join(".") : "").filter(Boolean);
    return paths.length ? `Cloud form was rejected. Check fields: ${[...new Set(paths)].join(", ")}.` : fallback;
  } catch { return fallback; }
}

async function operatorKey(): Promise<string | null> {
  if (process.env.HYPERTEST_CLOUD_WEB_ENABLED !== "true") return null;
  try {
    const value = process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE
      ? await readFile(process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE, "utf8")
      : process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY || "";
    const key = value.trim();
    return key && !/[\r\n]/.test(key) ? key : null;
  } catch { return null; }
}

/** The public site may differ from Next's internal listener behind a proxy. */
function trustedWebOrigin(request: NextRequest): string | null {
  const configured = process.env.HYPERTEST_CLOUD_WEB_ORIGIN;
  if (configured === undefined) return request.nextUrl.origin;
  try {
    const url = new URL(configured);
    if (!/^https?:$/.test(url.protocol) || !url.hostname || url.username || url.password || url.pathname !== "/" || url.search || url.hash
      || (configured !== url.origin && configured !== `${url.origin}/`)) return null;
    return url.origin;
  } catch { return null; }
}

async function upstream(path: string, key: string, init?: { method: "POST"; body: string }): Promise<Response> {
  return cloudServerRequest(path, key, init);
}

type Page = { profile: string; project_id: string; task_id: string; version: number; offset: number; next_offset: number; total_characters: number; complete: boolean; content: string; sha256: string };
async function completeArtifact(path: string, query: URLSearchParams, key: string): Promise<NextResponse> {
  const chunks: Buffer[] = []; let offset = 0, expectedHash: string | null = null, expectedSize: number | null = null;
  for (let count = 0; count < 130; count++) {
    const parameters = new URLSearchParams({ project_id: query.get("project_id") || "", offset: String(offset), length: "65536" });
    const response = await upstream(`cloud/${path}?${parameters}`, key);
    if (!response.ok) return safeError(response.status, "The original Cloud artifact could not be read.");
    const page = await response.json();
    expectedHash ??= page.sha256; expectedSize ??= page.byte_count;
    if (page.id !== path.split("/")[3] || page.task_id !== path.split("/")[1] || page.offset !== offset
      || page.sha256 !== expectedHash || page.byte_count !== expectedSize || typeof page.content_base64 !== "string"
      || !Number.isSafeInteger(expectedSize) || expectedSize! < 0 || expectedSize! > 8 * 1024 * 1024
      || typeof page.complete !== "boolean" || !/^[a-f0-9]{64}$/.test(page.sha256)) throw new Error("ARTIFACT_MISMATCH");
    const bytes = Buffer.from(page.content_base64, "base64"); chunks.push(bytes); offset += bytes.length;
    if (offset > expectedSize! || page.next_offset !== offset) throw new Error("ARTIFACT_GAP");
    if (page.complete) {
      const content = Buffer.concat(chunks);
      if (offset !== expectedSize || createHash("sha256").update(content).digest("hex") !== expectedHash) throw new Error("ARTIFACT_INCOMPLETE");
      return NextResponse.json({ content: new TextDecoder("utf-8", { fatal: true }).decode(content), filename: page.filename,
        sha256: expectedHash, byte_count: expectedSize }, { headers: { "Cache-Control": "no-store" } });
    }
    if (!bytes.length || page.next_offset !== offset) throw new Error("ARTIFACT_GAP");
  }
  throw new Error("ARTIFACT_LIMIT");
}
async function completeReadback(path: string, query: URLSearchParams, key: string): Promise<NextResponse> {
  const pieces: string[] = []; let offset = 0, version: number | null = query.has("version") ? Number(query.get("version")) : null;
  let total: number | null = null, expectedHash: string | null = null;
  for (let count = 0; count < 2000; count++) {
    const parameters = new URLSearchParams({ project_id: query.get("project_id") || "", offset: String(offset), limit: "24000" });
    if (version !== null) parameters.set("version", String(version));
    const response = await upstream(`cloud/${path}?${parameters}`, key);
    if (!response.ok) return safeError(response.status, "Cloud task readback was rejected. Refresh the task and check access.");
    const page = await response.json() as Page;
    version ??= page.version; total ??= page.total_characters; expectedHash ??= page.sha256;
    if (page.profile !== "cloud-harness-task/v1alpha1" || page.project_id !== query.get("project_id")
      || page.task_id !== path.split("/")[1] || page.version !== version || page.offset !== offset
      || page.total_characters !== total || !Number.isSafeInteger(total) || total < 0 || total > 32 * 1024 * 1024
      || page.sha256 !== expectedHash || typeof page.content !== "string" || typeof page.complete !== "boolean"
      || !Number.isSafeInteger(version) || version! < 1 || !/^[a-f0-9]{64}$/.test(page.sha256)) throw new Error("READBACK_MISMATCH");
    pieces.push(page.content); offset += [...page.content].length;
    if (offset > total || page.next_offset !== offset) throw new Error("READBACK_GAP");
    if (page.complete) {
      const content = pieces.join("");
      if (offset !== total || createHash("sha256").update(content).digest("hex") !== expectedHash) throw new Error("READBACK_INCOMPLETE");
      const document = JSON.parse(content);
      if (document.task?.id !== page.task_id || document.task?.project_id !== page.project_id || document.task?.version !== version) throw new Error("READBACK_TARGET");
      return NextResponse.json(document, { headers: { "Cache-Control": "no-store" } });
    }
    if (!page.content || page.next_offset !== offset) throw new Error("READBACK_GAP");
  }
  throw new Error("READBACK_LIMIT");
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  const key = await operatorKey();
  if (path === "setup") return NextResponse.json({ configured: key !== null && await cloudServerTransportReady() }, { headers: { "Cache-Control": "no-store" } });
  if (!key) return safeError(503, "Cloud Web access is not configured. Ask the deployment operator to enable it.");
  if (!GET_PATH.test(path)) return safeError(404, "Cloud route not found.");
  const query = new URLSearchParams(request.nextUrl.searchParams);
  if (query.has("project_id") && !new RegExp(`^${UUID}$`).test(query.get("project_id") || "")) return safeError(400, "Invalid Project identity.");
  try {
    if (query.get("readback") === "complete" && new RegExp(`^tasks/${UUID}$`).test(path)) return await completeReadback(path, query, key);
    if (query.get("readback") === "complete" && new RegExp(`^tasks/${UUID}/artifacts/${UUID}$`).test(path)) return await completeArtifact(path, query, key);
    query.delete("readback");
    const target = path.endsWith("/task-directory") ? path : `cloud/${path}`;
    const response = await upstream(`${target}?${query}`, key);
    if (!response.ok) return safeError(response.status, "Cloud records could not be read. Refresh and check access.");
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return safeError(502, "Cloud readback could not be verified. Previously loaded records remain available."); }
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if ((await context.params).path.join("/") !== "operations") return safeError(404, "Cloud route not found.");
  const expectedOrigin = trustedWebOrigin(request);
  if (!expectedOrigin) return safeError(503, "Cloud Web canonical origin is invalid. Ask the deployment operator to correct it.");
  const origin = request.headers.get("origin");
  if (!origin) return safeError(403, "A Cloud form Origin header is required.");
  if (origin !== expectedOrigin || request.headers.get("sec-fetch-site") === "cross-site") return safeError(403, "A same-origin Cloud form is required.");
  const key = await operatorKey();
  if (!key) return safeError(503, "Cloud Web access is not configured.");
  if (!request.headers.get("content-type")?.startsWith("application/json")) return safeError(415, "Cloud forms require JSON.");
  if (Number(request.headers.get("content-length")) > 12 * 1024 * 1024) return safeError(413, "Cloud form exceeds its size limit.");
  try {
    const body = await request.text();
    if (Buffer.byteLength(body) > 12 * 1024 * 1024) return safeError(413, "Cloud form exceeds its size limit.");
    const response = await upstream("cloud/operations", key, { method: "POST", body });
    if (!response.ok) return safeError(response.status, response.status === 409
      ? "Cloud state changed. Your form is preserved; refresh the accepted version before a new submission."
      : response.status >= 500 ? "Cloud submission is uncertain. Query the original operation key; do not submit again."
      : await rejectedFormDetail(response));
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch { return safeError(502, "Cloud submission is uncertain. Query the original operation key; do not submit again."); }
}
