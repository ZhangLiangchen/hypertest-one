const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const project = { id: "project-1", key: "P1", name: "Example project", status: "ACTIVE", description: "Description", repository_url: "https://example.org/sut", test_framework_repository_url: "https://example.org/tests" };
const heading = load("app/projects/project-workspace-heading.tsx", { require: name => name === "@/lib/i18n" ? i18n
  : name === "@/app/workspace-ui" ? { WorkspaceHeading: ({ title, description, actions, metadata }) => React.createElement("header", null, title, description, actions, metadata) }
    : name === "./project-actions" ? { ProjectActions: () => null } : require(name) });

test("both project views share identity while creating the intended task mode", () => {
  for (const locale of ["en", "zh"]) for (const mode of ["local", "cloud"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(heading.ProjectWorkspaceHeading, { project, projectId: project.id, mode })));
    assert.ok(html.includes("Example project"));
    assert.ok(html.includes("https://example.org/sut"));
    assert.ok(html.includes("https://example.org/tests"));
    assert.ok(html.includes(`/projects/project-1/tasks/new?mode=${mode}`));
    assert.ok(html.includes(locale === "zh" ? (mode === "local" ? "创建本地测试任务" : "创建云端测试任务") : (mode === "local" ? "Create local test task" : "Create cloud test task")));
    assert.equal(html.includes("创建归档任务"), false);
  }
});

test("deleted projects have no active task creation link", () => {
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(heading.ProjectWorkspaceHeading, { project: { ...project, deleted_at: "2026-01-01" }, projectId: project.id, mode: "cloud" })));
  assert.equal(html.includes("/tasks/new"), false);
  assert.ok(html.includes("disabled"));
});
