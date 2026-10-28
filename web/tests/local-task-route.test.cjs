const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const urls = load("lib/task-url.ts");
const taskId = "01a17c58-a95b-7df5-85a0-6171575aa1ad";
const projectId = "01a15de2-205e-76e6-bfad-7468a724f886";

function renderRoute(search, locale = "en") {
  const opened = [];
  const detail = (kind) => (props) => { opened.push({ kind, ...props }); return React.createElement("div", null, kind); };
  const route = load("app/tasks/[taskId]/page.tsx", { require: (name) =>
    name === "@/lib/i18n" ? i18n
      : name === "next/navigation" ? { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams(search) }
        : name === "../archive-task-detail" ? { default: detail("archive") }
          : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(route.default)));
  return { opened, html };
}

test("the shared task route selects archive data only with its explicit mode and project", () => {
  const archive = renderRoute(`mode=archive&projectId=${projectId}`);
  assert.deepEqual(archive.opened, [{ kind: "archive", taskId, projectId }]);
  assert.deepEqual(renderRoute("").opened, []);
  assert.deepEqual(renderRoute(`projectId=${projectId}`).opened, []);
});

test("missing or invalid archive targets and unknown modes never fall through to historical data", () => {
  for (const locale of ["en", "zh"]) {
    for (const search of ["mode=archive", "mode=archive&projectId=invalid", `mode=unknown&projectId=${projectId}`]) {
      const { opened, html } = renderRoute(search, locale);
      assert.deepEqual(opened, []);
      assert.ok(html.includes(locale === "en" ? "Open this task from its Project workspace." : "请从所属项目工作区打开此任务。"));
    }
  }
});

test("released CLI archive links replace the address with the shared task route and keep its fragment", () => {
  const effects = [], navigation = [];
  const route = load("app/archives/[taskId]/page.tsx", { window: { location: { hash: "#archive-upload-heading" } }, require: (name) =>
    name === "react" ? { ...React, useEffect: (effect) => effects.push(effect) }
      : name === "@/lib/i18n" ? i18n : name === "@/lib/task-url" ? urls
        : name === "@/app/workspace-ui" ? { WorkspaceLoading: ({ label }) => React.createElement("p", null, label) }
          : name === "next/navigation" ? { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams(`projectId=${projectId}&mode=legacy`), useRouter: () => ({ replace: (href) => navigation.push(href) }) }
            : require(name) });
  renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(route.default)));
  effects.forEach((effect) => effect());
  assert.deepEqual(navigation, [`/tasks/${taskId}?mode=archive&projectId=${projectId}#archive-upload-heading`]);
});

test("task links encode identifiers without changing project or adding route parameters", () => {
  assert.equal(urls.archiveTaskHref("task/one", "project&mode=legacy", "#archive-overview"), "/tasks/task%2Fone?mode=archive&projectId=project%26mode%3Dlegacy#archive-overview");
});

test("project archive rows link to the shared task route with their explicit project", () => {
  const component = load("app/projects/[projectId]/archive-tasks.tsx", { require: (name) =>
    name === "@/lib/i18n" ? i18n : name === "@/lib/task-url" ? urls
      : name === "@tanstack/react-query" ? { useQuery: () => ({ data: { items: [{ id: taskId, title: "Archived task", status: "DRAFT", archive_version: 1 }], total: 1 } }) }
        : ["@/lib/api", "@/lib/archive"].includes(name) ? {}
          : name === "@/app/tasks/task-records" ? { ReportedResultTag: () => null }
            : name === "./local-mode-guide" ? { LocalModeGuide: () => null }
              : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(component.ProjectArchiveTasks, { projectId, projectDeleted: false })));
  assert.ok(html.includes(`href="/tasks/${taskId}?mode=archive&amp;projectId=${projectId}"`));
  assert.equal(html.includes('href="/archives/'), false);
});
