const assert = require("node:assert/strict");
const test = require("node:test");
const { until } = require("./operation-harness.cjs");

test("async lifecycle waits for the real condition beyond an arbitrary event-loop turn count", async () => {
  let remaining = 150, ready = false;
  function advance() {
    if (--remaining === 0) ready = true;
    else setImmediate(advance);
  }
  setImmediate(advance);
  await until(() => ready);
  assert.equal(remaining, 0);
});

test("an unmet lifecycle condition reports its bounded deadline and context", async () => {
  await assert.rejects(until(() => false, { timeoutMs: 5, description: "original-key POST observation" }),
    /original-key POST observation did not settle within 5 ms \(\d+ condition checks\)/);
});

test("lifecycle condition failures propagate without being retried or converted to timeouts", async () => {
  const failure = new Error("state read failed");
  let checks = 0;
  await assert.rejects(until(() => { checks++; throw failure; }), (error) => error === failure);
  assert.equal(checks, 1);
});
