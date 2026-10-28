/** Server-only Local archive boundary; no credential is serialized to the browser. */
import { readFile } from "node:fs/promises";
import { NextRequest, NextResponse } from "next/server";
import { trustedServerRequest, cloudServerTransportReady } from "@/lib/cloud-server-auth";

const UUID = "[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}";
const archiveGet = new RegExp(`^(?:capabilities|actors|tasks|operations/by-key|tasks/${UUID}(?:/(?:archive|subtasks/${UUID}/archive))?|submissions/${UUID})$`);
const archivePost = new RegExp(`^(?:tasks|tasks/${UUID}/(?:subtasks|authorize|update|publications))$`);
const authGet = new RegExp(`^(?:grants|requests/by-key|requests/${UUID}|grants/${UUID}/operations/by-key)$`);
const authPost = new RegExp(`^(?:requests/${UUID}/approve|grants/${UUID}/revoke)$`);
const json = (value: unknown, status = 200) => NextResponse.json(value, { status, headers: { "Cache-Control": "no-store" } });
const failure = (status: number, detail: string) => json({ detail }, status);
async function key() {
  if (process.env.HYPERTEST_ARCHIVE_WEB_ENABLED !== "true") return null;
  try {
    const file = process.env.HYPERTEST_ARCHIVE_WEB_OPERATOR_KEY_FILE;
    if (!file) return null;
    const value = (await readFile(file, "utf8")).trim();
    return value && !/[\r\n]/.test(value) ? value : null;
  } catch { return null; }
}
function origin(request: NextRequest) {
  const configured = process.env.HYPERTEST_ARCHIVE_WEB_ORIGIN;
  if (!configured) return null;
  try {
    const value = new URL(configured);
    return /^https?:$/.test(value.protocol) && value.hostname && !value.username && !value.password && value.pathname === "/" && !value.search && !value.hash
      && (configured === value.origin || configured === `${value.origin}/`) ? value.origin : null;
  } catch { return null; }
}
/** Optional deployment-configured HTTPS origin of the CLI API. Public context, never a credential. */
function cliOrigin() {
  const configured = process.env.HYPERTEST_CLI_SERVER_ORIGIN;
  if (!configured) return null;
  try {
    const value = new URL(configured);
    return value.protocol === "https:" && value.hostname && !value.username && !value.password && value.pathname === "/" && !value.search && !value.hash
      && (configured === value.origin || configured === `${value.origin}/`) ? value.origin : null;
  } catch { return null; }
}
async function safeFailure(response: Response) {
  let detail: unknown;
  try { detail = (await response.json()).detail; } catch { /* Never forward uncontrolled upstream text. */ }
  const code = typeof detail === "string" && /^(?:ARCHIVE|CLI)_[A-Z0-9_]+$/.test(detail) ? detail
    : response.status >= 500 ? "ARCHIVE_ORIGINAL_KEY_REQUIRED" : "ARCHIVE_REQUEST_REJECTED";
  return failure(response.status, code);
}
async function fullSnapshot(path: string, query: URLSearchParams, operator: string) {
  const parts: string[] = []; let offset = 0, total: number | undefined, identity = "";
  const expectedTask = path.startsWith("tasks/") ? path.split("/")[1] : undefined;
  const expectedChild = path.includes("/subtasks/") ? path.split("/")[3] : null;
  for (let pageIndex = 0; pageIndex < 1500; pageIndex++) {
    query.set("offset", String(offset)); query.set("limit", "24000");
    const response = await trustedServerRequest(`local-archive/${path}?${query}`, operator, undefined, "archive");
    if (!response.ok) return safeFailure(response);
    const page = await response.json();
    const currentIdentity = JSON.stringify([page.profile, page.submission_id, page.project_id, page.task_id, page.target_kind, page.subtask_id, page.archive_version]);
    if (!identity) { identity = currentIdentity; total = page.total_chars; }
    if (currentIdentity !== identity || page.profile !== "local-artifact-archive/v1alpha1" || page.project_id !== query.get("project_id")
      || (expectedTask && (page.task_id !== expectedTask || page.subtask_id !== expectedChild))
      || (!expectedTask && page.submission_id !== path.split("/")[1])
      || (query.has("archive_version") && page.archive_version !== Number(query.get("archive_version")))
      || page.offset !== offset || page.total_chars !== total || !Number.isSafeInteger(total) || total! < 0 || total! > 32 * 1024 * 1024
      || typeof page.content !== "string" || typeof page.complete !== "boolean") throw new Error("ARCHIVE_READBACK_MISMATCH");
    parts.push(page.content); offset += [...page.content].length;
    if (offset > total! || (page.complete ? page.next_offset !== null : page.next_offset !== offset)) throw new Error("ARCHIVE_READBACK_MISMATCH");
    if (page.complete) {
      if (offset !== total) throw new Error("ARCHIVE_READBACK_INCOMPLETE");
      const document = JSON.parse(parts.join(""));
      if (document.profile !== page.profile || document.project_id !== page.project_id || document.task_id !== page.task_id || document.subtask_id !== page.subtask_id
        || document.target_kind !== page.target_kind || document.archive_version !== page.archive_version || !Array.isArray(document.assets)) throw new Error("ARCHIVE_READBACK_MISMATCH");
      return json(document);
    }
    if (!page.content) throw new Error("ARCHIVE_READBACK_INCOMPLETE");
  }
  throw new Error("ARCHIVE_READBACK_INCOMPLETE");
}
export async function localBoundary(request: NextRequest, path: string, domain: "archive" | "cli-authorization", method: "GET" | "POST") {
  const operator = await key();
  if (method === "GET" && path === "setup") {
    const configured = operator !== null && await cloudServerTransportReady();
    const cli = configured && domain === "cli-authorization" ? cliOrigin() : null;
    return json(cli ? { configured, cli_server_origin: cli } : { configured });
  }
  if (!(method === "GET" ? domain === "archive" ? archiveGet : authGet : domain === "archive" ? archivePost : authPost).test(path)) return failure(404, "ARCHIVE_ROUTE_NOT_FOUND");
  if (!operator) return failure(503, "ARCHIVE_WEB_UNAVAILABLE");
  const prefix = domain === "archive" ? "local-archive" : "cli-authorizations";
  try {
    if (method === "POST") {
      const expectedOrigin = origin(request);
      if (!expectedOrigin) return failure(503, "ARCHIVE_WEB_UNAVAILABLE");
      if (request.headers.get("origin") !== expectedOrigin || request.headers.get("sec-fetch-site") === "cross-site") return failure(403, "ARCHIVE_ORIGIN_REQUIRED");
      if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json") return failure(415, "ARCHIVE_JSON_REQUIRED");
      if (Number(request.headers.get("content-length")) > 2 * 1024 * 1024) return failure(413, "ARCHIVE_REQUEST_TOO_LARGE");
      const body = await request.text();
      if (Buffer.byteLength(body) > 2 * 1024 * 1024) return failure(413, "ARCHIVE_REQUEST_TOO_LARGE");
      try { JSON.parse(body); } catch { return failure(400, "ARCHIVE_JSON_REQUIRED"); }
      const response = await trustedServerRequest(`${prefix}/${path}`, operator, { method, body }, domain);
      return response.ok ? json(await response.json()) : safeFailure(response);
    }
    const query = new URLSearchParams(request.nextUrl.searchParams);
    const allowed = domain === "archive" ? ["project_id", "offset", "limit", "archive_version", "idempotency_key", "readback"] : ["request_id", "operation", "idempotency_key"];
    if ([...query.keys()].some((name) => !allowed.includes(name) || query.getAll(name).length !== 1)
      || ["project_id", "request_id"].some((name) => query.has(name) && !new RegExp(`^${UUID}$`).test(query.get(name)!))
      || ["offset", "limit", "archive_version"].some((name) => query.has(name) && !/^\d{1,9}$/.test(query.get(name)!))
      || (query.has("idempotency_key") && !/^[A-Za-z0-9_.:-]{1,128}$/.test(query.get("idempotency_key")!))
      || (query.has("operation") && !["APPROVE", "REVOKE"].includes(query.get("operation")!))) return failure(400, "ARCHIVE_QUERY_INVALID");
    const complete = query.get("readback") === "complete"; query.delete("readback");
    if (domain === "archive" && complete && (path.endsWith("/archive") || path.startsWith("submissions/"))) return await fullSnapshot(path, query, operator);
    const response = await trustedServerRequest(`${prefix}/${path}?${query}`, operator, undefined, domain);
    return response.ok ? json(await response.json()) : safeFailure(response);
  } catch { return failure(502, method === "POST" ? "ARCHIVE_ORIGINAL_KEY_REQUIRED" : "ARCHIVE_READBACK_UNAVAILABLE"); }
}
