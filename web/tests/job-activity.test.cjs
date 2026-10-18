const assert = require("node:assert/strict");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");
const helper = loadHelper("lib/job-activity.ts");
const { activityTiming, emptyActivityFeed, reconcileActivity, serverElapsed, visibleActivityItems } = helper;
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const now = "2026-10-18T12:10:00Z";
const stamp = (n) => new Date(Date.parse("2026-10-18T12:00:00Z") + n * 1000).toISOString();
const item = (n, extra = {}) => ({ id: id(n), kind: "MODEL_ACTIVITY", source: "PROVIDER", recorded_at: stamp(n), last_observed_at: stamp(n), count: 1, mission_id: id(901), attempt_id: id(902), agent_session_id: id(903), ...extra });
const page = (items = [], extra = {}) => ({ job_id: id(900), server_time: now, summary: { phase: "AGENT_RUNNING", current_attempt: { mission_id: id(901), mission_key: "MIS-EXAMPLE", mission_type: "ANALYZE_RISKS", attempt_id: id(902), attempt_no: 1, agent_session_id: id(903) }, turn_started_at: "2026-10-18T12:00:00Z", last_provider_signal_at: "2026-10-18T12:01:00Z", provider_signal_age_seconds: 540, worker_heartbeat_at: "2026-10-18T12:09:58Z", worker_heartbeat_age_seconds: 2 }, items, next_cursor: null, retention_per_attempt: 200, window_seconds: 2, truncated: false, ...extra });

test("quiet timing uses the server clock and keeps provider silence separate from worker heartbeats", () => {
  const result = activityTiming({ status: "RUNNING" }, page(), false);
  assert.equal(result.signalAge, 540);
  assert.equal(result.heartbeatAge, 2);
  assert.equal(result.quiet, true);
  assert.equal(serverElapsed(now, "2026-10-18T12:09:00Z"), 60);
  assert.equal(serverElapsed(now, "2026-10-18T12:11:00Z", 0), null);
  assert.equal(serverElapsed("bad", now), null);
  assert.equal(serverElapsed(now, null, 1000), null);
});

test("waiting, terminal, queued, cancelling and failed refreshes never produce a silence warning", () => {
  for (const status of ["WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED", "QUEUED", "CANCEL_REQUESTED"]) {
    assert.equal(activityTiming({ status }, page(), false).quiet, false, status);
  }
  for (const phase of ["QUEUED", "WAITING_INPUT", "CANCEL_REQUESTED", "RESULT_VALIDATION", "PLATFORM_WORK", "TERMINAL", "unknown-provider-text"]) {
    const activity = page(); activity.summary.phase = phase;
    assert.equal(activityTiming({ status: "RUNNING" }, activity, false).quiet, false, phase);
  }
  assert.equal(activityTiming({ status: "RUNNING" }, page(), true).quiet, false);
});

test("a new claim with no signal uses only its supplied turn start and leaves unknown timing neutral", () => {
  const activity = page();
  activity.summary.last_provider_signal_at = null;
  activity.summary.provider_signal_age_seconds = null;
  assert.equal(activityTiming({ status: "RUNNING" }, activity, false).quiet, true);
  activity.summary.turn_started_at = "2026-10-18T12:09:00Z";
  assert.equal(activityTiming({ status: "RUNNING" }, activity, false).quiet, false);
  activity.summary.turn_started_at = null;
  assert.equal(activityTiming({ status: "RUNNING" }, activity, false).quiet, false);
});

test("the projection excludes unknown kinds and all provider text while preserving safe record identity", () => {
  const rows = visibleActivityItems([item(1, { payload: { command: "SECRET_COMMAND" }, message: "SECRET_REASONING" }), item(2, { kind: "SECRET_UNKNOWN_KIND" }), item(3, { source: "SECRET_UNKNOWN_SOURCE" }), item(4, { mission_id: "SECRET_NON_UUID" }), item(5, { count: -1 })]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].mission_id, id(901));
  assert.equal(JSON.stringify(rows).includes("SECRET"), false);
  assert.equal(Object.keys(rows[0]).length, 9);
});

test("polling and older-page reconciliation retain each bucket's newest count and observation", () => {
  let feed = reconcileActivity(emptyActivityFeed(), page([item(3), item(2)], { next_cursor: id(2) }), "head");
  feed = reconcileActivity(feed, page([item(2, { count: 7, last_observed_at: stamp(20) }), item(1)], { next_cursor: null }), "older");
  feed = reconcileActivity(feed, page([item(4), item(3), item(2, { count: 2, last_observed_at: stamp(4) })], { server_time: "2026-10-18T12:10:02Z", next_cursor: id(2) }), "head");
  assert.equal(feed.items.map((row) => row.id).join(","), [4, 3, 2, 1].map(id).join(","));
  assert.equal(feed.items.find((row) => row.id === id(2)).count, 7);
  assert.equal(feed.items.find((row) => row.id === id(2)).last_observed_at, stamp(20));
  assert.equal(feed.nextCursor, null);
  const late = reconcileActivity(feed, page([item(6)], { server_time: "2026-10-18T12:09:59Z" }), "head");
  assert.equal(late, feed);
});

