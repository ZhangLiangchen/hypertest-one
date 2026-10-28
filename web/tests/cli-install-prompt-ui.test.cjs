const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const load = require("./load-helper.cjs");

function harness(clipboard, options = {}) {
  const { locale = "en", origin = "https://hypertest.example", props = {} } = options;
  const slots = []; let cursor = 0, effects = [], changed = false;
  const requested = [];
  const hooks = { ...React, useId: () => "install-prompt", useState(initial) {
    const index = cursor++;
    if (!(index in slots)) slots[index] = initial;
    return [slots[index], (value) => { changed ||= !Object.is(value, slots[index]); slots[index] = value; }];
  }, useEffect(callback, deps) {
    const index = cursor++, prior = slots[index];
    if (!prior || deps.some((value, offset) => !Object.is(value, prior[offset]))) { slots[index] = deps; effects.push(callback); }
  } };
  const component = load("app/cli-authorizations/cli-install-prompt.tsx", {
    window: { location: { origin } }, navigator: { clipboard },
    require: (name) => name === "react" ? hooks : name === "antd" ? { Alert: "Alert", Button: "Button", Space: "Space", Typography: { Paragraph: "Paragraph" } }
      : name === "@/lib/i18n" ? { useI18n: () => ({ locale, t: (en, zh) => locale === "zh" ? zh : en }) }
        : name === "@/lib/cli-install-prompt" ? { cliInstallPrompt: (values) => { requested.push(values); return `Install prompt: ${values.server || "generic"} ${values.projectId}`; },
          cliServerOrigin: (configured, site) => [configured, site].map((value) => {
            if (!value) return undefined;
            try { const parsed = new URL(value); return parsed.protocol === "https:" ? parsed.origin : undefined; } catch { return undefined; }
          }).find(Boolean) } : require(name),
  });
  return { requested, render() {
    for (let round = 0; round < 5; round++) {
      cursor = 0; effects = []; changed = false;
      const tree = component.CliInstallPrompt({ projectId: "00000000-0000-4000-8000-000000000001", ...props });
      effects.forEach((callback) => callback());
      if (!changed) return tree;
    }
    throw Error("effects did not settle");
  } };
}
function nodes(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
test("copying the install prompt uses the active site and project without starting installation", async () => {
  const copied = [], h = harness({ writeText: async (value) => copied.push(value) });
  const tree = h.render();
  assert.equal(copied.length, 0);
  assert.equal(h.requested.at(-1).server, "https://hypertest.example");
  await nodes(tree).find((node) => node.type === "Button").props.onClick();
  await new Promise(setImmediate);
  const final = nodes(h.render());
  assert.deepEqual(copied, ["Install prompt: https://hypertest.example 00000000-0000-4000-8000-000000000001"]);
  assert.equal(final.find((node) => node.props?.role === "status").props.children, "Copied. Paste it into your local Agent conversation.");
  assert.equal(final.find((node) => node.type === "details").props.open, false);
});
test("a deployment-configured CLI origin replaces the plain-HTTP site address", () => {
  const h = harness({ writeText: async () => {} }, { origin: "http://10.66.66.3:3000", props: { server: "https://localhost:18444" } });
  const tree = h.render();
  assert.equal(h.requested.at(-1).server, "https://localhost:18444");
  assert.equal(nodes(tree).find((node) => node.type === "Alert"), undefined);
});
test("a plain-HTTP site without a configured origin still prepares the generic prompt instead of failing", () => {
  const h = harness({ writeText: async () => {} }, { origin: "http://10.66.66.3:3000" });
  const tree = h.render();
  assert.equal(h.requested.at(-1).server, undefined);
  assert.equal(nodes(tree).find((node) => node.type === "Alert"), undefined);
  assert.ok(nodes(tree).find((node) => node.type === "Button"), "the copy action stays available");
});
test("clipboard denial exposes a read-only prompt for manual copy with bilingual feedback", async () => {
  for (const locale of ["en", "zh"]) {
    const h = harness({ writeText: async () => { throw Error("permission denied"); } }, { locale });
    await nodes(h.render()).find((node) => node.type === "Button").props.onClick();
    await new Promise(setImmediate);
    const result = nodes(h.render());
    assert.equal(result.find((node) => node.type === "details").props.open, true);
    assert.equal(result.find((node) => node.type === "Alert").props.message, locale === "en" ? "Clipboard access failed" : "无法写入剪贴板");
    const area = result.find((node) => node.type === "textarea");
    assert.equal(area.props.readOnly, true);
    assert.ok(area.props.value.includes("https://hypertest.example"));
    let selected = false;
    area.props.onFocus({ currentTarget: { select() { selected = true; } } });
    assert.equal(selected, true);
  }
});
