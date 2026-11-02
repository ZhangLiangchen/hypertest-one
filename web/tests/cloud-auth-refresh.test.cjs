const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

function page(authQueryState = {}) {
  const queries = {}, reads = [];
  const jsx = (type, props) => ({ type, props });
  const t = (english) => english;
  const values = {
    "cloud-web-setup": { configured: true },
    "cloud-capabilities": { enabled: true, worker_enabled: true },
    "cloud-agent-auth-status": { agents: { deepseek: { status: "VALID", checked_at: "2026-11-02T02:00:00Z" } } },
    "cloud-config": { items: [] },
    "cloud-credentials": { credentials: [], versions: [] },
    "cloud-directory": { total: 0, items: [] },
    project: { id: "project-1" },
  };
  const component = load("app/projects/[projectId]/cloud/page.tsx", { URLSearchParams, require: (name) => {
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "react") return { useState: (value) => [value, () => {}], useEffect: () => {} };
    if (name === "next/navigation") return { useParams: () => ({ projectId: "project-1" }), useSearchParams: () => new URLSearchParams() };
    if (name === "next/dynamic") return { __esModule: true, default: () => "CloudResources" };
    if (name === "next/link") return { __esModule: true, default: "Link" };
    if (name === "@tanstack/react-query") return { useQuery: (options) => {
      const key = options.queryKey[0]; queries[key] = options;
      return { data: values[key], isLoading: false, isError: false, isSuccess: true, refetch: () => reads.push(key), ...(key === "cloud-agent-auth-status" ? authQueryState : {}) };
    } };
    if (name === "@/lib/cloud") return { cloudAgentAuthStatus() {}, cloudCapabilities() {}, cloudConfiguration() {}, cloudCredentials() {}, cloudDirectory() {}, cloudProgressTone() {}, cloudSetup() {} };
    if (name === "@/lib/api") return { getProject() {} };
    if (name === "@/lib/cloud-operation") return { useCloudOperation: () => ({}) };
    if (name === "@/lib/i18n") return { useI18n: () => ({ t, label: t, formatDate: t }) };
    if (name === "@/app/tasks/task-records") return { ReportedResultTag: "ReportedResultTag" };
    if (name === "@/app/workspace-ui") return { ProjectNavigation: "ProjectNavigation", WorkspaceLoading: "WorkspaceLoading" };
    if (name === "../../project-workspace-heading") return { ProjectWorkspaceHeading: "ProjectWorkspaceHeading" };
    if (name === "./cloud-shared") return { CloudCapabilitiesNotice: "CloudCapabilitiesNotice", CloudOperationNotice: "CloudOperationNotice" };
    if (name === "@ant-design/icons") return { ReloadOutlined: "ReloadOutlined" };
    if (name === "antd") return { Alert: "Alert", Button: "Button", Empty: "Empty", Table: "Table", Tabs: "Tabs", Tag: "Tag", Typography: { Title: "Title" } };
    return require(name);
  } });
  const tree = component.default();
  const nodes = (value) => {
    if (!value || typeof value !== "object") return [];
    if (Array.isArray(value)) return value.flatMap(nodes);
    return [value, ...Object.values(value.props || value).flatMap(nodes)];
  };
  const all = nodes(tree);
  return { queries, reads, notice: all.find((entry) => entry.type === "CloudCapabilitiesNotice"), refresh: all.find((entry) => entry.type === "Button" && entry.props.children === "Refresh") };
}

test("Authentication status refreshes every 30 seconds and on window focus", () => {
  const view = page();
  assert.equal(view.queries["cloud-agent-auth-status"].refetchInterval, 30_000);
  assert.equal(view.queries["cloud-agent-auth-status"].refetchIntervalInBackground, false);
  assert.equal(view.queries["cloud-agent-auth-status"].refetchOnWindowFocus, "always");
  assert.equal(view.notice.props.authStatus.agents.deepseek.status, "VALID");
  view.refresh.props.onClick();
  assert.ok(view.reads.includes("cloud-agent-auth-status"), "manual refresh also reloads authentication");
});

test("Failed and pending authentication refresh never show cached valid state", () => {
  for (const state of [{ isError: true }, { isFetching: true }]) {
    const view = page(state);
    assert.equal(view.notice.props.authStatus, undefined);
    assert.equal(view.notice.props.capabilities.enabled, true, "adaptation remains visible");
  }
});
