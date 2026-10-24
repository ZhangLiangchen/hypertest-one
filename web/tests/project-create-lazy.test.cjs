const assert = require("node:assert/strict"), test = require("node:test"), React = require("react");
const load = require("./load-helper.cjs");
const env = load("lib/execution-environment.ts");
const draft = load("lib/run-draft.ts", { require: () => env });
const project = { id: "00000000-0000-4000-8000-000000000001", name: "Project", key: "P-1", default_branch: "main", repository_url: "https://github.com/team/repo" };

// Persistent hook slots exercise handlers and changed dependencies without real
// API calls, models, browser automation or business database fixtures.
function runtime() {
  const slots = []; let cursor, pending, changed;
  return {
    hooks: { ...React,
      useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === "function" ? initial() : initial; return [slots[i], value => { const next = typeof value === "function" ? value(slots[i]) : value; changed ||= !Object.is(slots[i], next); slots[i] = next; }]; },
      useRef(initial) { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
      useEffect(effect, deps) { const i = cursor++, before = slots[i]; if (!before || deps.some((value, index) => !Object.is(value, before[index]))) { slots[i] = deps; pending.push(effect); } },
    },
    render(component) { for (let round = 0; round < 8; round++) { cursor = 0; pending = []; changed = false; const tree = component(); pending.forEach(effect => effect()); if (!changed) return tree; } throw Error("component did not settle"); },
  };
}
function nodes(element) {
  if (!element || typeof element !== "object") return [];
  if (Array.isArray(element)) return element.flatMap(nodes);
  return [element, ...["children", "action", "description", "actions"].flatMap(name => nodes(element.props?.[name]))];
}
const ui = { Alert: "alert", Button: "button", Card: "card", Empty: "empty", Space: "space", Spin: "spin", Steps: "steps", Table: "table", Tag: "tag", Popconfirm: "confirm",
  Input: Object.assign(() => null, { TextArea: "textarea" }), Radio: { Group: "radio" }, Descriptions: Object.assign(() => null, { Item: "description" }), Typography: { Text: "text", Title: "title", Paragraph: "paragraph" } };
