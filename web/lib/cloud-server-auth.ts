/** Server-only authenticated HTTPS over the explicitly configured Unix socket. */
import { readFile } from "node:fs/promises";
import { request as httpsRequest } from "node:https";
import { isIP } from "node:net";
import { isAbsolute, normalize } from "node:path";
import { checkServerIdentity } from "node:tls";

const TIMEOUT_MS = 30_000;
const MAX_RESPONSE_BYTES = 32 * 1024 * 1024;
const unavailable = () => new Error("CLOUD_SERVER_TRANSPORT_UNAVAILABLE");

function absolutePath(value: string | undefined, limit: number): string {
  if (!value || !isAbsolute(value) || normalize(value) !== value || value.length > limit || /[\0\r\n]/.test(value)) throw unavailable();
  return value;
}

async function transport() {
  const configured = process.env.HYPERTEST_CLOUD_API_ORIGIN;
  if (!configured) throw unavailable();
  const url = new URL(configured);
  if (url.protocol !== "https:" || !url.hostname || url.username || url.password
    || url.pathname !== "/" || url.search || url.hash
    || (configured !== url.origin && configured !== `${url.origin}/`)) throw unavailable();
  const socketPath = absolutePath(process.env.HYPERTEST_CLOUD_API_SOCKET, 107);
  const caFile = absolutePath(process.env.HYPERTEST_CLOUD_API_CA_FILE, 4096);
  const ca = await readFile(caFile);
  if (!ca.length || ca.length > 1024 * 1024 || !ca.includes("-----BEGIN CERTIFICATE-----")) throw unavailable();
  const hostname = url.hostname.replace(/^\[|\]$/g, "");
  return { socketPath, ca, hostname, host: url.host, port: Number(url.port) || 443 };
}

/** Setup exposes readiness only, never the key, CA, socket or internal API origin. */
export async function cloudServerTransportReady(): Promise<boolean> {
  try { await transport(); return true; } catch { return false; }
}

export async function trustedServerRequest(path: string, key: string, init: { method?: "GET" | "POST"; body?: string } | undefined, domain: "cloud" | "memory" | "archive" | "cli-authorization"): Promise<Response> {
  try {
    const settings = await transport();
    const allowedPath = domain === "memory" ? /^memory\// : domain === "archive" ? /^local-archive\// : domain === "cli-authorization" ? /^cli-authorizations\// : /^(?:cloud|projects)\//;
    if (!key || /[\r\n]/.test(key) || !allowedPath.test(path) || path.includes("\\") || /[\0\r\n#]/.test(path)
      || path.split("?")[0].split("/").some((part) => part === "." || part === "..")
      || (init?.body !== undefined && (init.method !== "POST" || Buffer.byteLength(init.body) > 12 * 1024 * 1024))) throw unavailable();

    return await new Promise<Response>((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      let request: ReturnType<typeof httpsRequest> | undefined;
      const fail = () => {
        if (settled) return;
        settled = true; clearTimeout(timer);
        request?.destroy();
        reject(unavailable());
      };
      request = httpsRequest({
        protocol: "https:", hostname: settings.hostname, port: settings.port, socketPath: settings.socketPath,
        servername: isIP(settings.hostname) ? "" : settings.hostname,
        ca: settings.ca, rejectUnauthorized: true, minVersion: "TLSv1.2", agent: false,
        checkServerIdentity: (_hostname, certificate) => checkServerIdentity(settings.hostname, certificate),
        method: init?.method || "GET", path: `/api/v1/${path}`,
        headers: { Host: settings.host, "Content-Type": "application/json", "X-Hypertest-Operator-Key": key },
      }, (response) => {
        const status = response.statusCode;
        if (!status || status < 200 || status > 599 || (status >= 300 && status < 400)) { fail(); response.destroy(); return; }
        const chunks: Buffer[] = []; let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) { fail(); response.destroy(); return; }
          chunks.push(chunk);
        });
        response.once("aborted", fail);
        response.once("error", fail);
        response.once("end", () => {
          if (settled) return;
          if (!response.complete) { fail(); return; }
          try {
            const body = status === 204 || status === 205 ? null : new Uint8Array(Buffer.concat(chunks));
            const result = new Response(body, { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
            settled = true; clearTimeout(timer); resolve(result);
          } catch { fail(); }
        });
      });
      request.once("error", fail);
      timer = setTimeout(fail, TIMEOUT_MS);
      request.end(init?.body);
    });
  } catch { throw unavailable(); }
}

export function cloudServerRequest(path: string, key: string, init?: { method?: "GET" | "POST"; body?: string }): Promise<Response> {
  return trustedServerRequest(path, key, init, "cloud");
}
