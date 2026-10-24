const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");
const polling = load("lib/run-polling.ts");

const jobs = (...statuses) => statuses.map((status) => ({ status }));

test("static legacy runs stop polling while blocked, waiting and unknown control states stay observed", () => {
  for (const status of ["COMPLETED", "CANCELLED"]) assert.equal(polling.runPollInterval(status), false);
  for (const status of ["ANALYZING", "DESIGNING", "IMPLEMENTING", "EXECUTING", "DIAGNOSING", "VERIFYING"]) assert.equal(polling.runPollInterval(status), 5000);
  for (const status of ["CREATED", "BLOCKED", "WAITING_INPUT", "UNKNOWN", "RECOVERY_REQUIRED"]) assert.equal(polling.runPollInterval(status), 15000);
});

test("jobs retain fast active tracking, slow idle tracking and stop only known terminal histories", () => {
  for (const status of ["QUEUED", "RUNNING", "CANCEL_REQUESTED"]) {
    assert.equal(polling.jobPollInterval(status), 1500);
    assert.equal(polling.jobsPollInterval(jobs("SUCCEEDED", status), "COMPLETED"), 1500);
  }
  assert.equal(polling.jobPollInterval("WAITING_INPUT"), 5000);
  assert.equal(polling.jobsPollInterval(jobs("WAITING_INPUT"), "BLOCKED"), 5000);
  assert.equal(polling.jobPollInterval("UNKNOWN"), 15000);
  assert.equal(polling.jobsPollInterval(jobs("UNKNOWN"), "COMPLETED"), 5000);
  for (const status of ["SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"]) assert.equal(polling.jobPollInterval(status), false);
  assert.equal(polling.jobsPollInterval(jobs("SUCCEEDED", "FAILED"), "COMPLETED"), false);
  assert.equal(polling.jobsPollInterval([], "CANCELLED"), false);
  assert.equal(polling.jobsPollInterval(jobs("FAILED"), "BLOCKED"), 15000);
  assert.equal(polling.jobsPollInterval(undefined, "COMPLETED"), 1500);
});

test("unresolved questions and external operations remain observable even on a completed Run", () => {
  for (const status of ["PENDING", "ANSWERED"]) assert.equal(polling.inputPollInterval(jobs(status), [], "COMPLETED"), 5000);
  assert.equal(polling.inputPollInterval(jobs("CONSUMED", "CANCELLED"), [], "COMPLETED"), false);
  assert.equal(polling.inputPollInterval([], jobs("RUNNING"), "COMPLETED"), 5000);
  assert.equal(polling.inputPollInterval([], [], "BLOCKED"), 15000);
  assert.equal(polling.harnessPollInterval({ binding: { status: "CLOSED" }, issues: [] }, [], "COMPLETED"), false);
  assert.equal(polling.harnessPollInterval({ binding: { status: "CLOSED" }, issues: jobs("UNKNOWN") }, [], "COMPLETED"), 15000);
  for (const status of ["ACTIVE", "WAITING_INPUT", "RECOVERY_REQUIRED", "UNKNOWN"]) assert.equal(polling.harnessPollInterval({ binding: { status } }, [], "COMPLETED"), 15000);
  assert.equal(polling.harnessPollInterval({ binding: { status: "CLOSED" } }, jobs("QUEUED"), "COMPLETED"), 5000);
});

test("record timers only run for visible panels, without treating paused control states as completion", () => {
  for (const status of ["ANALYZING", "BLOCKED", "COMPLETED"]) assert.equal(polling.runRecordsPollInterval(status, false, jobs("RUNNING")), false);
  assert.equal(polling.runRecordsPollInterval("ANALYZING", true, []), 5000);
  assert.equal(polling.runRecordsPollInterval("BLOCKED", true, []), 15000);
  assert.equal(polling.runRecordsPollInterval("COMPLETED", true, []), false);
  assert.equal(polling.runRecordsPollInterval("COMPLETED", true, jobs("RUNNING")), 5000);
  assert.equal(polling.missionPollInterval("COMPLETED"), false);
  assert.equal(polling.missionPollInterval("WAITING_INPUT"), 15000);
  assert.equal(polling.missionPollInterval("SUBMITTED"), 3000);
});

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
