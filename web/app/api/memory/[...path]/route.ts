/** Optional Memory boundary. PowerContext is reached only by the API Gateway. */
import { readFile } from "node:fs/promises";
import { NextRequest, NextResponse } from "next/server";
import { memoryServerRequest, memoryServerTransportReady } from "@/lib/memory-server-auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const UUID = "[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}";
const getPath = new RegExp(`^(?:projects/${UUID}(?:/configuration)?|entries/${UUID}|operations/by-key)$`);
const safe = (status: number, code: string) => NextResponse.json({ code }, { status, headers: { "Cache-Control": "no-store" } });
const json = (value: unknown) => NextResponse.json(value, { headers: { "Cache-Control": "no-store" } });
async function operatorKey() {
  if (process.env.HYPERTEST_MEMORY_WEB_ENABLED !== "true") return null;
  try {
    const value = process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE
      ? await readFile(process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY_FILE, "utf8") : process.env.HYPERTEST_CLOUD_WEB_OPERATOR_KEY || "";
    const key = value.trim(); return key && !/[\r\n]/.test(key) ? key : null;
  } catch { return null; }
}
function webOrigin(request: NextRequest): string | null {
  const configured = process.env.HYPERTEST_CLOUD_WEB_ORIGIN;
  if (configured === undefined) return request.nextUrl.origin;
  try {
    const value = new URL(configured);
    return /^https?:$/.test(value.protocol) && value.hostname && !value.username && !value.password && value.pathname === "/" && !value.search && !value.hash
      && (configured === value.origin || configured === `${value.origin}/`) ? value.origin : null;
  } catch { return null; }
}
async function failure(response: Response) {
  if (response.status === 409) {
    let detail: unknown; try { detail = (await response.json()).detail; } catch { /* Safe fallback below. */ }
    if (typeof detail === "string" && /operation key.*conflict/i.test(detail)) return safe(409, "MEMORY_OPERATION_KEY_CONFLICT");
    return safe(409, "MEMORY_PRECONDITION_REQUIRED");
  }
  return safe(response.status, [400, 401, 403, 404, 422].includes(response.status) ? "MEMORY_REQUEST_REJECTED" : "MEMORY_UNAVAILABLE");
}
export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/"); const key = await operatorKey();
  if (path === "setup") return json({ configured: key !== null && await memoryServerTransportReady() });
  if (!key) return safe(503, "MEMORY_WEB_UNAVAILABLE");
  if (!getPath.test(path)) return safe(404, "MEMORY_ROUTE_NOT_FOUND");
  const query = new URLSearchParams(request.nextUrl.searchParams);
  const allowed = path === "operations/by-key" ? ["project_id", "operation_key"] : path.startsWith("entries/") ? ["project_id", "version"] : path.endsWith("/configuration") ? ["version"] : ["offset", "limit", "status"];
  if ([...query.keys()].some((field) => !allowed.includes(field)) || [...new Set(query.keys())].some((field) => query.getAll(field).length !== 1)
    || (query.has("project_id") && !new RegExp(`^${UUID}$`).test(query.get("project_id") || ""))
    || (query.has("offset") && !/^(?:0|[1-9][0-9]{0,8})$/.test(query.get("offset") || ""))
    || (query.has("limit") && (!/^[1-9][0-9]{0,2}$/.test(query.get("limit") || "") || Number(query.get("limit")) > 100))
    || (query.has("status") && !["CANDIDATE", "PUBLISHED", "RETRACTED"].includes(query.get("status") || ""))
    || (query.has("version") && !/^[1-9][0-9]{0,8}$/.test(query.get("version") || ""))
    || (path === "operations/by-key" && (!query.has("project_id") || !/^[A-Za-z0-9_.:-]{1,128}$/.test(query.get("operation_key") || "")))
    || (path.startsWith("entries/") && (!query.has("project_id") || !query.has("version")))) return safe(400, "MEMORY_QUERY_INVALID");
  try {
    const response = await memoryServerRequest(`memory/${path}?${query}`, key);
    return response.ok ? json(await response.json()) : failure(response);
  } catch { return safe(502, "MEMORY_UNAVAILABLE"); }
}
export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const path = (await context.params).path.join("/");
  if (!["operations", "query"].includes(path)) return safe(404, "MEMORY_ROUTE_NOT_FOUND");
  const origin = webOrigin(request);
  if (!origin) return safe(503, "MEMORY_WEB_UNAVAILABLE");
  if (request.headers.get("origin") !== origin || request.headers.get("sec-fetch-site") === "cross-site") return safe(403, "MEMORY_ORIGIN_REQUIRED");
  if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") return safe(415, "MEMORY_JSON_REQUIRED");
  const key = await operatorKey(); if (!key) return safe(503, "MEMORY_WEB_UNAVAILABLE");
  try {
    const body = await request.text(); if (Buffer.byteLength(body) > 128 * 1024) return safe(413, "MEMORY_REQUEST_TOO_LARGE");
    try { JSON.parse(body); } catch { return safe(400, "MEMORY_JSON_REQUIRED"); }
    const response = await memoryServerRequest(`memory/${path}`, key, { method: "POST", body });
    return response.ok ? json(await response.json()) : failure(response);
  } catch { return safe(502, path === "operations" ? "MEMORY_ORIGINAL_KEY_REQUIRED" : "MEMORY_UNAVAILABLE"); }
}