test("a missed head window rewinds pagination without dropping previously loaded records", () => {
  let feed = reconcileActivity(emptyActivityFeed(), page([item(2), item(1)], { next_cursor: id(1) }), "head");
  feed = reconcileActivity(feed, page([item(6), item(5)], { next_cursor: id(5), server_time: "2026-10-18T12:10:02Z" }), "head");
  assert.equal(feed.items.length, 4);
  assert.equal(feed.nextCursor, id(5));
  feed = reconcileActivity(feed, page([item(4), item(3), item(2)], { next_cursor: id(2) }), "older");
  assert.equal(feed.items.length, 6);
  assert.equal(feed.nextCursor, id(2));
});

test("an earlier-page response arriving after a new head gap cannot skip that gap", () => {
  let feed = reconcileActivity(emptyActivityFeed(), page([item(2), item(1)], { next_cursor: id(1) }), "head");
  const inFlightCursor = feed.nextCursor;
  feed = reconcileActivity(feed, page([item(6), item(5)], { next_cursor: id(5), server_time: "2026-10-18T12:10:02Z" }), "head");
  feed = reconcileActivity(feed, page([item(0)], { next_cursor: null }), "older", inFlightCursor);
  assert.equal(feed.items.length, 5);
  assert.equal(feed.nextCursor, id(5));
});

test("activity browsing is bounded and only a successful explicit reset discards loaded history", () => {
  const loaded = page(Array.from({ length: 310 }, (_, index) => item(index + 1)), { next_cursor: id(1), truncated: true });
  const feed = reconcileActivity(emptyActivityFeed(), loaded, "head");
  assert.equal(feed.items.length, 300);
  assert.equal(feed.items.at(-1).id, id(11));
  assert.equal(feed.atLimit, true);
  assert.equal(feed.truncated, true);
  const reset = reconcileActivity(feed, page([item(312)], { next_cursor: id(312) }), "reset");
  assert.equal(reset.items.length, 1);
  assert.equal(reset.atLimit, false);
  assert.equal(feed.items.length, 300);
});

test("the readonly API requests a bounded page and encoded cursor without writing a job", async () => {
  const requests = [];
  const { getJobActivity } = loadHelper("lib/api.ts", { URLSearchParams, fetch: async (url, init) => {
    requests.push({ url, init });
    return new Response(JSON.stringify(page()), { status: 200 });
  } });
  const controller = new AbortController();
  await getJobActivity(id(900), id(30), controller.signal);
  assert.equal(requests[0].url, `/api/v1/jobs/${id(900)}/activity?limit=30&before=${id(30)}`);
  assert.equal(requests[0].init.signal, controller.signal);
  assert.equal(requests[0].init.body, undefined);
  assert.equal(requests[0].init.method, undefined);
});

test("the actual activity view never renders raw provider fields or unknown kinds in either language", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const i18n = loadHelper("lib/i18n.tsx", { require });
  const { JobActivityView } = loadHelper("app/runs/[runId]/job-activity.tsx", { require: (name) => name === "@/lib/i18n" ? i18n : name === "@/lib/job-activity" ? helper : name === "./use-job-activity" ? {} : require(name) });
  const activity = page([item(1, { payload: "SECRET_COMMAND", reasoning: "SECRET_REASONING" }), item(2, { kind: "SECRET_UNKNOWN_KIND" })]);
  for (const locale of ["en", "zh"]) {
    const html = renderToStaticMarkup(React.createElement(i18n.I18nProvider, { initialLocale: locale }, React.createElement(JobActivityView, { job: { id: id(900), status: "RUNNING" }, activity, feed: { ...emptyActivityFeed(), items: activity.items }, loading: false, refreshing: false, refreshFailed: false, taskStale: false, olderLoading: false, olderFailed: false, cursorExpired: false, onRefresh() {}, onEarlier() {}, onReset() {}, onResults() {} })));
    assert.equal(html.includes("SECRET"), false);
    assert.equal(html.includes(locale === "en" ? "Agent activity signal" : "Agent 活动信号"), true);
    assert.equal(html.includes(locale === "en" ? "Worker heartbeat" : "Worker 心跳"), true);
  }
});
