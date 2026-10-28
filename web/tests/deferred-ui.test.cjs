const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const load = require("./load-helper.cjs");

function runtime() {
  const slots = []; let cursor = 0, effects = [], changed = false;
  const hooks = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], (value) => { const next = typeof value === "function" ? value(slots[index]) : value; changed ||= !Object.is(next, slots[index]); slots[index] = next; }];
    },
    useEffect(callback, dependencies) {
      const index = cursor++, previous = slots[index];
      if (!previous || dependencies.some((value, offset) => !Object.is(value, previous[offset]))) { slots[index] = dependencies; effects.push(callback); }
    },
  };
  return { hooks, render(component, commit = true) {
    for (let round = 0; round < 8; round++) {
      cursor = 0; effects = []; changed = false;
      const tree = component();
      if (commit) effects.forEach((callback) => callback());
      if (!changed) return tree;
    }
    throw Error("effects must settle");
  } };
}
function nodes(element) {
  if (!element || typeof element !== "object") return [];
  if (Array.isArray(element)) return element.flatMap(nodes);
  return [element, ...["children", "actions"].flatMap((key) => nodes(element.props?.[key]))];
}
const ui = { Alert: "Alert", Button: "Button", Empty: "Empty", Input: Object.assign(() => null, { TextArea: "TextArea" }), Select: "Select", Space: "Space", Table: "Table", Tag: "Tag", Typography: { Title: "Title", Text: "Text", Paragraph: "Paragraph" } };
function i18n(locale) {
  return { useI18n: () => ({ locale: locale.value, setLocale: (value) => { locale.value = value; }, t: (en, zh) => locale.value === "zh" ? zh : en, label: (value) => value, formatDate: (value) => value }), I18nProvider: "I18nProvider" };
}

