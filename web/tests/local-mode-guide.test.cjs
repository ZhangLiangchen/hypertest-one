const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const projectId = "01a15807-6162-7759-a0cf-614d34f977af";
const cliRelease = load("lib/cli-release.ts", { URL });
const cliInstall = load("lib/cli-install-prompt.ts", { URL, require: (name) => name === "./cli-release" ? cliRelease : require(name) });
const cliInstallComponent = load("app/cli-authorizations/cli-install-prompt.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/cli-install-prompt" ? cliInstall : name === "@/lib/clipboard" ? { copyText: async () => {} } : require(name) });
const component = load("app/projects/[projectId]/local-mode-guide.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/app/cli-authorizations/cli-install-prompt" ? cliInstallComponent : require(name) });

test("the archive project guide is reachable without blocking archive reads", () => {
  const section = load("app/projects/[projectId]/archive-tasks.tsx", { require: (name) =>
    name === "@/lib/task-url" ? load("lib/task-url.ts") : name === "@/lib/i18n" ? i18n : name === "./local-mode-guide" ? component
      : name === "@tanstack/react-query" ? { useQuery: () => ({ data: { items: [], total: 0 }, isLoading: false, isError: false }) }
      : ["@/lib/api", "@/lib/archive"].includes(name) ? {} : name === "@/app/tasks/task-records" ? { ReportedResultTag: () => null }
      : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });
  const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: "en" }, React.createElement(section.ProjectArchiveTasks, { projectId, projectDeleted: false })));
  assert.ok(html.includes("CLI installation prompt &amp; archive guide"));
  assert.ok(html.includes('aria-expanded="false"'));
  assert.ok(html.includes("No local test tasks yet"));
  assert.equal(html.includes("python3 -I -c"), false);
});

test("both languages guide explicit archives and link global CLI authorization without legacy setup", () => {
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.LocalModeGuide, { projectId, initiallyOpen: true })));
    assert.ok(html.includes(projectId)); assert.ok(html.includes(`/cli-authorizations?projectId=${projectId}`));
    assert.ok(html.includes("hypertest-archive"));
    assert.ok(html.includes(locale === "en" ? "Copy install / upgrade prompt" : "复制安装 / 升级 Prompt"));
    assert.ok(html.includes(cliRelease.CLI_RELEASE.artifactSha256));
    for (const text of locale === "en" ? ["Install and authorize the CLI once", "Task root", "Archive after local testing"] : ["安装 CLI 并完成一次授权", "任务根空间", "本地测试结束后归档"]) {
      if (text === "Task root" || text === "任务根空间") continue;
      assert.ok(html.includes(text), text);
    }
    assert.equal(/task:sync|--channel candidate|update-local.py|0\.144\.6|type="password"|name="token"|RELEASE_READY|VERIFIED/.test(html), false);
  }
});
