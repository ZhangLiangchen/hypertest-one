const assert = require("node:assert/strict");
const test = require("node:test");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load-helper.cjs");

const i18n = load("lib/i18n.tsx", { require });
const { CloudCapabilitiesNotice, cloudAuthObservationStatus } = load("app/projects/[projectId]/cloud/cloud-shared.tsx", {
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

function render(capabilities, locale = "en", compact = true, authStatus) {
  return renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale },
    React.createElement(CloudCapabilitiesNotice, { configured: true, capabilities, compact, authStatus })));
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

test("Authentication status is separate from integration and handles unknown or unavailable responses", () => {
  const checked_at = new Date(Date.now() - 5_000).toISOString();
  const auth = { agents: { deepseek: { status: "VALID", checked_at }, codex: { status: "INVALID", checked_at }, claude_code: { status: "NOT_SUPPORTED", checked_at: null } } };
  for (const [locale, labels] of Object.entries({ en: ["Authentication", "Valid", "Invalid", "Not supported", "Unconfirmed"], zh: ["认证", "有效", "无效", "暂不支持", "未确认"] })) {
    const html = render(configured, locale, true, auth);
    for (const [name, tone, label] of [["DeepSeek Harness", "ready", labels[1]], ["Codex", "unavailable", labels[2]], ["Claude Code", "unknown", labels[3]]]) {
      assert.ok(card(html, name).includes(labels[0]));
      assert.match(card(html, name), new RegExp(`cloud-capability-auth-state is-${tone}`));
      assert.ok(card(html, name).includes(label));
    }
    assert.ok(card(html, "DeepSeek Harness").includes(`dateTime="${checked_at}"`));
    const unknown = render(configured, locale, true, undefined);
    assert.match(card(unknown, "DeepSeek Harness"), /cloud-capability-status is-ready/);
    assert.match(card(unknown, "DeepSeek Harness"), /cloud-capability-auth-state is-unknown/);
    assert.ok(card(unknown, "DeepSeek Harness").includes(labels[4]));
    const explicitUnknown = render(configured, locale, true, { agents: { ...auth.agents, deepseek: { status: "UNKNOWN", checked_at: null } } });
    assert.ok(card(explicitUnknown, "DeepSeek Harness").includes(labels[4]));
  }
});

test("Authentication observations expire rather than showing a stale green or red light", () => {
  const observed = Date.parse("2026-11-02T12:00:00Z");
  for (const status of ["VALID", "INVALID"]) {
    const entry = { status, checked_at: "2026-11-02T12:00:00Z" };
    assert.equal(cloudAuthObservationStatus(entry, observed + 179_999), status);
    assert.equal(cloudAuthObservationStatus(entry, observed + 180_000), "UNKNOWN");
    assert.equal(cloudAuthObservationStatus(entry, observed - 1), "UNKNOWN");
    assert.equal(cloudAuthObservationStatus({ ...entry, checked_at: null }, observed), "UNKNOWN");
  }
  assert.equal(cloudAuthObservationStatus({ status: "NOT_SUPPORTED", checked_at: null }, observed), "NOT_SUPPORTED");
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
