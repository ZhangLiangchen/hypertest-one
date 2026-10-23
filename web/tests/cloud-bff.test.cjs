const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const test = require("node:test");
const load = require("./load-helper.cjs");
const { NextRequest } = require("next/server");

const project = "00000000-0000-4000-8000-000000000001";
const task = "00000000-0000-4000-8000-000000000002";
const canary = "synthetic-server-only-operator-key";
function moduleFor(fetch, enabled = true, cloudOrigin, webOrigin, transportReady = true) {
  return load("app/api/cloud/[...path]/route.ts", {
    require: (name) => {
      if (name === "next/server") return { NextResponse: { json: (value, init) => new Response(JSON.stringify(value), init) } };
      if (name === "@/lib/cloud-server-auth") return {
        cloudServerTransportReady: async () => transportReady,
        cloudServerRequest: async (path, key, init) => {
          if (!transportReady) throw new Error(canary);
          return fetch(`${cloudOrigin || "https://cloud-api.example.invalid"}/api/v1/${path}`, {
            ...init, headers: { "X-Hypertest-Operator-Key": key },
          });
        },
      };
      return require(name);
    },
    process: { env: { HYPERTEST_CLOUD_WEB_ENABLED: enabled ? "true" : "false", HYPERTEST_CLOUD_WEB_OPERATOR_KEY: canary, HYPERTEST_API_ORIGIN: "http://isolated-api", HYPERTEST_CLOUD_API_ORIGIN: cloudOrigin, HYPERTEST_CLOUD_WEB_ORIGIN: webOrigin } },
    fetch, Buffer, AbortSignal, TextDecoder, URLSearchParams, URL,
  });
}
const context = (...path) => ({ params: Promise.resolve({ path }) });
const request = (url, options = {}) => {
  const value = new Request(url, options); value.nextUrl = new URL(url); return value;
};

test("Cloud Web is explicitly disabled without exposing any server credential", async () => {
  let calls = 0;
  const routes = moduleFor(async () => { calls++; throw new Error("must not connect"); }, false);
  const response = await routes.GET(request("http://web/api/cloud/setup"), context("setup"));
  assert.deepEqual(await response.json(), { configured: false });
  const blocked = await routes.GET(request("http://web/api/cloud/capabilities"), context("capabilities"));
  assert.equal(blocked.status, 503);
  assert.equal((await blocked.text()).includes(canary), false);
  assert.equal(calls, 0);
});

test("Cloud BFF forwards only declared paths and requires same-origin JSON mutations", async () => {
  const calls = [];
  const routes = moduleFor(async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ status: "ACCEPTED" })); });
  assert.equal((await routes.GET(request("http://web/api/cloud/admin"), context("admin"))).status, 404);
  assert.equal((await routes.POST(request("http://web/api/cloud/operations", { method: "POST", headers: { origin: "http://other-site", "content-type": "application/json" }, body: "{}" }), context("operations"))).status, 403);
  assert.equal(calls.length, 0);
  const response = await routes.POST(request("http://web/api/cloud/operations", { method: "POST", headers: { origin: "http://web", "content-type": "application/json" }, body: JSON.stringify({ operation: "CONFIGURE", operation_key: "original" }) }), context("operations"));
  assert.equal(response.status, 200);
  assert.equal(calls[0].url, "https://cloud-api.example.invalid/api/v1/cloud/operations");
  assert.equal(calls[0].options.headers["X-Hypertest-Operator-Key"], canary);
  assert.equal((await response.text()).includes(canary), false);
});

test("Real NextRequest accepts only the configured public origin when its listener URL is internal", async () => {
  const calls = [];
  const publicOrigin = "https://workbench.example.invalid";
  const routes = moduleFor(async (url, options) => { calls.push({ url, options }); return new Response(JSON.stringify({ status: "ACCEPTED" })); }, true, undefined, publicOrigin);
  const form = (origin, extra = {}) => new NextRequest("http://localhost:3000/api/cloud/operations", {
    method: "POST", headers: { "content-type": "application/json", host: "internal-listener:3000", ...(origin ? { origin } : {}), ...extra }, body: "{}",
  });
  const internal = form(publicOrigin, { "sec-fetch-site": "same-origin", "x-forwarded-host": "untrusted.invalid", "x-forwarded-proto": "http" });
  assert.equal(internal.nextUrl.origin, "http://localhost:3000");
  assert.equal((await routes.POST(internal, context("operations"))).status, 200);
  assert.equal(calls.length, 1);
  assert.equal((await routes.POST(form("https://other.example.invalid", { "x-forwarded-host": "workbench.example.invalid" }), context("operations"))).status, 403);
  assert.equal((await routes.POST(form(publicOrigin, { "sec-fetch-site": "cross-site" }), context("operations"))).status, 403);
  const absent = await routes.POST(form(undefined, { referer: `${publicOrigin}/projects/example/cloud` }), context("operations"));
  assert.equal(absent.status, 403);
  assert.ok((await absent.text()).includes("Origin header is required"));
  assert.equal(calls.length, 1);
});

