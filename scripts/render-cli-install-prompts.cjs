#!/usr/bin/env node
// Render the public prompts from the same typed source used by the Web copy action.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createRequire } = require("node:module");
const root = path.resolve(__dirname, "..");
const ts = createRequire(path.join(root, "web/package.json"))("typescript");
const mode = process.argv[2];
if (!["--write", "--check"].includes(mode) || process.argv.length !== 3) {
  throw new Error("Usage: node scripts/render-cli-install-prompts.cjs --write|--check (requires existing web dependencies)");
}
const modules = new Map();
function load(name) {
  if (!new Set(["cli-release", "cli-install-prompt"]).has(name)) throw new Error("Unexpected prompt source import");
  if (modules.has(name)) return modules.get(name);
  const filename = path.join(root, "web/lib", name + ".ts");
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }, reportDiagnostics: true,
  });
  if (compiled.diagnostics.length) throw new Error("Prompt source compilation failed");
  const exports = {};
  vm.runInNewContext(compiled.outputText, { exports, URL, require: (specifier) => {
    if (specifier !== "./cli-release") throw new Error("Unexpected prompt source import");
    return load("cli-release");
  } }, { filename });
  modules.set(name, exports);
  return exports;
}
const { cliInstallPrompt } = load("cli-install-prompt");
const directory = path.join(root, "docs/cli-install-prompts");
for (const [locale, suffix] of [["zh", "zh-CN"], ["en", "en"]]) {
  const content = cliInstallPrompt({ locale });
  if (!content) throw new Error("CLI release is not published");
  const file = path.join(directory, `hypertest-cli-install-prompt.${suffix}.txt`);
  if (mode === "--write") {
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(file, content);
  } else if (fs.readFileSync(file, "utf8") !== content) {
    throw new Error("Public prompt is stale: " + file);
  }
  process.stdout.write(`${mode === "--write" ? "Rendered" : "Verified"} ${path.relative(root, file)}\n`);
}
