const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

function fakeDocument(copyResult) {
  const calls = { appended: [], removed: [], selected: 0, focused: 0, exec: [] };
  const body = { appendChild(node) { calls.appended.push(node); node.parentNode = body; }, removeChild(node) { calls.removed.push(node); node.parentNode = null; } };
  const element = { style: {}, value: "", setAttribute() {}, focus() { calls.focused++; }, select() { calls.selected++; }, setSelectionRange() {}, parentNode: null };
  const document = {
    activeElement: { focus() {} }, body,
    createElement() { return element; },
    execCommand(command) { calls.exec.push(command); return copyResult; },
  };
  return { document, calls };
}
const loadClipboard = (globals) => load("lib/clipboard.ts", globals);

test("a secure-context clipboard is used when the page has one", async () => {
  const writes = [];
  const { copyText } = loadClipboard({ navigator: { clipboard: { writeText: async (value) => writes.push(value) } } });
  await copyText("install prompt");
  assert.deepEqual(writes, ["install prompt"]);
});

test("a plain-HTTP page without navigator.clipboard copies through the legacy selection command", async () => {
  const { document, calls } = fakeDocument(true);
  const { copyText } = loadClipboard({ navigator: {}, document });
  await copyText("prompt without secure context");
  assert.deepEqual(calls.exec, ["copy"]);
  assert.equal(calls.appended.length, 1);
  assert.equal(calls.appended[0].value, "prompt without secure context");
  assert.equal(calls.selected, 1);
  assert.equal(calls.removed.length, 1);
  assert.equal(calls.appended[0].parentNode, null);
});

test("a rejected clipboard write falls back to the legacy command on the same click", async () => {
  const { document, calls } = fakeDocument(true);
  const { copyText } = loadClipboard({ navigator: { clipboard: { writeText: async () => { throw Error("denied"); } } }, document });
  await copyText("fallback prompt");
  assert.deepEqual(calls.exec, ["copy"]);
  assert.equal(calls.removed.length, 1);
});

test("manual selection stays available when both copy paths fail", async () => {
  const { document } = fakeDocument(false);
  await assert.rejects(loadClipboard({ navigator: {}, document }).copyText("x"), /CLIPBOARD_UNAVAILABLE/);
  await assert.rejects(loadClipboard({ navigator: {} }).copyText("x"), /CLIPBOARD_UNAVAILABLE/);
  const failing = fakeDocument(false);
  failing.document.execCommand = () => { throw Error("unsupported"); };
  await assert.rejects(loadClipboard({ navigator: {}, document: failing.document }).copyText("x"), /CLIPBOARD_UNAVAILABLE/);
  assert.equal(failing.calls.removed.length, 1, "the temporary textarea is always removed");
});
