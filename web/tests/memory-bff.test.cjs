const assert = require("node:assert/strict");
const test = require("node:test");
const { NextRequest } = require("next/server");
const load = require("./load-helper.cjs");
const project = "00000000-0000-4000-8000-000000000001", entry = "00000000-0000-4000-8000-000000000002";
const secret = "synthetic-operator-key", privateText = "synthetic-private-experience";
function routes(upstream, enabled = true, origin = "https://workbench.example.invalid") {
  return load("app/api/memory/[...path]/route.ts", { Buffer, URL, URLSearchParams,
    process: { env: { HYPERTEST_MEMORY_WEB_ENABLED: String(enabled), HYPERTEST_CLOUD_WEB_OPERATOR_KEY: secret, HYPERTEST_CLOUD_WEB_ORIGIN: origin } },
    require: (name) => name === "next/server" ? { NextResponse: { json: (value, init) => new Response(JSON.stringify(value), init) } }
      : name === "@/lib/memory-server-auth" ? { memoryServerRequest: upstream, memoryServerTransportReady: async () => true } : require(name),
  });
}
const context = (...path) => ({ params: Promise.resolve({ path }) });
const request = (path, init = {}) => new NextRequest(`http://localhost:3000/api/memory/${path}`, init);
const mutation = (body, origin = "https://workbench.example.invalid") => request("operations", { method: "POST", headers: { origin, "content-type": "application/json" }, body: JSON.stringify(body) });

test("Memory Web has an independent explicit switch and exposes no server secrets", async () => {
  let calls = 0; const api = routes(async () => { calls++; }, false);
  assert.deepEqual(await (await api.GET(request("setup"), context("setup"))).json(), { configured: false });
  const response = await api.GET(request(`projects/${project}`), context("projects", project));
  assert.equal(response.status, 503); assert.equal((await response.text()).includes(secret), false); assert.equal(calls, 0);
});

test("Memory BFF accepts only declared paths, original-key queries and explicit fixed revisions", async () => {
  const calls = []; const api = routes(async (...args) => { calls.push(args); return new Response("{}"); });
  assert.equal((await api.GET(request("admin"), context("admin"))).status, 404);
  assert.equal((await api.GET(request(`entries/${entry}?project_id=${project}`), context("entries", entry))).status, 400);
  assert.equal((await api.GET(request(`operations/by-key?project_id=${project}&operation_key=original&operation_key=replaced`), context("operations", "by-key"))).status, 400);
  const read = await api.GET(request(`entries/${entry}?project_id=${project}&version=2`), context("entries", entry));
  assert.equal(read.status, 200); assert.equal(calls[0][0], `memory/entries/${entry}?project_id=${project}&version=2`); assert.equal(calls[0][1], secret);
  assert.equal((await read.text()).includes(secret), false);
});

test("Memory same-origin mutations use only the server Operator key and never PowerContext admin credentials", async () => {
  const calls = []; const api = routes(async (...args) => { calls.push(args); return new Response(JSON.stringify({ status: "ACCEPTED" })); });
  assert.equal((await api.POST(mutation({}, "https://other.invalid"), context("operations"))).status, 403);
  assert.equal(calls.length, 0);
  const body = { operation: "PUBLISH", project_id: project, operation_key: "original", content: privateText };
  assert.equal((await api.POST(mutation(body), context("operations"))).status, 200);
  assert.equal(calls[0][0], "memory/operations"); assert.equal(calls[0][1], secret); assert.equal(calls[0][2].body, JSON.stringify(body));
  const badOrigin = routes(async () => { throw new Error("must not connect"); }, true, "https://workbench.example.invalid/path");
  assert.equal((await badOrigin.POST(mutation({}), context("operations"))).status, 503);
});

test("Lost Memory POST stays uncertain, sends once and exposes no private error values", async () => {
  let calls = 0; const api = routes(async () => { calls++; throw new Error(`${secret} ${privateText}`); });
  const response = await api.POST(mutation({ content: privateText }), context("operations"));
  assert.equal(response.status, 502); const body = await response.text(); assert.ok(body.includes("MEMORY_ORIGINAL_KEY_REQUIRED"));
  assert.equal(body.includes(secret), false); assert.equal(body.includes(privateText), false); assert.equal(calls, 1);
});

test("Memory rejections and key conflicts expose only stable safe codes", async () => {
  for (const [status, detail, code] of [[422, [{ input: privateText, msg: secret }], "MEMORY_REQUEST_REJECTED"], [409, "Memory operation key conflicts with its original actor or request", "MEMORY_OPERATION_KEY_CONFLICT"], [409, privateText, "MEMORY_PRECONDITION_REQUIRED"]]) {
    const api = routes(async () => new Response(JSON.stringify({ detail }), { status }));
    const response = await api.POST(mutation({}), context("operations"));
    assert.equal(response.status, status); assert.deepEqual(await response.json(), { code });
  }
});
