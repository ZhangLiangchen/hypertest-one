const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");
const load = require("./load-helper.cjs");

const key = "synthetic-server-only-key";
const secret = "synthetic-credential-value";
const ca = Buffer.from("-----BEGIN CERTIFICATE-----\nsynthetic-test-ca\n-----END CERTIFICATE-----\n");
const environment = {
  HYPERTEST_CLOUD_API_ORIGIN: "https://cloud-api.example.invalid",
  HYPERTEST_CLOUD_API_SOCKET: "/run/hypertest-cloud-web/api.sock",
  HYPERTEST_CLOUD_API_CA_FILE: "/run/hypertest-cloud-web-ca/ca.crt",
};

function harness(options = {}) {
  const calls = [], reads = [], timers = [];
  const api = load("lib/cloud-server-auth.ts", {
    require: (name) => {
      if (name === "node:fs/promises") return { readFile: async (file) => {
        reads.push(file);
        if (options.caError) throw new Error(`${key} ${secret}`);
        return options.ca ?? ca;
      } };
      if (name === "node:https") return { request: (settings, callback) => {
        const request = new EventEmitter();
        request.destroy = () => { request.destroyed = true; };
        const call = { settings, request }; calls.push(call);
        request.end = (body) => {
          call.body = body;
          queueMicrotask(() => {
            if (options.error) { request.emit("error", new Error(`${key} ${secret}`)); return; }
            if (options.hang) return;
            const response = new EventEmitter();
            response.statusCode = options.status ?? 200;
            response.complete = options.complete ?? true;
            response.headers = { "set-cookie": key, "x-hypertest-operator-key": key };
            response.destroy = () => { response.destroyed = true; }; call.response = response;
            callback(response);
            if (!request.destroyed) {
              response.emit("data", Buffer.from(options.body ?? '{"enabled":true}'));
              response.emit("end");
            }
          });
        };
        return request;
      } };
      return require(name);
    },
    process: { env: { ...environment, ...options.env } }, Buffer, URL, Response, Uint8Array,
    setTimeout: (callback, milliseconds) => { const timer = { callback, milliseconds }; timers.push(timer); return timer; },
    clearTimeout: (timer) => { if (timer) timer.cleared = true; },
  });
  return { api, calls, reads, timers };
}

test("Cloud server identity uses verified HTTPS over the configured UDS only", async () => {
  const { api, calls, reads, timers } = harness();
  assert.equal(await api.cloudServerTransportReady(), true);
  const response = await api.cloudServerRequest("cloud/operations", key, { method: "POST", body: JSON.stringify({ secret }) });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { enabled: true });
  assert.equal(calls.length, 1);
  const { settings, body } = calls[0];
  assert.equal(settings.protocol, "https:");
  assert.equal(settings.hostname, "cloud-api.example.invalid");
  assert.equal(settings.servername, settings.hostname);
  assert.equal(settings.port, 443);
  assert.equal(settings.socketPath, environment.HYPERTEST_CLOUD_API_SOCKET);
  assert.equal(settings.ca, ca);
  assert.equal(settings.rejectUnauthorized, true);
  assert.equal(settings.agent, false);
  assert.equal(settings.minVersion, "TLSv1.2");
  assert.equal(settings.path, "/api/v1/cloud/operations");
  assert.equal(settings.headers["X-Hypertest-Operator-Key"], key);
  assert.equal(settings.headers.Host, "cloud-api.example.invalid");
  assert.equal(settings.headers["X-Forwarded-Proto"], undefined);
  assert.equal(settings.headers.Authorization, undefined);
  assert.equal(body, JSON.stringify({ secret }));
  assert.deepEqual(reads, [environment.HYPERTEST_CLOUD_API_CA_FILE, environment.HYPERTEST_CLOUD_API_CA_FILE]);
  assert.equal(timers[0].milliseconds, 30_000);
  assert.equal(timers[0].cleared, true);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(response.headers.get("x-hypertest-operator-key"), null);
  const certificate = { subjectaltname: "DNS:cloud-api.example.invalid", subject: {} };
  assert.equal(settings.checkServerIdentity("ignored.invalid", certificate), undefined);
  assert.ok(settings.checkServerIdentity(settings.hostname, { ...certificate, subjectaltname: "DNS:other.invalid" }));
});

