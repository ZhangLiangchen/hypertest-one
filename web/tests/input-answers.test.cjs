const assert = require("node:assert/strict");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");
const { canAnswerInput, prepareInputAnswer, validateInputAnswer } = loadHelper("lib/input-answers.ts");

test("empty and whitespace-only answers are blocked without rewriting meaningful text", () => {
  for (const answer of ["", " \r\n\t", "\u3000"]) assert.equal(validateInputAnswer(answer), "empty");
  assert.equal(validateInputAnswer("  租户A\r\n保留细节🙂  "), null);
  assert.equal(validateInputAnswer("tenant\0a"), "nul");
});

test("the answer limit counts Unicode characters rather than UTF-16 code units", () => {
  assert.equal(validateInputAnswer("🙂".repeat(12000)), null);
  assert.equal(validateInputAnswer("🙂".repeat(12001)), "length");
  assert.equal(validateInputAnswer("a".repeat(12000)), null);
  assert.equal(validateInputAnswer("a".repeat(12001)), "length");
});

test("an uncertain retry retains its original body, key and concurrency version after polling", () => {
  let generated = 0;
  const key = () => `key-${++generated}`;
  const answer = "  中文回答\r\n另起一行 🙂  ";
  const first = prepareInputAnswer(undefined, answer, 1, key);
  const retry = prepareInputAnswer(first, answer, 4, key);
  assert.equal(first, retry);
  assert.equal(retry.answer, answer);
  assert.equal(retry.idempotency_key, "key-1");
  assert.equal(retry.expected_row_version, 1);
  assert.equal(generated, 1);
});

test("editing an uncertain answer creates a distinct request and keeps the old record intact", () => {
  const first = prepareInputAnswer(undefined, "tenant-a", 1, () => "old-key");
  const changed = prepareInputAnswer(first, "tenant-a ", 2, () => "new-key");
  assert.notEqual(changed, first);
  assert.equal(changed.answer, "tenant-a ");
  assert.equal(changed.idempotency_key, "new-key");
  assert.equal(changed.expected_row_version, 2);
  assert.equal(first.answer, "tenant-a");
  assert.equal(first.idempotency_key, "old-key");
});

test("answering requires the exact run-owned job to be safely paused", () => {
  const request = { status: "PENDING", test_run_id: "run-1", durable_job_id: "job-1" };
  const job = { id: "job-1", test_run_id: "run-1", status: "WAITING_INPUT" };
  assert.equal(canAnswerInput(request, job), true);
  assert.equal(canAnswerInput(request, undefined), false);
  assert.equal(canAnswerInput(request, { ...job, id: "job-2" }), false);
  assert.equal(canAnswerInput(request, { ...job, test_run_id: "run-2" }), false);
  for (const status of ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "CANCELLED", "FAILED", "SUCCEEDED", "INTERRUPTED"]) {
    assert.equal(canAnswerInput(request, { ...job, status }), false, status);
  }
});

test("answered, consumed and cancelled questions cannot submit another answer", () => {
  const job = { id: "job-1", test_run_id: "run-1", status: "WAITING_INPUT" };
  for (const status of ["ANSWERED", "CONSUMED", "CANCELLED"]) {
    assert.equal(canAnswerInput({ status, test_run_id: "run-1", durable_job_id: "job-1" }, job), false);
  }
});

test("the answer API sends the untouched draft and original retry key to the recorded question", async () => {
  const calls = [];
  const result = { input_request: { id: "question-1", status: "ANSWERED" }, job: { id: "job-1", status: "QUEUED" } };
  const { answerInputRequest } = loadHelper("lib/api.ts", { fetch: async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(result), { status: 202, headers: { "Content-Type": "application/json" } });
  } });
  const payload = { answer: "  中文回答\r\n🙂  ", expected_row_version: 1, idempotency_key: "same-key" };
  const first = await answerInputRequest("question-1", payload);
  await answerInputRequest("question-1", payload);
  assert.equal(first.job.id, "job-1");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, "/api/v1/input-requests/question-1/answer");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.body, calls[1].init.body);
  assert.deepEqual(JSON.parse(calls[0].init.body), payload);
});

test("an answer conflict remains a failure and never launches a replacement job", async () => {
  const calls = [];
  const { answerInputRequest, ApiError } = loadHelper("lib/api.ts", { fetch: async (url) => {
    calls.push(url);
    return new Response(JSON.stringify({ detail: "input request is already answered" }), { status: 409 });
  } });
  await assert.rejects(answerInputRequest("question-1", { answer: "different", expected_row_version: 1, idempotency_key: "key-2" }), (error) => error instanceof ApiError && error.status === 409);
  assert.deepEqual(calls, ["/api/v1/input-requests/question-1/answer"]);
});