function shell(fromRun = null) {
  const r = runtime(), imports = [], DynamicDialog = () => null;
  const deps = {
    react: r.hooks, antd: ui, "next/dynamic": { default: () => DynamicDialog }, "next/link": { default: "a" },
    "next/navigation": { useParams: () => ({ projectId: project.id }), useSearchParams: () => ({ get: () => fromRun }) },
    "@/lib/i18n": { useI18n: () => ({ t: en => en, label: value => value, locale: "en", formatDate: value => value }) },
    "@tanstack/react-query": { useQuery: ({ queryKey }) => ({ data: queryKey[0] === "project" ? project : [] }) },
    "@/lib/api": {}, "./session-tasks": { ProjectSessionTasks: "session-tasks" }, "../project-actions": { ProjectActions: "project-actions" },
    "@/app/workspace-ui": { ProjectNavigation: "navigation", WorkspaceHeading: "heading", WorkspaceLoading: "loading" },
  };
  const { default: Page } = load("app/projects/[projectId]/page.tsx", { require: name => { imports.push(name); return name in deps ? deps[name] : require(name); } });
  return { render: () => r.render(Page), DynamicDialog, imports };
}
function dialog({ copiedInputs, copyError, fromRun = null } = {}) {
  const r = runtime(), requests = [], mutations = [], queries = []; let locale = "en", open = true;
  const form = { values: {}, resetCount: 0, resetFields() { this.resetCount++; this.values = {}; }, setFieldsValue(values) { Object.assign(this.values, values); },
    setFieldValue(name, value) { this.values[name] = value; }, setFields(fields) { for (const f of fields) if ("value" in f) this.values[f.name] = f.value; },
    getFieldValue(name) { return this.values[name]; }, getFieldsValue() { return { ...this.values }; }, getFieldsError() { return []; }, validateFields: async () => {}, scrollToField() {} };
  const Form = Object.assign(() => null, { Item: "field", useForm: () => [form], useWatch: name => form.values[name] });
  const policy = load("app/projects/[projectId]/policy-fields.tsx", { require: name => name === "antd" ? { ...ui, Form } : name === "@/lib/i18n" ? {} : require(name) });
  const query = {
    useQuery(options) { queries.push(options); return options.queryKey[0] === "copy-run-inputs" ? { data: copiedInputs, error: copyError, isError: Boolean(copyError), isPending: !copiedInputs && !copyError } : { data: { profiles: [{ profile_id: "python-pytest-v1", kind: "pytest", network: "none", available: true }] } }; },
    useMutation(options) { const ref = r.hooks.useRef(null); if (!ref.current) { ref.current = { isPending: false, isSuccess: false, isError: false, reset() { this.isError = false; }, mutate(payload) { this.isPending = true; requests.push(payload); } }; mutations.push(ref.current); } ref.current.options = options; return ref.current; },
    useQueryClient: () => ({ setQueryData() {}, invalidateQueries() {} }),
  };
  const onDraftChange = () => {};
  const deps = { react: r.hooks, antd: { ...ui, Form }, "@tanstack/react-query": query, "next/link": { default: "a" }, "next/navigation": { useRouter: () => ({ push() {} }) },
    "@/lib/i18n": { useI18n: () => ({ locale, t: (en, zh) => locale === "en" ? en : zh }) }, "@/lib/api": { errorText: value => String(value || "") }, "@/app/client-modal": { ClientModal: "modal" },
    "@/app/execution-environment": { EnvironmentFields: "environment-fields", EnvironmentRequestSummary: "environment-summary" }, "@/lib/execution-environment": env,
    "@/lib/prd-import": load("lib/prd-import.ts", { TextDecoder }), "@/lib/uuid": { createUuid: () => String(requests.length + 1) }, "@/lib/run-draft": draft, "./policy-fields": policy, "./harness-fields": { HarnessFields: "harness-fields" } };
  const { default: Dialog } = load("app/projects/[projectId]/run-create-dialog.tsx", { TextEncoder, require: name => name in deps ? deps[name] : require(name) });
  const render = () => r.render(() => Dialog({ project, fromRun, createOpen: open, setCreateOpen: value => { open = value; }, onDraftChange }));
  return { render, submit: () => nodes(render()).find(node => node.type === Form).props.onFinish(), submitHandler: () => nodes(render()).find(node => node.type === Form).props.onFinish, form, requests, queries,
    setOpen(value) { open = value; }, setLocale(value) { locale = value; },
    settleFailure() { const m = mutations[1]; m.isPending = false; m.isError = true; m.options.onSettled(); } };
}

test("project reads omit legacy dependencies and retain the dynamic instance after first opening", () => {
  const h = shell(), first = h.render();
  assert.equal(nodes(first).some(node => node.type === h.DynamicDialog), false);
  assert.equal(h.imports.some(name => /policy|harness-fields|execution-environment|prd-import|run-draft/.test(name)), false);
  nodes(first).find(node => node.type === ui.Button && node.props.children === "Create test run").props.onClick();
  const active = nodes(h.render()).find(node => node.type === h.DynamicDialog);
  assert.equal(active.props.createOpen, true);
  active.props.setCreateOpen(false);
  const closed = nodes(h.render()).find(node => node.type === h.DynamicDialog);
  assert.ok(closed); assert.equal(closed.key, active.key); assert.equal(closed.props.createOpen, false);
});

test("fromRun mounts the verifier without automatically replacing a draft or opening creation", () => {
  const h = shell("saved-run"), component = nodes(h.render()).find(node => node.type === h.DynamicDialog);
  assert.equal(component.props.fromRun, "saved-run"); assert.equal(component.props.createOpen, false);
});