test("Existing IP SANs are verified as IPs without inventing a DNS SNI", async () => {
  const { api, calls } = harness({ env: { HYPERTEST_CLOUD_API_ORIGIN: "https://192.0.2.10" } });
  await api.cloudServerRequest("cloud/capabilities", key);
  const settings = calls[0].settings;
  assert.equal(settings.servername, "");
  assert.equal(settings.hostname, "192.0.2.10");
  assert.equal(settings.checkServerIdentity("ignored.invalid", { subject: {}, subjectaltname: "IP Address:192.0.2.10" }), undefined);
  assert.ok(settings.checkServerIdentity("192.0.2.10", { subject: {}, subjectaltname: "IP Address:192.0.2.11" }));
});

test("Missing or noncanonical TLS configuration cannot send either identity or secret", async () => {
  const invalid = [
    { HYPERTEST_CLOUD_API_ORIGIN: undefined, HYPERTEST_API_ORIGIN: "https://legacy-api.invalid" },
    ...["", "http://cloud-api.invalid", "http://127.0.0.1", "https://user:password@cloud-api.invalid", "https://cloud-api.invalid:65536",
      "https://cloud-api.invalid/path", "https://cloud-api.invalid?token=value", "https://cloud-api.invalid/#fragment", " https://cloud-api.invalid", "https://cloud-api.invalid\n"].map((value) => ({ HYPERTEST_CLOUD_API_ORIGIN: value })),
    { HYPERTEST_CLOUD_API_SOCKET: undefined }, { HYPERTEST_CLOUD_API_SOCKET: "relative.sock" },
    { HYPERTEST_CLOUD_API_SOCKET: "/run/../tmp/api.sock" }, { HYPERTEST_CLOUD_API_SOCKET: "/run/api.sock\n" },
    { HYPERTEST_CLOUD_API_CA_FILE: undefined }, { HYPERTEST_CLOUD_API_CA_FILE: "ca.crt" },
  ];
  for (const env of invalid) {
    const { api, calls } = harness({ env });
    assert.equal(await api.cloudServerTransportReady(), false);
    await assert.rejects(api.cloudServerRequest("cloud/operations", key, { method: "POST", body: JSON.stringify({ secret }) }), { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });
    assert.equal(calls.length, 0);
  }
  for (const options of [{ ca: Buffer.alloc(0) }, { ca: Buffer.from("not a certificate") }, { caError: true }]) {
    const { api, calls } = harness(options);
    assert.equal(await api.cloudServerTransportReady(), false);
    await assert.rejects(api.cloudServerRequest("cloud/operations", key, { method: "POST", body: JSON.stringify({ secret }) }), { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });
    assert.equal(calls.length, 0);
  }
});

test("A canonical existing HTTPS port is Host metadata while transport remains the same UDS", async () => {
  const { api, calls } = harness({ env: { HYPERTEST_CLOUD_API_ORIGIN: "https://cloud-api.example.invalid:8443" } });
  await api.cloudServerRequest("cloud/capabilities", key);
  assert.equal(calls[0].settings.port, 8443);
  assert.equal(calls[0].settings.headers.Host, "cloud-api.example.invalid:8443");
  assert.equal(calls[0].settings.hostname, "cloud-api.example.invalid");
  assert.equal(calls[0].settings.servername, "cloud-api.example.invalid");
  assert.equal(calls[0].settings.socketPath, environment.HYPERTEST_CLOUD_API_SOCKET);
});

test("TLS rejection, redirects and truncated replies are one failed request without raw diagnostics", async () => {
  for (const options of [{ error: true }, { status: 302 }, { complete: false }]) {
    const { api, calls } = harness(options);
    await assert.rejects(api.cloudServerRequest("cloud/operations", key, { method: "POST", body: JSON.stringify({ secret }) }), { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].request.destroyed, true);
  }
});

test("A total transport deadline destroys the request without retrying its body", async () => {
  const { api, calls, timers } = harness({ hang: true });
  const pending = api.cloudServerRequest("cloud/operations", key, { method: "POST", body: JSON.stringify({ secret }) });
  await new Promise(setImmediate);
  assert.equal(calls.length, 1);
  timers[0].callback();
  await assert.rejects(pending, { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });
  assert.equal(calls[0].request.destroyed, true);
  assert.equal(calls.length, 1);
});

test("Malformed identity or a nonrelative request is rejected before HTTPS starts", async () => {
  const { api, calls } = harness();
  for (const [path, identity] of [["cloud/capabilities", ""], ["cloud/capabilities", `${key}\r\nInjected: value`],
    ["https://other.invalid", key], ["/cloud/capabilities", key], ["../cloud/capabilities", key], ["cloud/capabilities#fragment", key]]) {
    await assert.rejects(api.cloudServerRequest(path, identity), { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });
  }
  assert.equal(calls.length, 0);
});