test("provider theme and query cache retain their identity when language changes", () => {
  const r = runtime(), locale = { value: "en" }; let clients = 0;
  const dependencies = { react: r.hooks, antd: { ConfigProvider: "ConfigProvider" }, "@/lib/i18n": i18n(locale),
    "@ant-design/v5-patch-for-react-19": {}, "antd/locale/zh_CN": { default: { locale: "zh-cn" } }, "antd/locale/en_US": { default: { locale: "en" } },
    "@tanstack/react-query": { QueryClient: class { constructor(options) { clients++; this.options = options; } }, QueryClientProvider: "QueryClientProvider" } };
  const { Providers } = load("app/providers.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const wrapper = Providers({ children: "persistent draft", initialLocale: "en" });
  const render = () => r.render(() => wrapper.props.children.type(wrapper.props.children.props));
  const first = render(), cache = nodes(first).find((node) => node.type === "QueryClientProvider").props.client;
  locale.value = "zh";
  const translated = render();
  assert.equal(translated.props.theme, first.props.theme);
  assert.equal(translated.props.theme.token.motion, false);
  assert.equal(translated.props.theme.token.colorPrimary, "#2563eb");
  assert.equal(translated.props.theme.token.controlHeight, 38);
  assert.notEqual(translated.props.locale, first.props.locale);
  assert.equal(nodes(translated).find((node) => node.type === "QueryClientProvider").props.client, cache);
  assert.equal(clients, 1);
  assert.equal(cache.options.defaultOptions.queries.refetchOnWindowFocus, false);
});

test("ClientModal defers first mounting and retains the same child after close and reopen", () => {
  const r = runtime(), Modal = "DeferredModal", child = React.createElement("input", { defaultValue: "preserved draft" });
  const { ClientModal } = load("app/client-modal.tsx", { require: (name) => name === "react" ? r.hooks : name === "next/dynamic" ? { default: () => Modal } : require(name) });
  let open = false;
  const render = () => r.render(() => ClientModal({ open, forceRender: true, children: child }));
  assert.equal(render(), null, "closed forceRender dialogs stay outside the initial tree");
  open = true;
  const active = render();
  assert.equal(active.type, Modal); assert.equal(active.props.open, true);
  open = false;
  const closed = render();
  assert.equal(closed.type, active.type); assert.equal(closed.key, active.key); assert.equal(closed.props.open, false);
  assert.equal(closed.props.children, child, "the draft subtree remains mounted after first use");
  open = true;
  assert.equal(render().props.children, child);
});

test("guide handlers defer the drawer until requested and preserve it across language changes", () => {
  const r = runtime(), locale = { value: "en" }, Guide = "DeferredGuide";
  const dependencies = { react: r.hooks, antd: ui, "@/lib/i18n": i18n(locale), "next/dynamic": { default: () => Guide }, "next/navigation": { usePathname: () => "/" }, "next/link": { default: "a" }, "@ant-design/icons": {} };
  const { SiteHeader } = load("app/site-header.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const render = () => r.render(SiteHeader);
  const first = render();
  assert.equal(nodes(first).some((node) => node.type === Guide), false);
  nodes(first).find((node) => node.type === ui.Button).props.onClick();
  const active = nodes(render()).find((node) => node.type === Guide);
  assert.equal(active.props.open, true);
  active.props.onClose();
  nodes(render()).find((node) => node.type === ui.Select).props.onChange("zh");
  let tree = render(), closed = nodes(tree).find((node) => node.type === Guide);
  assert.equal(closed.type, active.type); assert.equal(closed.key, active.key); assert.equal(closed.props.open, false);
  assert.equal(nodes(tree).find((node) => node.type === ui.Button).props["aria-label"], "使用指南");
  nodes(tree).find((node) => node.type === ui.Button).props.onClick();
  assert.equal(nodes(render()).find((node) => node.type === Guide).props.open, true);
});

test("dashboard handlers keep the deferred creation component after its first opening", () => {
  const r = runtime(), locale = { value: "en" }, Dialog = "DeferredProjectDialog", projects = [];
  const dependencies = { react: r.hooks, antd: ui, "@/lib/i18n": i18n(locale), "next/dynamic": { default: () => Dialog }, "next/link": { default: "a" }, "@ant-design/icons": {}, "@/lib/api": {},
    "@tanstack/react-query": { useQuery: () => ({ data: projects }) }, "@/app/projects/project-actions": { ProjectActions: "ProjectActions" }, "@/app/workspace-ui": { WorkspaceHeading: "WorkspaceHeading", WorkspaceLoading: "WorkspaceLoading" } };
  const { default: Page } = load("app/page.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const render = () => r.render(Page);
  const first = render();
  assert.equal(nodes(first).some((node) => node.type === Dialog), false);
  nodes(first).find((node) => node.type === ui.Button && node.props.children === "Create project").props.onClick();
  const active = nodes(render()).find((node) => node.type === Dialog);
  assert.equal(active.props.open, true); assert.equal(active.props.projects, projects);
  active.props.onClose(); locale.value = "zh";
  const closed = nodes(render()).find((node) => node.type === Dialog);
  assert.equal(closed.type, active.type); assert.equal(closed.key, active.key); assert.equal(closed.props.open, false);
  nodes(render()).find((node) => node.type === ui.Button && node.props.children === "创建项目").props.onClick();
  assert.equal(nodes(render()).find((node) => node.type === Dialog).props.open, true);
});

test("project list shows both repository addresses without a project branch", () => {
  const r = runtime(), locale = { value: "en" };
  const project = { id: "p1", name: "Project", key: "P1", status: "ACTIVE", repository_url: "https://git.example/sut", test_framework_repository_url: "https://git.example/framework", default_branch: "legacy" };
  const dependencies = { react: r.hooks, antd: ui, "@/lib/i18n": i18n(locale), "next/dynamic": { default: () => "Dialog" }, "next/link": { default: "a" }, "@ant-design/icons": {}, "@/lib/api": {},
    "@tanstack/react-query": { useQuery: () => ({ data: [project] }) }, "@/app/projects/project-actions": { ProjectActions: "ProjectActions" }, "@/app/workspace-ui": { WorkspaceHeading: "WorkspaceHeading", WorkspaceLoading: "WorkspaceLoading" } };
  const { default: Page } = load("app/page.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const table = nodes(r.render(Page)).find((node) => node.type === ui.Table);
  const sut = table.props.columns.find((column) => column.key === "repository");
  const framework = table.props.columns.find((column) => column.key === "framework");
  assert.equal(sut.title, "SUT repository");
  assert.equal(framework.title, "Test framework repository");
  assert.ok(JSON.stringify(sut.render(null, project)).includes(project.repository_url));
  assert.ok(JSON.stringify(framework.render(null, project)).includes(project.test_framework_repository_url));
  assert.equal(JSON.stringify(sut.render(null, project)).includes("legacy"), false);
});

test("extracted project dialog preserves draft, validation and the original creation request", async () => {
  const r = runtime(), locale = { value: "en" }, requests = [], navigations = [], invalidations = [], validations = [];
  const form = { values: { key: " qa_one ", name: "  Project one  ", description: " original description ", repository_url: " https://git.invalid/repo ", test_framework_repository_url: " https://git.invalid/framework " },
    getFieldValue(name) { return this.values[name]; }, setFieldValue(name, value) { this.values[name] = value; }, getFieldsError: () => [{ name: ["name"], errors: ["invalid"] }],
    validateFields: async (names) => { validations.push(names); }, scrollToField() {} };
  const Form = Object.assign(() => null, { Item: "Field", useForm: () => [form], useWatch: (name) => form.values[name] });
  let options, open = true;
  const creation = { isPending: false, isSuccess: false, isError: false, mutate: async (values) => { const project = await options.mutationFn(values); options.onSuccess(project); } };
  const dependencies = { react: r.hooks, antd: { ...ui, Form }, "@/lib/i18n": i18n(locale), "@/app/client-modal": { ClientModal: "Modal" }, "next/link": { default: "a" },
    "next/navigation": { useRouter: () => ({ push: (value) => navigations.push(value) }) }, "@/lib/uuid": { createUuid: () => "synthetic-key" },
    "@/lib/api": { createProject: async (payload) => { requests.push(payload); return { id: "created-project" }; }, errorText: () => "failure" },
    "@tanstack/react-query": { useMutation: (value) => { options = value; return creation; }, useQueryClient: () => ({ setQueryData() {}, invalidateQueries: (query) => invalidations.push(query) }) } };
  const { CreateProjectDialog } = load("app/create-project-dialog.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const render = () => r.render(() => CreateProjectDialog({ open, onClose: () => { open = false; }, projects: [] }));
  const first = render(), before = { ...form.values };
  first.props.onCancel(); locale.value = "zh"; render(); open = true;
  const reopened = render();
  assert.deepEqual(form.values, before);
  assert.equal(reopened.props.title, "创建项目"); assert.equal(reopened.props.forceRender, true);
  assert.ok(validations.length >= 2, "opening and language changes revalidate existing errors");
  await nodes(reopened).find((node) => node.type === Form).props.onFinish(form.values);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{ key: "QA_ONE", name: "Project one", description: "original description", repository_url: "https://git.invalid/repo", test_framework_repository_url: "https://git.invalid/framework" }]);
  assert.deepEqual(navigations, ["/projects/created-project"]);
  assert.equal(invalidations.length, 1);
  creation.isPending = true;
  const pending = render();
  assert.equal(pending.props.closable, false); assert.equal(pending.props.maskClosable, false); assert.equal(pending.props.keyboard, false);
  assert.equal(nodes(pending).find((node) => node.type === Form).props.disabled, true);
});

test("project workspace loads only the current project and archive tasks", async () => {
  const r = runtime(), locale = { value: "en" }, queries = [], requests = [];
  const project = { id: "project-1", name: "Project", key: "P1", status: "ACTIVE" };
  const dependencies = {
    react: r.hooks, antd: ui, "@/lib/i18n": i18n(locale), "next/link": { default: "a" },
    "next/navigation": { useParams: () => ({ projectId: project.id }) }, "@ant-design/icons": {},
    "@/lib/api": { getProject: async (...args) => { requests.push(args); return project; }, errorText: () => "failure" },
    "@tanstack/react-query": { useQuery: (options) => { queries.push(options); return { data: project }; } },
    "./archive-tasks": { ProjectArchiveTasks: "ProjectArchiveTasks" },
    "../project-workspace-heading": { ProjectWorkspaceHeading: "ProjectWorkspaceHeading" },
    "@/app/workspace-ui": { ProjectNavigation: "ProjectNavigation", WorkspaceLoading: "WorkspaceLoading" },
  };
  const { default: Page } = load("app/projects/[projectId]/page.tsx", { require: (name) => name in dependencies ? dependencies[name] : require(name) });
  const tree = r.render(Page);
  assert.equal(JSON.stringify(queries.map(({ queryKey }) => queryKey)), JSON.stringify([["project", project.id]]));
  await queries[0].queryFn();
  assert.deepEqual(requests, [[project.id, true]]);
  assert.ok(nodes(tree).some((node) => node.type === "ProjectArchiveTasks"));
  assert.equal(JSON.stringify(tree).includes("/runs/"), false);
});
