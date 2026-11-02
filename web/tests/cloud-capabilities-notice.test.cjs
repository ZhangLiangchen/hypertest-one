const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");

const i18n = load("lib/i18n.tsx", { require });
const { CloudCapabilitiesNotice } = load("app/projects/[projectId]/cloud/cloud-shared.tsx", {
  require: (name) => name === "@/lib/i18n" ? i18n
    : name === "@/lib/cloud-recovery" ? load("lib/cloud-recovery.ts")
      : name === "next/link" ? { default: ({ children, ...props }) => React.createElement("a", props, children) }
        : require(name),
});

const configured = {
  enabled: true,
  worker_enabled: true,
  supported: { root_agent: true, codex_delegation: true, claude_code_delegation: false },
  configuration: { codex_enabled: false },
  admission: { state: "NOT_CHECKED", scope: "PER_ATTEMPT" },
};

function render(capabilities, locale = "en", compact = true) {
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale },
    React.createElement(CloudCapabilitiesNotice, { configured: true, capabilities, compact })));
}

// Limit each assertion to the status belonging to the named agent.
function card(html, name) {
  const index = html.indexOf(name);
  assert.notEqual(index, -1, `no capability card for ${name}`);
  const nextCard = html.indexOf('class="cloud-capability-agent"', index);
  const details = html.indexOf('<details', index);
  return html.slice(index, nextCard === -1 ? details : nextCard);
}

test("Cloud capability dashboard renders actual API support and configuration in both locales", () => {
  for (const [locale, labels] of Object.entries({
    en: ["Adapted", "Implemented · not enabled", "Not supported", "View execution capability details"],
    zh: ["已适配", "已实现 · 未启用", "暂未支持", "查看执行能力说明"],
  })) {
    const html = render(configured, locale);
    for (const [name, tone, status] of [
      ["DeepSeek Harness", "ready", labels[0]], ["Codex", "partial", labels[1]], ["Claude Code", "unavailable", labels[2]],
    ]) {
      assert.match(card(html, name), new RegExp(`cloud-capability-status is-${tone}`));
      assert.ok(card(html, name).includes(status), `${name}: ${status}`);
    }
    assert.ok(html.includes(labels[3]));
    assert.match(html, /<details class="cloud-capabilities-details">/, "details are closed by default");
  }
});

test("Codex indicates enabled only when support and configuration are explicitly enabled", () => {
  let html = render({ ...configured, configuration: { codex_enabled: true } });
  assert.match(card(html, "Codex"), /cloud-capability-status is-ready/);
  assert.ok(card(html, "Codex").includes("Delegation enabled"));
  html = render({ ...configured, configuration: {} });
  assert.match(card(html, "Codex"), /cloud-capability-status is-unknown/);
  assert.ok(card(html, "Codex").includes("Unknown"));
  html = render({ ...configured, supported: { ...configured.supported, codex_delegation: false }, configuration: { codex_enabled: true } });
  assert.match(card(html, "Codex"), /cloud-capability-status is-unavailable/);
});

test("Worker disabled or unknown remains visible outside the collapsed details", () => {
  for (const compact of [true, false]) for (const locale of ["en", "zh"]) for (const worker_enabled of [false, undefined]) {
    const html = render({ ...configured, worker_enabled }, locale, compact);
    const notice = html.indexOf('class="cloud-worker-notice"');
    assert.ok(notice > -1 && notice < html.indexOf('<details'), "worker warning is visible without expanding details");
    assert.ok(html.includes(locale === "en" ? "dispatch requires an enabled worker" : "下发需要启用 Worker"));
  }
});