test("closing, reopening and language switching preserve form text and the current step", () => {
  const h = dialog(); h.render();
  h.form.setFieldsValue({ source_mode: "sha", commit_sha: "a".repeat(40), prd_text: "  原始需求\r\n", configuration_text: "" });
  h.submit(); h.setOpen(false); h.render(); h.setLocale("zh"); h.render(); h.setOpen(true);
  const tree = h.render();
  assert.equal(h.form.resetCount, 1); assert.equal(h.form.values.prd_text, "  原始需求\r\n"); assert.equal(h.form.values.configuration_text, "");
  assert.equal(nodes(tree).find(node => node.type === ui.Steps).props.current, 1);
  assert.ok(h.queries.some(option => option.queryKey[0] === "execution-environments" && option.enabled === false));
});

test("submission fences repeated handlers and preserves the original key after failure and reopening", () => {
  const h = dialog(); h.render(); h.form.setFieldsValue({ source_mode: "sha", commit_sha: "a".repeat(40), prd_text: " exact\r\n", configuration_text: "" });
  for (let step = 0; step < 4; step++) h.submit();
  const submit = h.submitHandler(); submit(); submit();
  assert.equal(h.requests.length, 1); assert.equal(h.requests[0].prd_text, " exact\r\n"); assert.equal(h.requests[0].configuration_text, "");
  const key = h.requests[0].idempotency_key;
  h.settleFailure(); h.setOpen(false); h.render(); h.setOpen(true); h.render(); h.submit();
  assert.equal(h.requests[1].idempotency_key, key);
  h.settleFailure(); h.form.setFieldsValue({ prd_text: "edited" }); h.submit();
  assert.notEqual(h.requests[2].idempotency_key, key);
});

const copied = { run: { id: "00000000-0000-4000-8000-000000000002", key: "RUN-OLD" }, source: { repository_url: "https://github.com/team/repo", commit_sha: "b".repeat(40), branch: "repair" },
  policy: { compiled_policy: { gate_version: "custom", extra: { retain: "full original" } } }, environment: env.defaultEnvironmentValues(), prd: "\uFEFF原文\r\n  ", configuration: "" };

test("copied inputs require replacement confirmation and preserve full policy and original text", () => {
  const h = dialog({ copiedInputs: copied, fromRun: copied.run.id }); h.render(); h.form.setFieldsValue({ prd_text: "unsaved draft" });
  const before = h.render(); assert.equal(h.form.values.prd_text, "unsaved draft");
  const confirmation = nodes(before).find(node => node.type === ui.Popconfirm); assert.ok(confirmation); confirmation.props.onConfirm();
  assert.equal(h.form.values.prd_text, copied.prd); assert.equal(h.form.values.configuration_text, ""); assert.equal(h.form.values.commit_sha, copied.source.commit_sha); assert.equal(h.form.values.source_mode, "sha");
  for (let step = 0; step < 4; step++) h.submit(); h.submit();
  assert.deepEqual(h.requests[0].policy, copied.policy.compiled_policy); assert.equal(h.requests[0].prd_text, copied.prd);
  nodes(h.render()).find(node => node.type === ui.Popconfirm).props.onConfirm();
  assert.equal(h.form.resetCount, 2, "a pending request cannot be replaced through the copy banner");
});

test("failed verification preserves the active draft and offers retry rather than partial copied inputs", () => {
  const h = dialog({ fromRun: copied.run.id, copyError: new draft.RunDraftError("project") }); h.render(); h.form.setFieldsValue({ prd_text: "keep me" });
  const tree = h.render(); assert.equal(h.form.values.prd_text, "keep me"); assert.equal(nodes(tree).some(node => node.type === ui.Popconfirm), false);
  const notice = nodes(tree).find(node => node.type === ui.Alert && node.props.className === "copy-run-notice");
  assert.equal(notice.props.type, "error"); assert.ok(String(notice.props.description).includes("different project"));
});
