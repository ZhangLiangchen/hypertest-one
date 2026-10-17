const assert = require("node:assert/strict");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");
const { latestRunVerdict } = loadHelper("lib/run-summary.ts");

test("missing or non-formal run decisions remain unknown", () => {
  assert.equal(latestRunVerdict(undefined), undefined);
  assert.equal(latestRunVerdict([]), undefined);
  assert.equal(latestRunVerdict([
    { sequence_no: 1, status: "DRAFT", scope: "TEST_RUN", decision: "RELEASE_READY" },
    { sequence_no: 2, status: "REVOKED", scope: "TEST_RUN", decision: "RELEASE_READY" },
    { sequence_no: 3, status: "FINAL", scope: "REQUIREMENT", decision: "PASS" },
  ]), undefined);
});

test("newer draft, revoked and narrow-scope passes cannot replace a formal blocked run verdict", () => {
  const blocked = { sequence_no: 4, status: "FINAL", scope: "TEST_RUN", decision: "RELEASE_BLOCKED" };
  assert.equal(latestRunVerdict([
    blocked,
    { sequence_no: 5, status: "DRAFT", scope: "TEST_RUN", decision: "RELEASE_READY" },
    { sequence_no: 6, status: "REVOKED", scope: "TEST_RUN", decision: "RELEASE_READY" },
    { sequence_no: 7, status: "FINAL", scope: "RISK", decision: "PASS" },
    { sequence_no: 8, status: "FINAL", scope: "REQUIREMENT", decision: "PASS" },
  ]), blocked);
});

test("chooses the greatest formal run sequence without changing history order", () => {
  const older = { sequence_no: 1, status: "FINAL", scope: "TEST_RUN", decision: "RELEASE_BLOCKED" };
  const newer = { sequence_no: 3, status: "FINAL", scope: "TEST_RUN", decision: "RELEASE_READY" };
  const records = [newer, older];
  assert.equal(latestRunVerdict(records), newer);
  assert.equal(records[0], newer);
  assert.equal(records[1], older);
});
