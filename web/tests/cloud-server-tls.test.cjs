const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const https = require("node:https");
const path = require("node:path");
const test = require("node:test");
const load = require("./load-helper.cjs");

// Executed by the remote Node test job only. Certificates and keys are generated
// for this test, never taken from the deployment or the user's configuration.
test("Actual TLS over UDS authenticates CA/SAN and closes rejected or uncertain requests", async (t) => {
  const directory = fs.mkdtempSync("/tmp/ht-cloud-tls-");
  fs.chmodSync(directory, 0o700);
  const socket = path.join(directory, "api.sock");
  const certificate = (stem) => {
    const key = path.join(directory, `${stem}.key`), cert = path.join(directory, `${stem}.crt`);
    execFileSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "1",
      "-subj", "/CN=cloud-api.example.invalid", "-addext", "subjectAltName=DNS:cloud-api.example.invalid",
      "-addext", "basicConstraints=critical,CA:TRUE", "-keyout", key, "-out", cert], {
      stdio: "ignore", env: { PATH: process.env.PATH, HOME: directory, TMPDIR: directory, OPENSSL_CONF: "/dev/null" },
    });
    fs.chmodSync(key, 0o600); return { key, cert };
  };
  let server;
  const connections = new Set(), requests = [];
  let mode = "normal";
  try {
    const trusted = certificate("trusted"), wrong = certificate("wrong");
    server = https.createServer({ key: fs.readFileSync(trusted.key), cert: fs.readFileSync(trusted.cert) }, (request, response) => {
      const pieces = [];
      request.on("error", () => {}); response.on("error", () => {});
      request.on("data", (piece) => pieces.push(piece));
      request.on("end", () => {
        requests.push({ headers: request.headers, body: Buffer.concat(pieces).toString("utf8"), url: request.url });
        if (mode === "hang") return;
        if (mode === "redirect") { response.writeHead(302, { Location: "https://other.invalid/secret" }); response.end(); return; }
        if (mode === "oversize") { response.end(Buffer.alloc(32 * 1024 * 1024 + 1, 120)); return; }
        if (mode === "truncated") { response.writeHead(200, { "Content-Length": "100" }); response.write("{}"); response.destroy(); return; }
        response.end('{"status":"ACCEPTED"}');
      });
    });
    server.on("tlsClientError", () => {});
    server.on("connection", (connection) => { connections.add(connection); connection.on("close", () => connections.delete(connection)); });
    await new Promise((resolve, reject) => { server.once("error", reject); server.listen(socket, resolve); });

    const client = (overrides = {}, timeout) => load("lib/cloud-server-auth.ts", {
      require, Buffer, URL, Response, Uint8Array, clearTimeout,
      setTimeout: timeout ? (callback) => setTimeout(callback, timeout) : setTimeout,
      process: { env: {
        HYPERTEST_CLOUD_API_ORIGIN: "https://cloud-api.example.invalid:8080",
        HYPERTEST_CLOUD_API_SOCKET: socket, HYPERTEST_CLOUD_API_CA_FILE: trusted.cert, ...overrides,
      } },
    });
    const key = "synthetic-operator-key", secret = "synthetic-private-credential";
    const body = JSON.stringify({ operation_key: "frozen-original", secret });
    const send = (api) => api.cloudServerRequest("cloud/operations", key, { method: "POST", body });
    const rejected = async (api) => assert.rejects(send(api), { message: "CLOUD_SERVER_TRANSPORT_UNAVAILABLE" });

    await t.test("correct CA and SAN send identity only through the fixed UDS", async () => {
      const response = await send(client());
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { status: "ACCEPTED" });
      assert.equal(requests.length, 1);
      assert.equal(requests[0].headers.host, "cloud-api.example.invalid:8080");
      assert.equal(requests[0].headers["x-hypertest-operator-key"], key);
      assert.equal(requests[0].headers["x-forwarded-proto"], undefined);
      assert.equal(requests[0].url, "/api/v1/cloud/operations");
      assert.equal(requests[0].body, body);
    });
    await t.test("wrong CA or hostname cannot transmit an HTTP body or Operator header", async () => {
      const before = requests.length;
      await rejected(client({ HYPERTEST_CLOUD_API_CA_FILE: wrong.cert }));
      await rejected(client({ HYPERTEST_CLOUD_API_ORIGIN: "https://wrong-name.example.invalid:8080" }));
      assert.equal(requests.length, before);
    });
    await t.test("HTTP and path-bearing origins fail before an authenticated connection", async () => {
      const before = requests.length;
      for (const origin of ["http://cloud-api.example.invalid:8080", "https://cloud-api.example.invalid:8080/path"]) {
        await rejected(client({ HYPERTEST_CLOUD_API_ORIGIN: origin }));
      }
      assert.equal(requests.length, before);
    });
    for (const failure of ["redirect", "oversize", "truncated", "hang"]) {
      await t.test(`${failure} is one failed request and never repeats the original body`, async () => {
        mode = failure;
        const before = requests.length;
        await rejected(client({}, failure === "hang" ? 500 : undefined));
        assert.equal(requests.length, before + 1);
      });
    }
  } finally {
    if (server) {
      const stopped = new Promise((resolve) => server.close(resolve));
      for (const connection of connections) connection.destroy();
      await stopped;
    }
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
