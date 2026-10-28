const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const polling = load("lib/run-polling.ts");

const projectId = "00000000-0000-4000-8000-000000000001";
const taskId = "00000000-0000-4000-8000-000000000002";
const summary = (overrides = {}) => ({ id: taskId, project_id: projectId, version: 7, latest_attempt_id: "attempt-1", current_attempt: { id: "attempt-1", status: "RUNNING" }, status: "RUNNING", resolutions: [], observed_at: "2026-10-25T01:00:00Z", ...overrides });

test("Cloud polls lightweight observations for waiting, recovery and unresolved version resolution", () => {
  for (const status of ["QUEUED", "PREPARING", "RUNNING"]) assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status })), 3000);
  for (const status of ["DRAFT", "WAITING_INPUT", "RECOVERY_REQUIRED", "UNKNOWN", "BLOCKED"]) assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status })), 15000);
  for (const status of ["COMPLETED", "FAILED", "CANCELLED"]) assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status })), false);
  assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status: "DRAFT", resolutions: [{ status: "RESOLVING" }] })), 3000);
  assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status: "CANCELLED", recovery: { phase: "STOP_UNCONFIRMED" } })), 15000);
  assert.equal(polling.cloudSummaryPollInterval(projectId, taskId, summary({ status: "COMPLETED", project_id: "foreign-project" })), 3000);
});

test("Cloud complete readback is fixed to the exact accepted version and matching Attempt", async () => {
  const calls = [];
  const live = summary();
  const original = JSON.stringify(live);
  const read = async (project, task, version) => { calls.push({ project, task, version }); return { task: { ...live }, assets: [{ markdown: "Original FAIL" }] }; };
  const accepted = await polling.readCloudPollingDocument(projectId, taskId, live, read);
  assert.deepEqual(calls, [{ project: projectId, task: taskId, version: 7 }]);
  assert.equal(accepted.assets[0].markdown, "Original FAIL");
  assert.equal(JSON.stringify(live), original);
  for (const change of [{ version: 8 }, { id: "foreign-task" }, { project_id: "foreign-project" }, { latest_attempt_id: "foreign-attempt" }]) {
    await assert.rejects(polling.readCloudPollingDocument(projectId, taskId, live, async () => ({ task: { ...live, ...change } })), /accepted version did not match/);
  }
});

test("Cloud rejects an invalid summary before requesting any complete document", async () => {
  let reads = 0;
  for (const change of [{ id: "foreign-task" }, { project_id: "foreign-project" }, { version: 0 }, { version: 7.5 }, { current_attempt: { id: "foreign-attempt" } }]) {
    await assert.rejects(polling.readCloudPollingDocument(projectId, taskId, summary(change), async () => { reads++; }), /summary identity is not verified/);
  }
  assert.equal(reads, 0);
});
