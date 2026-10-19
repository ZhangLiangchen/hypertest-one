const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const environment = load("lib/execution-environment.ts");
const { loadRunDraft } = load("lib/run-draft.ts", { require: () => environment });
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function fixture() {
  const calls = [];
  const values = {
    run: { id: id(1), project_id: id(2), source_snapshot_id: id(3), policy_snapshot_id: id(4) },
    source: { id: id(3), repository_url: "https://github.com/team/repo.git", commit_sha: "a".repeat(40), environment_definition: { image_id: "OLD_IMAGE", request: { profile_id: "python-api-v2", service: { app: "app:app", health_path: "/ready", startup_timeout_seconds: 12 } } } },
    policy: { id: id(4), compiled_policy: { gate_version: "mvp/v1", gate: { blocking_finding_severities: ["CRITICAL"] }, coverage: { default_dimensions: ["FUNCTIONAL", "NEGATIVE"] }, custom_extension: { keep: "original" } } },
    prd: "\uFEFF需求\r\nKeep whitespace.  \r\n",
    configuration: "",
  };
  const readers = Object.fromEntries(Object.keys(values).map((key) => [key, async (requested) => { calls.push([key, requested]); return values[key]; }]));
  return { values, readers, calls };
}

test("copied round retains exact UTF-8 text, empty context and every policy field, but copies only an environment request", async () => {
  const f = fixture();
  const result = await loadRunDraft(id(2), id(1), f.readers);
  assert.equal(result.prd, f.values.prd);
  assert.equal(result.configuration, "");
  assert.equal(JSON.stringify(result.policy.compiled_policy), JSON.stringify(f.values.policy.compiled_policy));
  assert.equal(result.source.commit_sha, "a".repeat(40));
  assert.equal(result.environment.environment_profile_id, "python-api-v2");
  assert.equal(result.environment.service_app, "app:app");
  assert.equal(JSON.stringify(result.environment).includes("OLD_IMAGE"), false);
  assert.equal("idempotency_key" in result, false);
  assert.equal("binding" in result, false);
  assert.deepEqual(f.calls, [["run", id(1)], ["source", id(3)], ["policy", id(4)], ["prd", id(3)], ["configuration", id(3)]]);
});

test("a cross-project run is rejected before reading any input content", async () => {
  const f = fixture();
  await assert.rejects(loadRunDraft(id(9), id(1), f.readers), (e) => e.code === "project");
  assert.deepEqual(f.calls, [["run", id(1)]]);
});

test("malformed run links cannot become arbitrary API paths", async () => {
  const f = fixture();
  for (const input of ["../projects", `${id(1)}?other=1`, ""]) {
    await assert.rejects(loadRunDraft(id(2), input, f.readers), (e) => e.code === "run");
  }
  assert.equal(f.calls.length, 0);
});

test("a saved input failing server integrity validation never produces a partial copied draft", async () => {
  const f = fixture();
  f.readers.configuration = async () => { throw new Error("configuration checksum mismatch"); };
  await assert.rejects(loadRunDraft(id(2), id(1), f.readers), /checksum mismatch/);
  assert.equal(f.values.prd, "\uFEFF需求\r\nKeep whitespace.  \r\n");
});

test("snapshot identity mismatch cannot populate a copied draft", async () => {
  const f = fixture(); f.values.source.id = id(8);
  await assert.rejects(loadRunDraft(id(2), id(1), f.readers), (e) => e.code === "snapshot");
});

test("unbound, archived and incomplete API environments need explicit new configuration", async () => {
  for (const definition of [null, { request: { profile_id: "python-api-v1", service: { app: "app:app", health_path: "/health", startup_timeout_seconds: 30 } } }, { request: { profile_id: "python-api-v2", service: { app: "app:app" } } }]) {
    const f = fixture(); f.values.source.environment_definition = definition;
    await assert.rejects(loadRunDraft(id(2), id(1), f.readers), (e) => e.code === "environment");
  }
});

test("actual input API readers preserve a leading U+FEFF, CRLF and empty text byte-for-byte", async () => {
  for (const text of ["\uFEFF需求\r\n  ", "", "\r\n{\"context\":\"原文\"}\r\n"]) {
    const bytes = new TextEncoder().encode(text);
    const api = load("lib/api.ts", { TextDecoder, fetch: async () => new Response(bytes) });
    assert.equal(await api.getPrdContent(id(3)), text);
    assert.equal(await api.getConfigurationContent(id(3)), text);
  }
});

test("input API readers reject invalid UTF-8 and error responses instead of copying replacement text", async () => {
  const invalid = load("lib/api.ts", { TextDecoder, fetch: async () => new Response(new Uint8Array([0xc3, 0x28])) });
  await assert.rejects(invalid.getPrdContent(id(3)), /encoded data/);
  await assert.rejects(invalid.getConfigurationContent(id(3)), /encoded data/);
  const corrupt = load("lib/api.ts", { TextDecoder, fetch: async () => new Response(JSON.stringify({ detail: "PRD artifact unavailable or checksum mismatch" }), { status: 409 }) });
  await assert.rejects(corrupt.getPrdContent(id(3)), (error) => error.status === 409);
});
