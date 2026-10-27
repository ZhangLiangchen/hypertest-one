const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const link = { default: ({ children, ...props }) => React.createElement("a", props, children) };
const p = "00000000-0000-4000-8000-000000000001", taskId = "00000000-0000-4000-8000-000000000002";
const workspace = load("app/workspace-ui.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "next/link" ? link : require(name) });
const records = load("app/tasks/task-records.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : require(name) });
const release = load("lib/cli-release.ts", { URL });
const archive = load("lib/archive.ts", { require: () => ({ ApiError: Error }) });
const task = { id: taskId, project_id: p, title: "Synthetic archive fixture", objective: "Declared test sources", owner_uploader_actor_ref: "interactive:actor", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN" };
const operation = { ready: true, blocked: false, pending: null, busy: false, error: null };
function renderPage(path, locale, query, search = new URLSearchParams({ projectId: p })) {
  const component = load(path, { URLSearchParams, require: (name) => name === "@/lib/i18n" ? i18n : name === "@/app/workspace-ui" ? workspace : name === "@/app/tasks/task-records" ? records
    : name === "@/lib/archive" ? archive : name === "@/lib/api" ? { errorText: (e) => e?.message || "" } : name === "@/lib/cli-release" ? release : name === "@/lib/cli-authorization" ? {}
      : name === "@/lib/archive-operation" ? { useArchiveOperation: () => operation, useLocalWebOperation: () => operation } : name.endsWith("archive-shared") ? { ArchiveOperationNotice: () => null }
        : name === "@tanstack/react-query" ? { useQuery: ({ queryKey }) => ({ data: query[queryKey[0]], isLoading: false, isError: false }), useQueryClient: () => ({ invalidateQueries() {} }) }
          : name === "next/link" ? link : name === "next/navigation" ? { useParams: () => ({ taskId }), useSearchParams: () => search } : require(name),
  });
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.default)));
}
test("archive instruction requires project/task and only adds an explicitly selected subtask", () => {
  const root = archive.archiveSkillInstruction(p, taskId);
  assert.ok(root.startsWith("$hypertest-archive")); assert.ok(root.includes(`--project-id ${p} --task-id ${taskId}`)); assert.equal(root.includes("--subtask-id"), false);
  assert.ok(archive.archiveSkillInstruction(p, taskId, "child", true).includes("--subtask-id child"));
});
test("root archives render bilingual explicit upload, optional children and original version controls", () => {
  for (const locale of ["en", "zh"]) {
    const html = renderPage("app/archives/[taskId]/page.tsx", locale, { "archive-task": { task, subtasks: [], publications: [], submission_history: [], management_history: [] }, "archive-snapshot": { ...task, assets: [] }, "archive-actors": { items: [] } });
    assert.ok(html.includes(`--project-id ${p} --task-id ${taskId}`)); assert.equal(html.includes("--subtask-id"), false);
    assert.ok(html.includes(locale === "en" ? "Task root (no Subtask ID)" : "任务根空间（无需子任务 ID）"));
    assert.ok(html.includes(locale === "en" ? "Optional subtasks" : "可选子任务"));
    assert.ok(html.includes('id="archive-version"')); assert.equal(html.includes("hypertest_bind_task"), false);
  }
});
test("CLI authorization page supports explicit project approval without secret fields or shell-injected query text", () => {
  assert.equal(release.cliInstallCommand(), null);
  const published = { published: true, version: "0.1.0", sourceCommit: "a".repeat(40), releaseUrl: "https://example.invalid/cli-v0.1.0", installerUrl: "https://example.invalid/install-cli-release.py", artifactUrl: "https://example.invalid/hypertest-cli-0.1.0.pyz", installerSha256: "b".repeat(64), artifactSha256: "c".repeat(64) };
  const command = release.cliInstallCommand(published);
  assert.ok(command.includes("python3 -I -c")); assert.ok(command.includes(published.installerSha256)); assert.ok(command.includes(published.artifactSha256));
  assert.ok(command.indexOf("Installer SHA-256 mismatch") < command.indexOf("exec(compile"));
  assert.equal(command.includes("curl"), false);
  assert.throws(() => release.cliInstallCommand({ ...published, version: "0.1.0;malicious" }), /METADATA_INVALID/);
  const request = { request_id: taskId, status: "PENDING", client_name: "Synthetic CLI", server_url: "https://web.example", short_code: "ABC123", credential_fingerprint: "a".repeat(16), expires_at: "2026-10-27T23:00:00Z", approval: null, grants: [] };
  for (const locale of ["en", "zh"]) {
    const html = renderPage("app/cli-authorizations/page.tsx", locale, { "archive-web-setup": { configured: true }, "cli-request": request, "cli-actors": { items: [{ actor_identity_id: "a", actor_ref: "interactive:a", status: "ACTIVE" }] }, projects: [{ id: p, name: "Synthetic Project" }], "cli-grants": { items: [] } }, new URLSearchParams({ request_id: taskId, projectId: "$(touch /tmp/forbidden)" }));
    assert.ok(html.includes("ABC123")); assert.ok(html.includes("archive:read")); assert.ok(html.includes("archive:write"));
    assert.ok(html.includes("hypertest skill install --global --host codex"));
    assert.equal(html.includes("$(touch"), false); assert.equal(/type="password"|name="token"|Operator-Key/.test(html), false);
    assert.ok(html.includes(locale === "en" ? "Approve CLI" : "批准 CLI"));
  }
});
