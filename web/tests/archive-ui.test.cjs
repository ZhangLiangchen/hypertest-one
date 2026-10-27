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
const install = load("lib/cli-install-prompt.ts", { URL, require: (name) => name === "./cli-release" ? release : require(name) });
const cliProjects = load("lib/cli-project-authorization.ts", { URL });
const installComponent = load("app/cli-authorizations/cli-install-prompt.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/cli-install-prompt" ? install : require(name) });
const archive = load("lib/archive.ts", { URL, require: () => ({ ApiError: Error }) });
const task = { id: taskId, project_id: p, title: "Synthetic archive fixture", objective: "Declared test sources", owner_uploader_actor_ref: "interactive:actor", version: 1, archive_version: 1, status: "DRAFT", reported_result: "NOT_RUN" };
const operation = { ready: true, blocked: false, pending: null, busy: false, error: null };
function renderPage(path, locale, query, search = new URLSearchParams({ projectId: p }), observe) {
  const antd = require("antd");
  const Form = observe ? Object.assign((props) => { if (props.form) { observe.approve = props.onFinish; observe.initialValues = props.initialValues; } return React.createElement(antd.Form, props); }, antd.Form) : antd.Form;
  const pageRequire = (name) => name === "@/lib/i18n" ? i18n : name === "@/app/workspace-ui" ? workspace : name === "@/app/tasks/task-records" ? records
    : name === "../archive-prompt" ? load("app/archives/archive-prompt.tsx", { require: pageRequire }) : name === "@/lib/archive" ? archive : name === "@/lib/api" ? { errorText: (e) => e?.message || "" } : name === "@/lib/cli-release" ? release : name === "@/lib/cli-install-prompt" ? install : name === "./cli-install-prompt" ? installComponent : name === "@/lib/cli-authorization" ? {}
      : name === "@/lib/archive-operation" ? { useArchiveOperation: () => operation, useLocalWebOperation: () => observe?.operation || operation } : name.endsWith("archive-shared") ? { ArchiveOperationNotice: () => null }
        : name === "@tanstack/react-query" ? { useQuery: ({ queryKey }) => { assert.notEqual(queryKey[0], "cli-actors", "CLI approval must not fetch historical uploader identities"); return { data: query[queryKey[0]], isLoading: false, isError: false }; }, useQueryClient: () => ({ invalidateQueries() {} }) }
          : name === "@/lib/cli-project-authorization" ? cliProjects
          : name.startsWith("./cli-") ? load(`app/cli-authorizations/${name.slice(2)}.tsx`, { require: pageRequire })
          : name === "next/link" ? link : name === "next/navigation" ? { useParams: () => ({ taskId }), useSearchParams: () => search } : name === "antd" ? { ...antd, Form } : require(name);
  const component = load(path, { URLSearchParams, require: pageRequire });
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(component.default)));
}
test("archive instruction requires project/task and only adds an explicitly selected subtask", () => {
  const root = archive.archiveSkillInstruction(p, taskId);
  assert.ok(root.startsWith("$hypertest-archive")); assert.ok(root.includes(`Project ID: ${p}`)); assert.ok(root.includes(`Task ID: ${taskId}`)); assert.equal(root.includes("Subtask ID:"), false);
  assert.ok(archive.archiveSkillInstruction(p, taskId, p, true).includes(`Subtask ID: ${p}`));
});
test("CLI approval submits short-code project authorization without choosing an actor", async () => {
  const sent = [];
  const observe = { operation: { ...operation, submit: async (...args) => { sent.push(args); return null; } } };
  renderPage("app/cli-authorizations/page.tsx", "en", { "archive-web-setup": { configured: true }, "cli-request": { request_id: taskId, status: "PENDING", short_code: "ABC123", client_name: "Synthetic CLI", expires_at: "2026-10-27T23:00:00Z" }, projects: [{ id: p, name: "Synthetic Project" }], "cli-grants": { items: [] } }, new URLSearchParams({ request_id: taskId }), observe);
  await observe.approve({ actor_identity_id: "historical-actor", project_ids: [p], expires_in_days: 30 });
  assert.equal(sent.length, 1);
  assert.equal(sent[0][0], `requests/${taskId}/approve`);
  assert.equal(sent[0][1]("original-key"), `requests/by-key?request_id=${taskId}&operation=APPROVE&idempotency_key=original-key`);
  assert.deepEqual(JSON.parse(JSON.stringify(sent[0][2])), { project_ids: [p], scopes: ["archive:read", "archive:write"], expires_in_days: 30, short_code: "ABC123" });
});
test("CLI approval preselects the request project hint while still requiring explicit short-code consent", () => {
  const observe = {};
  const html = renderPage("app/cli-authorizations/page.tsx", "en", { "archive-web-setup": { configured: true }, "cli-request": { request_id: taskId, status: "PENDING", short_code: "ABC123", client_name: "Synthetic CLI", expires_at: "2026-10-27T23:00:00Z", requested_project_id: p }, projects: [{ id: p, name: "Synthetic Project" }], "cli-grants": { items: [] } }, new URLSearchParams({ request_id: taskId }), observe);
  assert.deepEqual(Array.from(observe.initialValues.project_ids), [p]);
  assert.ok(html.includes("The code matches the CLI I started"));
  assert.ok(html.includes('type="checkbox"'));
});
test("completed pairing is a compact client status with folded details, while approved still awaits the CLI", () => {
  for (const locale of ["zh", "en"]) {
    for (const status of ["BOUND", "APPROVED"]) {
      const request = { request_id: taskId, status, client_name: "Synthetic Laptop", short_code: "ABC123", expires_at: "2026-10-27T23:00:00Z", approval: { project_ids: [p], expires_at: "2027-01-01T23:00:00Z" } };
      const html = renderPage("app/cli-authorizations/page.tsx", locale, { "archive-web-setup": { configured: true }, "cli-request": request, projects: [], "cli-grants": { items: [] } }, new URLSearchParams({ request_id: taskId }));
      assert.ok(html.includes('class="cli-request-result"'));
      assert.ok(html.includes('<strong>Synthetic Laptop</strong>'));
      assert.ok(html.includes('<details class="cli-pairing-details">'));
      assert.equal(html.includes('ant-alert-success'), false);
      assert.ok(html.includes(status === "BOUND" ? 'cli-request-status is-bound' : 'cli-request-status is-waiting'));
      if (status === "APPROVED") assert.ok(html.includes(locale === "en" ? "awaiting CLI" : "等待 CLI 确认"));
    }
  }
});
test("client tree keeps one project child with all grant records and exposes Add project", () => {
  const grant = { grant_id: "g1", project_id: p, client_instance_id: taskId, client_name: "Synthetic Laptop", actor_ref: `interactive:${p}`, status: "ACTIVE", scopes: ["archive:read", "archive:write"], expires_at: "2027-01-01T23:00:00Z", credential_fingerprint: "first-fingerprint" };
  for (const locale of ["zh", "en"]) {
    const html = renderPage("app/cli-authorizations/page.tsx", locale, { "archive-web-setup": { configured: true }, projects: [{ id: p, name: "Synthetic Project" }], "cli-grants": { items: [grant, { ...grant, grant_id: "g2", status: "REVOKED", credential_fingerprint: "old-fingerprint" }] } }, new URLSearchParams());
    assert.equal((html.match(/class="cli-client-node"/g) || []).length, 1);
    assert.equal((html.match(/class="cli-project-node"/g) || []).length, 1);
    assert.ok(html.includes('aria-expanded="false"'));
    assert.ok(html.includes(locale === "en" ? "Add project" : "添加项目"));
    assert.ok(html.includes("first-fingerprint"));
    assert.ok(html.includes("old-fingerprint"));
    assert.ok(html.includes(locale === "en" ? "Revoked" : "已撤销"));
  }
});
test("root archives render bilingual explicit upload, optional children and original version controls", () => {
  for (const locale of ["en", "zh"]) {
    const html = renderPage("app/archives/[taskId]/page.tsx", locale, { "archive-task": { task, subtasks: [], publications: [], submission_history: [], management_history: [] }, "archive-snapshot": { ...task, assets: [] }, "archive-actors": { items: [] } });
    assert.ok(html.includes(`Project ID: ${p}`)); assert.ok(html.includes(`Task ID: ${taskId}`)); assert.equal(html.includes("Subtask ID:"), false);
    assert.ok(html.includes(locale === "en" ? "Copy archive prompt" : "复制归档 Prompt"));
    assert.ok(html.includes("SSL_CERT_FILE"));
    assert.ok(html.includes(locale === "en" ? "Task root (no Subtask ID)" : "任务根空间（无需子任务 ID）"));
    assert.ok(html.includes(locale === "en" ? "Optional subtasks" : "可选子任务"));
    assert.ok(html.includes('id="archive-version"')); assert.equal(html.includes("hypertest_bind_task"), false);
    assert.ok(html.includes(`/cli-authorizations?projectId=${p}#cli-install`));
    assert.ok(html.includes(locale === "en" ? "CLI installation prompt &amp; authorization" : "CLI 安装 Prompt 与授权"));
  }
});
test("CLI authorization page supports explicit project approval without secret fields or shell-injected query text", () => {
  assert.equal(release.cliInstallCommand({ published: false }), null);
  assert.ok(release.cliInstallCommand().includes(release.CLI_RELEASE.artifactSha256));
  const published = { published: true, version: "0.1.0", sourceCommit: "a".repeat(40), releaseUrl: "https://example.invalid/cli-v0.1.0", installerUrl: "https://example.invalid/install-cli-release.py", artifactUrl: "https://example.invalid/hypertest-cli-0.1.0.pyz", installerSha256: "b".repeat(64), artifactSha256: "c".repeat(64) };
  const command = release.cliInstallCommand(published);
  assert.ok(command.includes("python3 -I -c")); assert.ok(command.includes(published.installerSha256)); assert.ok(command.includes(published.artifactSha256));
  assert.ok(command.indexOf("Installer SHA-256 mismatch") < command.indexOf("exec(compile"));
  assert.equal(command.includes("curl"), false);
  assert.throws(() => release.cliInstallCommand({ ...published, version: "0.1.0;malicious" }), /METADATA_INVALID/);
  const request = { request_id: taskId, status: "PENDING", client_name: "Synthetic CLI", server_url: "https://web.example", short_code: "ABC123", credential_fingerprint: "a".repeat(16), expires_at: "2026-10-27T23:00:00Z", approval: null, grants: [] };
  for (const locale of ["en", "zh"]) {
    const html = renderPage("app/cli-authorizations/page.tsx", locale, { "archive-web-setup": { configured: true }, "cli-request": request, projects: [{ id: p, name: "Synthetic Project" }], "cli-grants": { items: [] } }, new URLSearchParams({ request_id: taskId, projectId: "$(touch /tmp/forbidden)" }));
    assert.ok(html.includes("ABC123")); assert.ok(html.includes("archive:read")); assert.ok(html.includes("archive:write"));
    assert.ok(html.includes("hypertest skill install --global --host codex"));
    assert.ok(html.includes(release.CLI_RELEASE.artifactUrl));
    assert.equal(html.includes("$(touch"), false); assert.equal(/type="password"|name="token"|Operator-Key/.test(html), false);
    assert.ok(html.includes(locale === "en" ? "Approve CLI" : "批准 CLI"));
    assert.equal(html.includes(locale === "en" ? "Existing uploader identity" : "既有上传身份"), false);
    assert.equal(html.includes("actor_identity_id"), false);
    assert.ok(html.includes('id="cli-install"'));
    assert.ok(html.includes(locale === "en" ? "Copy installation prompt" : "复制安装 Prompt"));
    assert.ok(html.includes(locale === "en" ? "Manual installation and binding" : "手动安装与绑定"));
    assert.match(html, /<textarea[^>]+readOnly=""/);
    assert.ok(html.includes('<details class="cli-install-manual">'), "manual commands stay in the collapsed secondary section");
    const manual = html.slice(html.indexOf('<details class="cli-install-manual">'), html.indexOf("</section>"));
    assert.ok(manual.includes(locale === "en" ? "PENDING with exit code 4" : "PENDING 和退出码 4"));
    assert.ok(manual.includes(locale === "en" ? "Keep the original request_id" : "请保留原 request_id"));
    assert.ok(manual.includes("hypertest auth bind --resume --request-id"));
  }
});
