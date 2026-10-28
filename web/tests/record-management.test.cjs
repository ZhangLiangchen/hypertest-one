const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const helpers = load("lib/record-management.ts");
const i18n = load("lib/i18n.tsx", { require });

test("manual edit payloads preserve the chosen version and exclude immutable identity and test results", () => {
  const project = helpers.projectEditPayload({ name: "  项目  ", description: "", repository_url: "  ", test_framework_repository_url: " https://git.example/framework ", default_branch: " main ", key: "OTHER", row_version: 99, status: "ARCHIVED" }, 4);
  assert.equal(JSON.stringify(project), JSON.stringify({ expected_version: 4, name: "项目", description: null, repository_url: null, test_framework_repository_url: "https://git.example/framework" }));
});

test("project and task management use version guarded APIs and explicit recycle bin reads", async () => {
  const calls = [];
  const api = load("lib/api.ts", { fetch: async (url, options) => { calls.push({ url, options }); return new Response("{}"); } });
  await api.getProjects();
  await api.getProjects(true);
  await api.updateProject("project id", { expected_version: 2, name: "Edited" });
  await api.deleteProject("project id", 3);
  await api.restoreProject("project id", 4);
  await api.getProject("project id", true);
  assert.deepEqual(calls.map(({ url }) => url), ["/api/v1/projects", "/api/v1/projects?include_deleted=true", "/api/v1/projects/project%20id", "/api/v1/projects/project%20id?expected_version=3", "/api/v1/projects/project%20id/restore", "/api/v1/projects/project%20id?include_deleted=true"]);
  assert.deepEqual(calls.slice(2, 5).map(({ options }) => options.method), ["PATCH", "DELETE", "POST"]);
  for (const { options } of calls) assert.equal(options.headers["X-Hypertest-Operator-Key"], undefined);
});

test("only stale version conflicts ask the user to reopen; dependency conflicts retain their actual cause", () => {
  const api = load("lib/api.ts", { require });
  const { ManagementDialog } = load("app/record-management.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/api" ? api : name === "@/app/client-modal" ? { ClientModal: ({ children }) => React.createElement("div", null, children) } : require(name) });
  const render = (error) => renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(ManagementDialog, { error, open: true, title: "Delete", version: 4, pending: false, mode: "delete", onRefresh() {}, onCancel() {}, onConfirm() {} }, "Retain history")));
  const stale = render(new api.ApiError(409, "Project version is stale; refresh first"));
  assert.ok(stale.includes("Your input is preserved"));
  assert.ok(stale.includes("Editing version"));
  const dependency = render(new api.ApiError(409, "Project has undeleted session tasks; delete tasks first"));
  assert.ok(dependency.includes("delete tasks first"));
  assert.equal(dependency.includes("cancel and reopen"), false);
});
