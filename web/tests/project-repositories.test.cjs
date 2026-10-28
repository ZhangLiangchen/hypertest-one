const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const load = require("./load-helper.cjs");

function harness() {
  let mutation, sent;
  const form = { getFieldsError: () => [], getFieldValue: () => "", setFieldValue() {} };
  const Form = Object.assign(() => null, { Item: "field", useForm: () => [form], useWatch: () => undefined });
  const ui = { Alert: "alert", Button: "button", Form, Input: Object.assign(() => null, { TextArea: "textarea" }), Space: "space", Typography: { Paragraph: "paragraph", Text: "text" } };
  const deps = { react: { ...React, useEffect() {} }, antd: ui, "@tanstack/react-query": { useMutation: (options) => { mutation = options; return {}; }, useQueryClient: () => ({}) },
    "next/link": { default: "a" }, "next/navigation": { useRouter: () => ({}) }, "@/lib/api": { createProject: async (payload) => { sent = payload; } },
    "@/app/client-modal": { ClientModal: "modal" }, "@/lib/i18n": { useI18n: () => ({ locale: "en", t: (en) => en }) }, "@/lib/uuid": { createUuid: () => "test-uuid" } };
  const { CreateProjectDialog } = load("app/create-project-dialog.tsx", { require: (name) => name in deps ? deps[name] : require(name) });
  const tree = CreateProjectDialog({ open: true, onClose() {}, projects: [] });
  const nodes = (v) => !v || typeof v !== "object" ? [] : Array.isArray(v) ? v.flatMap(nodes) : [v, ...nodes(v.props?.children)];
  return { tree, nodes, get mutation() { return mutation; }, get sent() { return sent; } };
}

test("project creation requests both repositories and selects no project branch", async () => {
  const h = harness();
  const fields = h.nodes(h.tree).filter((node) => node.type === "field");
  const sut = fields.find((node) => node.props.name === "repository_url");
  const framework = fields.find((node) => node.props.name === "test_framework_repository_url");
  assert.ok(sut.props.rules.some((rule) => rule.required));
  assert.ok(framework.props.rules.some((rule) => rule.required));
  assert.equal(fields.some((node) => node.props.name === "default_branch"), false);
  await h.mutation.mutationFn({ key: " demo ", name: " Demo ", repository_url: " https://git.example/sut ", test_framework_repository_url: " https://git.example/sut " });
  assert.equal(JSON.stringify(h.sent), JSON.stringify({ key: "DEMO", name: "Demo", repository_url: "https://git.example/sut", test_framework_repository_url: "https://git.example/sut" }));
});
