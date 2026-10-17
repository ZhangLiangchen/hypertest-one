const assert = require("node:assert/strict");
const test = require("node:test");
const loadHelper = require("./load-helper.cjs");

const { decodePrdBytes, MAX_PRD_CHARACTERS } = loadHelper("lib/prd-import.ts", { TextDecoder });
const encode = (text) => new TextEncoder().encode(text).buffer;

function accepted(bytes, expected) {
  const original = Buffer.from(bytes).toString("hex");
  const result = decodePrdBytes(bytes);
  assert.equal(result.ok, true);
  assert.equal(result.text, expected);
  assert.equal(Buffer.from(bytes).toString("hex"), original);
}

function rejected(bytes, error) {
  const result = decodePrdBytes(bytes);
  assert.equal(result.ok, false);
  assert.equal(result.error, error);
  // Failed imports must not return replacement content for an existing draft.
  assert.equal(Object.hasOwn(result, "text"), false);
}

test("valid UTF-8 retains Chinese, emoji, CRLF and surrounding whitespace", () => {
  const text = "  中文 requirements 😀\r\n第二行\r\n ";
  accepted(encode(text), text);
});

test("a UTF-8 BOM is decoded while CRLF and content remain unchanged", () => {
  accepted(encode("\ufeff中文 BOM\r\n"), "中文 BOM\r\n");
});

test("an interior BOM character is retained as original content", () => {
  accepted(encode("正文\ufeff内部字符\n"), "正文\ufeff内部字符\n");
});

test("the documented maximum decoded length is accepted", () => {
  const text = "a".repeat(MAX_PRD_CHARACTERS);
  accepted(encode(text), text);
});

for (const [description, text] of [
  ["empty file", ""],
  ["whitespace", " \t\r\n"],
  ["BOM only", "\ufeff"],
  ["BOM and whitespace", "\ufeff\r\n  "],
  ["repeated BOMs", "\ufeff\ufeff"],
]) {
  test(`${description} is rejected without replacement draft content`, () => {
    rejected(encode(text), "empty");
  });
}

for (const [description, bytes] of [
  ["UTF-16", [0xff, 0xfe, 0x61, 0x00]],
  ["malformed UTF-8", [0xc3, 0x28]],
  ["truncated UTF-8", [0xe4, 0xb8]],
]) {
  test(`${description} is rejected instead of silently replacing characters`, () => {
    rejected(Uint8Array.from(bytes).buffer, "encoding");
  });
}

test("embedded NUL is rejected without replacement draft content", () => {
  rejected(encode("正文\0隐含NUL"), "encoding");
});

test("content beyond the decoded length limit is rejected", () => {
  rejected(encode("a".repeat(MAX_PRD_CHARACTERS + 1)), "length");
});
