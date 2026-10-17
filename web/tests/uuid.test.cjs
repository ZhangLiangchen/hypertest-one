const assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");

function uuidWith(crypto) {
  return loadHelper("lib/uuid.ts", {
    crypto,
    Math: { random() { throw new Error("An insecure random fallback must never be used"); } },
  }).createUuid;
}

test("native randomUUID is preferred and called with its Crypto receiver", () => {
  let nativeCalls = 0;
  const provider = {
    randomUUID() {
      assert.equal(this, provider);
      nativeCalls += 1;
      return "12345678-1234-4234-8234-123456789abc";
    },
    getRandomValues() { throw new Error("The native UUID path must not use the fallback"); },
  };
  assert.equal(uuidWith(provider)(), "12345678-1234-4234-8234-123456789abc");
  assert.equal(nativeCalls, 1);
});

for (const [byte, expected] of [
  [0x00, "00000000-0000-4000-8000-000000000000"],
  [0xff, "ffffffff-ffff-4fff-bfff-ffffffffffff"],
]) {
  test(`HTTP fallback sets RFC v4 and variant bits for random byte ${byte}`, () => {
    let randomCalls = 0;
    const provider = {
      getRandomValues(bytes) {
        assert.equal(this, provider);
        assert.equal(bytes.byteLength, 16);
        randomCalls += 1;
        bytes.fill(byte);
        return bytes;
      },
    };
    assert.equal(uuidWith(provider)(), expected);
    assert.equal(randomCalls, 1);
  });
}

test("HTTP fallback produces distinct standard UUIDs with real WebCrypto", () => {
  const createUuid = uuidWith({ getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });
  const values = Array.from({ length: 1000 }, () => createUuid());
  assert.equal(new Set(values).size, values.length);
  assert.ok(values.every((value) => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value)));
});

for (const provider of [undefined, {}]) {
  test(`missing ${provider ? "random methods" : "Crypto provider"} fails instead of using insecure randomness`, () => {
    assert.throws(() => uuidWith(provider)(), /Cryptographic random values are unavailable/);
  });
}
