const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

// Exercise the shipped details/pagination handlers and lazy render functions.
// AntD is represented by terminal nodes; the existing session-task tests also
// render the content through real React/AntD in both languages.
function harness(detail, locale = "en") {
  const states = new Map();
  let scope = "", cursor = 0;
  const react = {
    useState(initial) {
      const key = `${scope}:${cursor++}`;
      if (!states.has(key)) states.set(key, initial);
      return [states.get(key), (value) => states.set(key, typeof value === "function" ? value(states.get(key)) : value)];
    },
    useMemo(callback, dependencies) {
      const key = `${scope}:${cursor++}`, previous = states.get(key);
      if (!previous || dependencies.some((value, index) => !Object.is(value, previous.dependencies[index]))) states.set(key, { dependencies, value: callback() });
      return states.get(key).value;
    },
  };
  const jsx = (type, props, key) => ({ type, props, key });
  const ui = Object.fromEntries(["Descriptions", "Empty", "Pagination", "Space", "Table", "Tag"].map((name) => [name, name]));
  ui.Typography = { Title: "Title", Text: "Text", Paragraph: "Paragraph" };
  const { SessionTaskRecords } = load("app/tasks/task-records.tsx", { require(name) {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en, zh) => locale === "zh" ? zh : en, label: (value) => value, formatDate: (value) => value || "—" }) };
    return require(name);
  } });
  function resolve(node, path) {
    if (Array.isArray(node)) return node.map((child, index) => resolve(child, `${path}/${child?.key ?? index}`));
    if (!node || typeof node !== "object") return node;
    if (typeof node.type === "function") {
      const parentScope = scope, parentCursor = cursor;
      scope = `${path}/${node.type.name}`; cursor = 0;
      const child = node.type(node.props);
      scope = parentScope; cursor = parentCursor;
      return resolve(child, `${path}/${node.type.name}`);
    }
    return { ...node, props: { ...node.props, children: resolve(node.props.children, `${path}/children`) } };
  }
  const nodes = (node) => Array.isArray(node) ? node.flatMap(nodes) : !node || typeof node !== "object" ? [] : [node, ...nodes(node.props?.children)];
  const text = (node) => Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : node == null || typeof node === "boolean" ? "" : String(node);
  let tree;
  const render = () => tree = resolve(jsx(SessionTaskRecords, { detail }), "records");
  render();
  return { nodes, text, render, get tree() { return tree; },
    section(id) { return nodes(tree).find((node) => node.props["aria-labelledby"] === id); },
    toggle(summary, open = true) {
      const target = nodes(tree).find((node) => node.type === "details" && text(node.props.children[0]).includes(summary));
      assert.ok(target, `details: ${summary}`);
      const element = { open };
      target.props.onToggle({ target: element, currentTarget: element });
      render();
    },
    page(label, current) {
      const nav = nodes(tree).find((node) => node.type === "nav" && node.props["aria-label"] === label);
      assert.ok(nav, `pagination: ${label}`);
      nodes(nav).find((node) => node.type === "Pagination").props.onChange(current);
      render();
    },
  };
}

function fixture(count = 1) {
  const at = "2026-10-25T02:00:00Z";
  const task = { id: "task-fixed", project_id: "project-fixed", provider: "codex", session_id: "source-session", title: "Accepted task", objective: "Preserve source records", status: "COMPLETED", plan_markdown: "# Plan", reported_result: "FAIL", version: count + 1, source: "AGENT_REPORTED", created_at: at, last_synced_at: at };
  const ids = Array.from({ length: count }, (_, index) => String(index + 1).padStart(3, "0"));
  const cases = ids.map((id, index) => ({ id: `case-${id}`, task_id: task.id, key: `[case-${id}]`, title: `Case ${id}`, steps: ["Project framework output"], expected: "Expected", actual: "Observed failure", reported_result: "FAIL", revision: index + 1, task_version: index + 1, source: "AGENT_REPORTED", created_at: at }));
  const reports = ids.map((id, index) => ({ id: `report-${id}`, task_id: task.id, key: `[report-${id}]`, title: `Report ${id}`, markdown: `# Failure ${id}\n<script>untrusted()</script>\n\nResult: FAIL\n`, source_ref: `reports/${id}.md`, reported_result: "FAIL", revision: index + 1, task_version: index + 1, source: "AGENT_REPORTED", created_at: at }));
  const entries = (kind) => ids.map((id, index) => ({ id: `${kind}-${id}`, action: kind === "bind" ? "BIND" : "UPDATE", actor_ref: `[${kind}-${id}]`, task_version: index + 1, task_snapshot: { ...task, version: index + 1 }, created_at: at }));
  return { task, cases, reports, case_history: cases, report_history: reports, sync_history: entries("sync"), management_history: entries("manage"), binding_history: entries("bind") };
}

