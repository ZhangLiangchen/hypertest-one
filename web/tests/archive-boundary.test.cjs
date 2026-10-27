const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const p = "00000000-0000-4000-8000-000000000001", task = "00000000-0000-4000-8000-000000000002", subtask = "00000000-0000-4000-8000-000000000003";
const secret = "operator-canary-never-browser";
function boundary(upstream, env = {}) {
  return load("lib/archive-server.ts", { Buffer, URL, URLSearchParams,
    process: { env: { HYPERTEST_ARCHIVE_WEB_ENABLED: "true", HYPERTEST_ARCHIVE_WEB_OPERATOR_KEY_FILE: "/private/operator", HYPERTEST_ARCHIVE_WEB_ORIGIN: "https://web.example", ...env } },
    require: (name) => name === "node:fs/promises" ? { readFile: async () => secret } : name === "next/server" ? { NextResponse: { json: (v, init) => new Response(JSON.stringify(v), init) } }
      : name === "@/lib/cloud-server-auth" ? { trustedServerRequest: upstream, cloudServerTransportReady: async () => true } : require(name),
  }).localBoundary;
}
function req(path, options) { const request = new Request(`https://web.example/api/archive/${path}`, options); request.nextUrl = new URL(request.url); return request; }
const post = (origin = "https://web.example") => ({ method: "POST", headers: { origin, "content-type": "application/json" }, body: "{}" });
test("Local BFF requires independent enablement, operator file and same-origin JSON; no credential exposure", async () => {
  const calls = []; const up = async (...args) => { calls.push(args); return new Response(JSON.stringify({ ok: true })); };
  for (const env of [{ HYPERTEST_ARCHIVE_WEB_ENABLED: "false" }, { HYPERTEST_ARCHIVE_WEB_OPERATOR_KEY_FILE: "" }]) {
    const route = boundary(up, env); assert.equal((await route(req("tasks"), "tasks", "archive", "GET")).status, 503);
  }
  const route = boundary(up);
  assert.equal((await route(req("tasks", post("https://evil.example")), "tasks", "archive", "POST")).status, 403);
  assert.equal((await route(req("tasks", { ...post(), headers: { "content-type": "application/json" } }), "tasks", "archive", "POST")).status, 403);
  assert.equal((await route(req("requests", post()), "requests", "cli-authorization", "POST")).status, 404, "browser cannot redeem or create credentials");
  assert.equal((await route(req("actors"), "actors", "cli-authorization", "GET")).status, 404, "CLI approval does not enumerate legacy identities");
  assert.equal((await route(req(`tasks/${task}/submissions`, post()), `tasks/${task}/submissions`, "archive", "POST")).status, 404, "browser cannot impersonate an uploader");
  assert.equal(calls.length, 0);
  const result = await route(req("tasks", post()), "tasks", "archive", "POST");
  assert.equal(result.status, 200); assert.equal(calls[0][1], secret); assert.equal((await result.text()).includes(secret), false);
});
test("Local BFF preserves safe rejection codes and hides arbitrary upstream errors", async () => {
  for (const detail of [secret, { input: secret }, "ARCHIVE_TASK_VERSION_CONFLICT", "CLI_PAIRING_EXPIRED"]) {
    const route = boundary(async () => new Response(JSON.stringify({ detail }), { status: 409 }));
    const result = await route(req("tasks", post()), "tasks", "archive", "POST"); const body = await result.json();
    assert.equal(JSON.stringify(body).includes(secret), false);
    if (typeof detail === "string" && detail !== secret) assert.equal(body.detail, detail);
  }
});
test("Complete root snapshots freeze identity and Unicode page offsets, reject mismatched child or version", async () => {
  const doc = { profile: "local-artifact-archive/v1alpha1", project_id: p, task_id: task, target_kind: "TASK", subtask_id: null, archive_version: 2, assets: [{ markdown: "原文🙂\nFAIL" }] };
  const chars = [...JSON.stringify(doc)]; const first = Math.floor(chars.length / 2);
  for (const corrupt of [null, "subtask", "version", "offset"]) {
    let count = 0;
    const route = boundary(async () => {
      const start = count++ ? first : 0, end = start ? chars.length : first;
      const page = { ...doc, submission_id: null, offset: start, next_offset: end === chars.length ? null : end, total_chars: chars.length, content: chars.slice(start, end).join(""), complete: end === chars.length };
      if (count === 2 && corrupt) { if (corrupt === "subtask") page.subtask_id = subtask; if (corrupt === "version") page.archive_version = 3; if (corrupt === "offset") page.next_offset = end; }
      return new Response(JSON.stringify(page));
    });
    const response = await route(req(`tasks/${task}/archive?project_id=${p}&archive_version=2&readback=complete`), `tasks/${task}/archive`, "archive", "GET");
    assert.equal(response.status, corrupt ? 502 : 200); if (!corrupt) assert.deepEqual(await response.json(), doc);
  }
});