test("Canonical origin configuration fails closed and forwarded headers cannot establish trust", async () => {
  let calls = 0;
  const fetch = async () => { calls++; return new Response("{}"); };
  for (const value of ["", "ftp://web.example.invalid", "https://user:password@web.example.invalid", "https://web.example.invalid/path", "https://web.example.invalid?query=value", "https://web.example.invalid/#fragment", " https://web.example.invalid", "https://web.example.invalid\n"]) {
    const routes = moduleFor(fetch, true, undefined, value);
    const response = await routes.POST(new NextRequest("http://localhost:3000/api/cloud/operations", { method: "POST", headers: { origin: "https://web.example.invalid", "content-type": "application/json" }, body: "{}" }), context("operations"));
    assert.equal(response.status, 503, value);
  }
  const direct = moduleFor(fetch);
  const headers = { origin: "https://web.example.invalid", "content-type": "application/json", "x-forwarded-host": "web.example.invalid", "x-forwarded-proto": "https" };
  assert.equal((await direct.POST(new NextRequest("http://localhost:3000/api/cloud/operations", { method: "POST", headers, body: "{}" }), context("operations"))).status, 403);
  assert.equal(calls, 0);
  headers.origin = "http://localhost:3000";
  assert.equal((await direct.POST(new NextRequest("http://localhost:3000/api/cloud/operations", { method: "POST", headers, body: "{}" }), context("operations"))).status, 200);
  assert.equal(calls, 1);
});

test("A lost Cloud submission returns uncertainty without an automatic retry or raw error", async () => {
  let calls = 0;
  const routes = moduleFor(async () => { calls++; throw new Error(canary); });
  const response = await routes.POST(request("http://web/api/cloud/operations", { method: "POST", headers: { origin: "http://web", "content-type": "application/json" }, body: "{}" }), context("operations"));
  const content = await response.text();
  assert.equal(response.status, 502);
  assert.equal(calls, 1);
  assert.equal(content.includes(canary), false);
  assert.ok(content.includes("original operation key"));
});

test("Cloud may use its own trusted HTTPS origin without changing legacy API rewrites", async () => {
  const calls = [];
  const routes = moduleFor(async (url) => { calls.push(url); return new Response(JSON.stringify({ enabled: false })); }, true, "https://cloud-api.example.invalid");
  const response = await routes.GET(request("http://web/api/cloud/capabilities"), context("capabilities"));
  assert.equal(response.status, 200);
  assert.equal(calls[0], "https://cloud-api.example.invalid/api/v1/cloud/capabilities?");
});

test("Cloud setup requires the HTTPS transport and its failure keeps the original write uncertain", async () => {
  let calls = 0;
  const routes = moduleFor(async () => { calls++; return new Response("{}"); }, true, undefined, undefined, false);
  assert.deepEqual(await (await routes.GET(request("http://web/api/cloud/setup"), context("setup"))).json(), { configured: false });
  const response = await routes.POST(request("http://web/api/cloud/operations", {
    method: "POST", headers: { origin: "http://web", "content-type": "application/json" },
    body: JSON.stringify({ operation: "STORE_CREDENTIAL", operation_key: "original", secret: "synthetic-private-value" }),
  }), context("operations"));
  const content = await response.text();
  assert.equal(response.status, 502);
  assert.ok(content.includes("original operation key"));
  assert.equal(content.includes(canary), false);
  assert.equal(content.includes("synthetic-private-value"), false);
  assert.equal(calls, 0);
});

