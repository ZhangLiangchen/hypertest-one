const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");
const i18n = load("lib/i18n.tsx", { require });
const entry = { id: "entry-a", project_id: "project-a", version: 3, status: "PUBLISHED", title: "<script>private()</script> 原始经验", content: "Selected lesson", applicability: "Framework v1" };

function component({ unavailable = false, pending = false } = {}) {
  const project = { data: { name: "Project A", deleted_at: null }, isSuccess: true, isError: false };
  const records = { data: { enabled: true, configuration: { enabled: true, version: 1 }, entries: [entry], operations: [] }, isPending: false, isError: unavailable, refetch() {} };
  const operation = { ready: true, busy: false, blocked: pending, pending: pending ? { operation: "PUBLISH", operation_key: "original-key", state: "UNKNOWN" } : null, submit() {}, reconcile() {} };
  return load("app/projects/[projectId]/memory/memory-workspace.tsx", { Date, require: (name) => name === "@/lib/i18n" ? i18n
    : name === "@/lib/api" ? {} : name === "@/lib/memory" ? {} : name === "@/lib/memory-operation" ? { useMemoryOperation: () => operation }
      : name === "@tanstack/react-query" ? { useQuery: ({ queryKey }) => queryKey[0] === "project" ? project : queryKey[0] === "memory" ? records : { data: { configured: true } }, useMutation: () => ({ reset() {} }) }
        : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) } : require(name) });
}

test("Experience workspace is bilingual, keeps loaded records when unavailable and treats reference text as untrusted", () => {
  for (const locale of ["en", "zh"]) {
    const { MemoryWorkspace } = component({ unavailable: true, pending: true });
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(MemoryWorkspace, { projectId: "project-a" })));
    for (const text of locale === "en" ? ["Project experience", "Project experience is unavailable", "Historical reference", "Query original receipt", "Private candidates", "original-key", "Separate"] .filter((value) => value !== "Separate") : ["项目经验", "项目经验暂不可用", "历史参考", "查询原回执", "私有候选", "original-key"]) assert.ok(html.includes(text), text);
    assert.ok(html.includes("&lt;script&gt;private()&lt;/script&gt;")); assert.equal(html.includes("<script>private()"), false);
    assert.ok(html.includes(locale === "en" ? "Task synchronization remains available" : "任务同步仍可继续"));
    assert.equal(html.includes("RELEASE_READY"), false);
  }
});

function editorHarness(editor) {
  const values = [], jsx = (type, props) => ({ type, props });
  const form = { scrollToField() {} }, Form = Object.assign(() => null, { Item: "Form.Item", useForm: () => [form], useWatch: () => "LOCAL" });
  const ui = Object.fromEntries(["Alert", "Button", "Checkbox", "Descriptions", "Empty", "InputNumber", "Skeleton", "Space", "Table", "Tabs", "Tag"].map((name) => [name, name]));
  Object.assign(ui, { Form, Input: { TextArea: "Input.TextArea" }, Radio: { Group: "Radio.Group" }, Typography: { Title: "Title", Paragraph: "Paragraph", Text: "Text" } });
  const { MemoryEditor } = load("app/projects/[projectId]/memory/memory-workspace.tsx", { Date, require: (name) => name === "react/jsx-runtime" ? { jsx, jsxs: jsx, Fragment: "Fragment" }
    : name === "antd" ? ui : name === "@/lib/i18n" ? { useI18n: () => ({ t: (en) => en }) }
      : ["@/lib/api", "@/lib/memory", "@/lib/memory-operation", "@tanstack/react-query"].includes(name) ? {} : name === "next/link" ? { default: "Link" } : require(name) });
  const nodes = (tree) => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
  const tree = MemoryEditor({ editor, blocked: false, busy: false, onSubmit: async (value) => { values.push(value); return true; }, onClose() {} });
  return { values, form: nodes(tree).find((node) => node.type === Form), nodes: nodes(tree) };
}

test("Candidate form submits only explicitly selected accepted source and lesson", async () => {
  const current = editorHarness({ action: "CREATE_CANDIDATE" });
  await current.form.props.onFinish({ mode: "LOCAL", task_id: "task-a", task_version: 7, report_id: "report-a", title: "Selected", content: "Lesson", applicability: "v1", transcript: "never selected" });
  const request = current.values[0]; assert.equal(request.operation, "CREATE_CANDIDATE"); assert.equal(request.expected_version, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(request.source)), { mode: "LOCAL", task_id: "task-a", task_version: 7, report_id: "report-a" });
  assert.equal(JSON.stringify(request).includes("transcript"), false);
});

test("Human publication and revision use edited text, fixed original version and explicit review confirmation", async () => {
  for (const action of ["PUBLISH", "REVISE"]) {
    const current = editorHarness({ action, entry });
    const review = current.nodes.find((node) => node.type === "Form.Item" && node.props.name === "reviewed");
    await assert.rejects(review.props.rules[0].validator(undefined, false), /Confirm your review/);
    await review.props.rules[0].validator(undefined, true);
    await current.form.props.onFinish({ title: "Redacted title", content: "Reviewed safe lesson", publication_note: "Sensitive values removed", reviewed: true, applicability: "v2", report_id: "private-report" });
    const request = current.values[0]; assert.equal(request.operation, action); assert.equal(request.expected_version, 3); assert.equal(request.entry_id, "entry-a");
    assert.equal(request.content, "Reviewed safe lesson"); assert.equal(request.source, undefined); assert.equal(JSON.stringify(request).includes("private-report"), false);
  }
});

test("Withdrawal sends a new revision intention and preserves original lesson text", async () => {
  const original = JSON.stringify(entry), current = editorHarness({ action: "RETRACT", entry });
  await current.form.props.onFinish({ publication_note: "Outdated", reviewed: true });
  assert.deepEqual(JSON.parse(JSON.stringify(current.values[0])), { operation: "RETRACT", expected_version: 3, entry_id: "entry-a", publication_note: "Outdated" });
  assert.equal(JSON.stringify(entry), original);
});
