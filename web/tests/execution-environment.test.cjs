const assert = require("node:assert/strict");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");
const helper = loadHelper("lib/execution-environment.ts");
const { buildEnvironmentRequest, canUseEnvironment, defaultEnvironmentValues, environmentInputIssue, executionBackend, runInputSignature, selectedEnvironmentProfile, validHealthPath, validServiceApp, validStartupTimeout, visibleEnvironmentDefinition, visibleExecutionIdentity } = helper;
const sha = "a".repeat(64);
const apiDraft = () => ({ ...defaultEnvironmentValues(), environment_profile_id: "python-api-v1", service_app: "package.api:app" });
const profile = (id = "python-api-v1", extra = {}) => ({ profile_id: id, kind: id === "python-api-v1" ? "asgi" : "pytest", dependencies: { pytest: "8.3.3", fastapi: "0.115.0" }, dependency_lock_sha256: sha, launcher_sha256: sha, network: "none", available: true, checked_at: "2026-10-18T12:00:00Z", ...extra });
const binding = () => ({ schema_version: "hypertest.environment/v1", request: buildEnvironmentRequest(apiDraft()), image_id: `sha256:${sha}`, image_os: "linux", image_architecture: "amd64", dependency_lock_sha256: sha, dependencies: { pytest: "8.3.3", fastapi: "0.115.0" }, launcher_sha256: sha });

test("defaults and ASGI request bodies contain only supported environment inputs", () => {
  assert.equal(defaultEnvironmentValues().environment_profile_id, "python-pytest-v1");
  const draft = { ...apiDraft(), image: "untrusted", command: "SECRET_COMMAND", service_port: 1234, env: { TOKEN: "SECRET" } };
  assert.equal(JSON.stringify(buildEnvironmentRequest(draft)), JSON.stringify({ profile_id: "python-api-v1", service: { app: "package.api:app", health_path: "/health", startup_timeout_seconds: 30 } }));
});

test("switching to pytest preserves the ASGI draft without leaking hidden service fields", () => {
  const draft = apiDraft();
  const original = JSON.stringify(draft);
  assert.equal(JSON.stringify(buildEnvironmentRequest({ ...draft, environment_profile_id: "python-pytest-v1", service_health_path: "https://secret.invalid" })), '{"profile_id":"python-pytest-v1"}');
  assert.equal(JSON.stringify(draft), original);
  assert.equal(buildEnvironmentRequest(draft).service.app, "package.api:app");
});

test("ASGI accepts ASCII dotted objects and rejects factories, commands and whitespace rewriting", () => {
  for (const value of ["main:app", "package.api_v2:application", "_app:_application"]) assert.equal(validServiceApp(value), true, value);
  for (const value of ["", "main:create_app()", "main:app --port 9", "main:app;echo x", " main:app", "main:app ", "服务:app", "main:app.extra", "/main.py:app", "https://host:app"]) assert.equal(validServiceApp(value), false, value);
  assert.equal(validServiceApp(`${"a".repeat(253)}:app`), false);
});

test("health paths reject authority, query, fragment, encoding and traversal", () => {
  for (const value of ["/health", "/", "/ready/v1", "/health_check~live"]) assert.equal(validHealthPath(value), true, value);
  for (const value of ["health", "//host/health", "/a//health", "/../health", "/x..y", "/%2e%2e/health", "/health?token=secret", "/health#fragment", "http://host/health", "/health\\x", "/" + "a".repeat(256)]) assert.equal(validHealthPath(value), false, value);
});

test("startup timeout rejects fractional or textual values rather than silently normalizing them", () => {
  for (const value of [1, 30, 120]) assert.equal(validStartupTimeout(value), true);
  for (const value of [0, 121, 1.5, "30", null, undefined, Infinity]) assert.equal(validStartupTimeout(value), false);
  assert.equal(environmentInputIssue({ ...apiDraft(), service_startup_timeout_seconds: 121 }), "timeout");
});

test("failed, missing and unavailable catalog entries block use without choosing a fallback", () => {
  const draft = apiDraft();
  const catalog = { profiles: [profile(), profile("python-pytest-v1")] };
  assert.equal(canUseEnvironment(catalog, draft.environment_profile_id, false), true);
  assert.equal(canUseEnvironment(catalog, draft.environment_profile_id, true), false);
  assert.equal(canUseEnvironment({ profiles: [profile("python-pytest-v1")] }, draft.environment_profile_id, false), false);
  assert.equal(canUseEnvironment({ profiles: [profile(undefined, { available: false })] }, draft.environment_profile_id, false), false);
  assert.equal(canUseEnvironment({ profiles: [profile(undefined, { kind: "pytest" })] }, draft.environment_profile_id, false), false);
  assert.equal(canUseEnvironment(catalog, "unknown-untrusted-profile", false), false);
  assert.equal(canUseEnvironment({ profiles: null }, draft.environment_profile_id, false), false);
  assert.equal(canUseEnvironment({ profiles: [null] }, draft.environment_profile_id, false), false);
  assert.equal(selectedEnvironmentProfile(catalog, draft.environment_profile_id).profile_id, draft.environment_profile_id);
  assert.equal(draft.service_app, "package.api:app");
});