test("Fixed-version task readback counts unicode code points, pins continuation and verifies SHA", async () => {
  const document = { task: { id: task, project_id: project, version: 7, title: "🧪 原始测试报告" }, assets: [{ markdown: "FAIL\nPreserved original report\n".repeat(5) }] };
  const original = JSON.stringify(document), characters = [...original], split = 110;
  const sha256 = createHash("sha256").update(original).digest("hex");
  const calls = [];
  const routes = moduleFor(async (url) => {
    calls.push(url); const parsed = new URL(url), offset = Number(parsed.searchParams.get("offset"));
    const end = offset === 0 ? split : characters.length;
    return new Response(JSON.stringify({ profile: "cloud-harness-task/v1alpha1", project_id: project, task_id: task,
      version: 7, offset, next_offset: end, total_characters: characters.length, complete: end === characters.length,
      content: characters.slice(offset, end).join(""), sha256 }));
  });
  const response = await routes.GET(request(`http://web/api/cloud/tasks/${task}?project_id=${project}&readback=complete`), context("tasks", task));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), document);
  assert.equal(calls.length, 2);
  assert.equal(new URL(calls[1]).searchParams.get("version"), "7");
  assert.equal(new URL(calls[1]).searchParams.get("offset"), String(split));
});

test("Readback version drift and tampered originals are rejected instead of presented as synced", async () => {
  const routes = moduleFor(async () => new Response(JSON.stringify({ profile: "cloud-harness-task/v1alpha1", project_id: project, task_id: task,
    version: 9, offset: 0, next_offset: 2, total_characters: 2, complete: true, content: "{}", sha256: "a".repeat(64) })));
  const response = await routes.GET(request(`http://web/api/cloud/tasks/${task}?project_id=${project}&readback=complete&version=8`), context("tasks", task));
  assert.equal(response.status, 502);
  assert.ok((await response.text()).includes("could not be verified"));
});

test("Original artifact readback verifies every byte across chunk boundaries", async () => {
  const artifact = "00000000-0000-4000-8000-000000000003";
  const original = Buffer.from("原始报告 🧪\nFAIL survives\n");
  const sha256 = createHash("sha256").update(original).digest("hex"), offsets = [];
  const routes = moduleFor(async (url) => {
    const parsed = new URL(url), offset = Number(parsed.searchParams.get("offset")); offsets.push(offset);
    const end = offset === 0 ? 7 : original.length;
    return new Response(JSON.stringify({ id: artifact, task_id: task, filename: "original.txt", byte_count: original.length, sha256,
      offset, next_offset: end, complete: end === original.length, content_base64: original.subarray(offset, end).toString("base64") }));
  });
  const response = await routes.GET(request(`http://web/api/cloud/tasks/${task}/artifacts/${artifact}?project_id=${project}&readback=complete`), context("tasks", task, "artifacts", artifact));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).content, original.toString("utf8"));
  assert.deepEqual(offsets, [0, 7]);
});

test("A final readback page still requires a boolean terminal and an exact continuation offset", async () => {
  const document = { task: { id: task, project_id: project, version: 1 } }, content = JSON.stringify(document);
  const page = { profile: "cloud-harness-task/v1alpha1", project_id: project, task_id: task, version: 1,
    offset: 0, next_offset: content.length, total_characters: content.length, complete: true, content, sha256: createHash("sha256").update(content).digest("hex") };
  for (const change of [{ complete: "false" }, { next_offset: content.length + 1 }, { version: "1" }]) {
    const routes = moduleFor(async () => new Response(JSON.stringify({ ...page, ...change })));
    const response = await routes.GET(request(`http://web/api/cloud/tasks/${task}?project_id=${project}&readback=complete`), context("tasks", task));
    assert.equal(response.status, 502);
  }
});

test("Rejected forms expose known invalid field names but never input, context, messages or arbitrary keys", async () => {
  const routes = moduleFor(async () => new Response(JSON.stringify({ detail: [
    { loc: ["body", "CREATE_TASK", "inputs", "prd_markdown"], msg: canary, input: canary, ctx: { secret: canary } },
    { loc: ["body", canary], msg: canary },
  ] }), { status: 422 }));
  const response = await routes.POST(request("http://web/api/cloud/operations", { method: "POST", headers: { origin: "http://web", "content-type": "application/json" }, body: "{}" }), context("operations"));
  const content = await response.text();
  assert.equal(response.status, 422);
  assert.ok(content.includes("inputs.prd_markdown"));
  assert.equal(content.includes(canary), false);
});
