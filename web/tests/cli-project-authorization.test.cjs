const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const { groupCliGrants, cliProjectAuthorizationPrompt } = load("lib/cli-project-authorization.ts", { URL });
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const fixture = (n, overrides = {}) => ({ grant_id: uuid(n), client_instance_id: uuid(10), actor_ref: `interactive:${uuid(20)}`, client_name: "Same hostname", project_id: uuid(30), status: "ACTIVE", ...overrides });
test("client/project tree separates identities and preserves repeated and inactive grants", () => {
  const grants = [fixture(1), fixture(2, { status: "REVOKED" }), fixture(3, { project_id: uuid(31), status: "EXPIRED" }), fixture(4, { client_instance_id: uuid(11) }), fixture(5, { actor_ref: `interactive:${uuid(21)}` })];
  const groups = groupCliGrants(grants);
  assert.equal(groups.length, 3);
  assert.equal(groups[0].projects.length, 2);
  assert.deepEqual(Array.from(groups[0].projects[0].grants, (g) => g.grant_id), [uuid(1), uuid(2)]);
  assert.equal(groups.flatMap((c) => c.projects.flatMap((p) => p.grants)).length, grants.length);
  assert.equal(new Set(groups.map((g) => g.key)).size, 3);
  assert.equal(grants[1].status, "REVOKED");
});
const options = { server: "https://hypertest.example:8080", clientInstanceId: uuid(10), actorRef: `interactive:${uuid(20)}`, projectId: uuid(31) };
test("incremental prompt matches the existing profile and preserves original-key recovery in both languages", () => {
  for (const locale of ["en", "zh"]) {
    const prompt = cliProjectAuthorizationPrompt({ ...options, locale });
    for (const value of Object.values(options)) assert.ok(prompt.includes(value));
    assert.ok(prompt.includes("hypertest profile show --json"));
    assert.ok(prompt.includes("--profile 'MATCHED_PROFILE'"));
    assert.ok(prompt.includes(`--project-id '${options.projectId}' --wait-seconds 0 --json`));
    assert.ok(prompt.includes("hypertest auth bind --resume --request-id ORIGINAL_REQUEST_ID"));
    assert.ok(prompt.includes("hypertest auth reconcile --request-id ORIGINAL_REQUEST_ID"));
    assert.ok(prompt.includes("SSL_CERT_FILE"));
    assert.ok(prompt.includes(locale === "en" ? "I must match the short code" : "由我在网页核对短码"));
    assert.equal(prompt.includes("--profile default"), false);
  }
});
test("invalid identifiers and noncanonical or unsafe origins cannot enter copyable commands", () => {
  for (const field of ["projectId", "clientInstanceId", "actorRef"]) {
    assert.throws(() => cliProjectAuthorizationPrompt({ ...options, locale: "en", [field]: "$(touch /tmp/not-allowed)" }), /CONTEXT_INVALID/);
  }
  for (const server of ["http://hypertest.example", "https://user:secret@hypertest.example", "https://hypertest.example/path", "https://hypertest.example/?q=1", "https://hypertest.example/#x", "https://evil'host", "https://hypertest.example\n"]) {
    assert.throws(() => cliProjectAuthorizationPrompt({ ...options, locale: "zh", server }), /SERVER_INVALID/);
  }
  assert.ok(cliProjectAuthorizationPrompt({ ...options, locale: "en", server: options.server + "/" }).includes(`--server '${options.server}'`));
});