test("idempotency identity includes the environment and preserves original PRD/configuration bytes", () => {
  const input = { repository_url: "https://github.com/example/repo", commit_sha: "a".repeat(40), branch: "main", prd_text: "  中文 PRD\r\n🙂  ", configuration_text: " {\n\"context\":true\n} ", environment: buildEnvironmentRequest(apiDraft()) };
  const initial = runInputSignature("project-1", input);
  assert.equal(runInputSignature("project-1", { ...input, branch: "another-label" }), initial);
  assert.notEqual(runInputSignature("project-1", { ...input, environment: buildEnvironmentRequest(defaultEnvironmentValues()) }), initial);
  assert.notEqual(runInputSignature("project-1", { ...input, environment: buildEnvironmentRequest({ ...apiDraft(), service_health_path: "/ready" }) }), initial);
  assert.equal(JSON.parse(initial).prd_text, input.prd_text);
  assert.equal(JSON.parse(initial).configuration_text, input.configuration_text);
});

test("bindings force Docker while historical null bindings retain the legacy Runner choice", () => {
  assert.equal(executionBackend(binding(), "local"), "docker");
  assert.equal(executionBackend({ unknown: "bad-binding" }, "local"), "docker");
  assert.equal(executionBackend(null, "local"), "local");
  assert.equal(executionBackend(undefined, "docker"), "docker");
});

test("frozen definitions exclude unknown fields and do not adopt later catalog updates", () => {
  const original = binding(); original.raw = "SECRET_RAW"; original.request.service.env = { TOKEN: "SECRET_TOKEN" };
  const safe = visibleEnvironmentDefinition(original);
  const updatedCatalog = { profiles: [profile(undefined, { dependencies: { fastapi: "999.0" } })] };
  assert.equal(selectedEnvironmentProfile(updatedCatalog, "python-api-v1").dependencies.fastapi, "999.0");
  assert.equal(safe.dependencies.fastapi, "0.115.0");
  assert.equal(JSON.stringify(safe).includes("SECRET"), false);
  assert.equal(visibleEnvironmentDefinition({ ...original, schema_version: "unknown" }), null);
  assert.equal(visibleEnvironmentDefinition({ ...original, image_id: "SECRET_IMAGE_URL" }), null);
});

test("execution uses its own top-level definition and records the actual Runner image separately", () => {
  const frozen = binding(); const actual = `sha256:${"b".repeat(64)}`;
  const projected = visibleExecutionIdentity({ environment_definition: frozen, environment: { image_id: actual, network: "none", environment_definition: { ...binding(), image_id: actual }, raw: "SECRET_RAW" }, command: "SECRET_COMMAND" });
  assert.equal(projected.definition.image_id, frozen.image_id);
  assert.equal(projected.image_id, actual);
  assert.equal(JSON.stringify(projected).includes("SECRET"), false);
  assert.equal(visibleExecutionIdentity({ environment: { image_id: actual, network: "none" } }).definition, null);
  assert.equal(visibleExecutionIdentity({ environment_definition: { schema_version: "unknown" }, environment: { environment_definition: frozen } }).definition, null);
  assert.equal(visibleExecutionIdentity({ environment_definition: null, environment: { environment_definition: frozen } }).definition.image_id, frozen.image_id);
});

test("catalog API makes one readonly request", async () => {
  const calls = [];
  const { getExecutionEnvironments } = loadHelper("lib/api.ts", { fetch: async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify({ profiles: [profile()] }), { status: 200 }); } });
  assert.equal((await getExecutionEnvironments()).profiles[0].profile_id, "python-api-v1");
  assert.equal(calls.length, 1); assert.equal(calls[0].url, "/api/v1/execution-environments");
  assert.equal(calls[0].init.method, undefined); assert.equal(calls[0].init.body, undefined);
});

test("real bilingual components render pinned identities without raw payloads or secret fields", () => {
  const React = require("react"); const { renderToStaticMarkup } = require("react-dom/server");
  const i18n = loadHelper("lib/i18n.tsx", { require });
  const { PinnedEnvironment, ExecutionEnvironmentIdentity } = loadHelper("app/execution-environment.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/execution-environment" ? helper : require(name) });
  const definition = { ...binding(), command: "SECRET_COMMAND", env: { TOKEN: "SECRET_TOKEN" }, raw: "SECRET_RAW" };
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(React.Fragment, null, React.createElement(PinnedEnvironment, { definition }), React.createElement(ExecutionEnvironmentIdentity, { execution: { environment_id: "SECRET_UNKNOWN_ID", environment_fingerprint: sha, spec: { environment_definition: definition, environment: { image_id: definition.image_id, network: "none", raw: "SECRET_RAW" } } } }))));
    assert.equal(html.includes("SECRET"), false); assert.equal(html.includes("package.api:app"), true);
    assert.equal(html.includes(locale === "en" ? "Pinned execution environment" : "固定执行环境"), true);
  }
});
