const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

test("A 409 is a version conflict only with an explicit code or known stale-version detail", async () => {
  const cloud = load("lib/cloud.ts", { fetch: async () => new Response(JSON.stringify({ detail: "safe precondition", code: "REQUEST_PRECONDITION_REQUIRED" }), { status: 409 }) });
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Unknown conflict")), "REQUEST_PRECONDITION_REQUIRED");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Cloud Task version is stale")), "VERSION_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "VERSION_CONFLICT")), "VERSION_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "SDK_RESUME_UNSUPPORTED")), "SDK_RESUME_UNSUPPORTED");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "safe detail", "OPERATION_KEY_CONFLICT")), "OPERATION_KEY_CONFLICT");
  assert.equal(cloud.cloudSubmissionIssue(new cloud.CloudApiError(409, "Cloud operation key conflicts with its original actor or request")), "OPERATION_KEY_CONFLICT");
  assert.equal(cloud.canReleaseCloudPending(409, false, "OPERATION_KEY_CONFLICT"), false);
  await assert.rejects(cloud.cloudRequest("operations"), (error) => error.status === 409 && error.code === "REQUEST_PRECONDITION_REQUIRED");
});