test("closed report/history disclosures do not read artifact bodies or serialize snapshots", () => {
  const detail = fixture(45);
  let reportReads = 0, snapshotSerializations = 0;
  for (const report of detail.reports) {
    const original = report.markdown;
    Object.defineProperty(report, "markdown", { get() { reportReads++; return original; } });
  }
  for (const record of [...detail.sync_history, ...detail.management_history, ...detail.binding_history]) record.task_snapshot.toJSON = () => { snapshotSerializations++; return { version: record.task_version, reported_result: "FAIL" }; };
  const view = harness(detail);
  assert.equal(reportReads, 0);
  assert.equal(snapshotSerializations, 0);
  assert.equal(view.text(view.tree).includes("Observed failure"), false);
  view.toggle("Case revision history");
  view.toggle("Report revision history");
  assert.equal(reportReads, 0, "opening a history lists summaries without reading bodies");
  assert.equal(snapshotSerializations, 0);
  view.toggle("Task at this sync");
  assert.equal(snapshotSerializations, 1);
  view.render();
  assert.equal(snapshotSerializations, 1, "an unchanged opened snapshot is not reserialized on rerender");
  view.toggle("Task at this sync", false);
  assert.equal(view.nodes(view.tree).filter((node) => node.type === "pre").length, 1, "closing removes the snapshot, retaining only the plan");
});

test("all report and history pages remain reachable exactly once without mutating accepted ordering", () => {
  const detail = fixture(45), view = harness(detail);
  const idsBefore = detail.reports.map((item) => item.id);
  view.toggle("Case revision history");
  view.toggle("Report revision history");
  const groups = [
    ["task-reports-heading", "Report pages", "report"],
    ["task-cases-heading", "Case history pages", "case"],
    ["task-reports-heading", "Report history pages", "report"],
    ["task-binding-history-heading", "Binding history pages", "bind"],
    ["task-management-heading", "Management history pages", "manage"],
    ["task-sync-heading", "Sync history pages", "sync"],
  ];
  for (const [sectionId, label, kind] of groups) {
    const seen = [];
    for (let page = 1; page <= 3; page++) {
      view.page(label, page);
      let section = view.section(sectionId);
      if (label === "Case history pages" || label === "Report history pages") section = view.nodes(section).find((node) => node.type === "details" && view.text(node.props.children[0]).includes(label === "Case history pages" ? "Case revision history" : "Report revision history"));
      else if (label === "Report pages") section = { props: { children: view.nodes(section).filter((node) => node.type === "details" && node.props.className?.includes("data-surface")) } };
      const pageIds = [...view.text(section).matchAll(new RegExp(`\\[${kind}-(\\d{3})\\]`, "g"))].map((match) => match[1]);
      assert.equal(pageIds.length, page === 3 ? 5 : 20, label);
      seen.push(...pageIds);
    }
    assert.deepEqual(seen, Array.from({ length: 45 }, (_, index) => String(index + 1).padStart(3, "0")), label);
  }
  assert.deepEqual(detail.reports.map((item) => item.id), idsBefore);
});

test("opening current and historical reports preserves exact original text, failure and revision identity", () => {
  for (const locale of ["en", "zh"]) {
    const detail = fixture(2);
    detail.report_history = detail.reports.map((item) => ({ ...item, id: `historical-${item.id}`, title: `Historical ${item.title}`, markdown: `# Historical ${item.markdown}` }));
    detail.reports[1] = { ...detail.reports[1], revision: 99, task_version: 99, reported_result: "PASS", markdown: "A newer report must not replace the accepted historical failure." };
    const view = harness(detail, locale);
    const original = detail.reports[0].markdown;
    view.toggle("Report 001");
    let body = view.nodes(view.tree).find((node) => node.props["aria-label"] === (locale === "en" ? "Original Markdown report" : "原始 Markdown 报告"));
    assert.equal(body.props.children, original);
    assert.equal(view.nodes(view.tree).find((node) => node.type === "Text" && node.props.copyable?.text).props.copyable.text, original);
    assert.ok(view.text(view.tree).includes("FAIL"));
    view.toggle("Report 001", false);
    view.toggle(locale === "en" ? "Report revision history" : "报告修订历史");
    view.toggle("Historical Report 002");
    body = view.nodes(view.tree).find((node) => node.props["aria-label"] === (locale === "en" ? "Original Markdown report" : "原始 Markdown 报告"));
    assert.equal(body.props.children, detail.report_history[1].markdown);
    const content = view.nodes(view.tree).find((node) => node.props.className === "session-report-content");
    assert.ok(view.text(content).includes(locale === "en" ? "Revision 2" : "修订 2"));
    assert.ok(view.text(content).includes(locale === "en" ? "Task version 2" : "任务版本 2"));
    assert.ok(view.text(content).includes("reports/002.md"));
    assert.ok(view.text(content).includes("FAIL"));
    assert.equal(view.text(content).includes("99"), false);
  }
});

test("case history content is created only for the opened revision and remains complete", () => {
  const detail = fixture(45), view = harness(detail);
  let reads = 0;
  Object.defineProperty(detail.case_history[20], "actual", { get() { reads++; return "Original failed observation\nNo truncation"; } });
  view.toggle("Case revision history");
  view.page("Case history pages", 2);
  assert.equal(reads, 0);
  view.toggle("[case-021]");
  assert.equal(reads, 1);
  const content = view.nodes(view.tree).find((node) => node.props.className === "session-case-content");
  assert.ok(view.text(content).includes("Original failed observation\nNo truncation"));
  assert.ok(view.text(content).includes("Project framework output"));
  assert.ok(view.text(content).includes("Revision 21"));
  assert.ok(view.text(content).includes("Task version 21"));
});
