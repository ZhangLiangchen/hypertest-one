const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

// Exercise the actual resource form effects and submission without a browser.
function harness(submit, { project, latest } = {}) {
  const states = [], effects = [], calls = [];
  let cursor = 0, dirty = false, saved = 0;
  const resourceForm = { values: {}, setFieldsValue(values) { Object.assign(this.values, values); } };
  const Form = Object.assign(() => null, { Item: "Form.Item", useForm: () => [resourceForm] });
  const react = {
    useState(initial) { const index = cursor++; if (!(index in states)) states[index] = initial; return [states[index], (next) => { const value = typeof next === "function" ? next(states[index]) : next; if (!Object.is(value, states[index])) { states[index] = value; dirty = true; } }]; },
    useEffect(effect, dependencies) { const index = cursor++, previous = states[index]; if (!previous || dependencies.some((value, i) => value !== previous[i])) { states[index] = dependencies; effects.push(effect); } },
  };
  const jsx = (type, props) => ({ type, props });
  const ui = { Form, Alert: "Alert", Button: "Button", Input: "Input", Typography: { Paragraph: "Paragraph", Title: "Title", Text: "Text" } };
  const { CloudResources } = load("app/projects/[projectId]/cloud/resources.tsx", { require: (name) => {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en }) };
    if (name === "@/lib/cloud") return { credentialFreeUrl: () => true };
    if (name === "./resources-layout.css") return {};
    return require(name);
  } });
  const operation = { blocked: false, busy: false, submit: async (request) => { calls.push(request); return submit(request); } };
  const render = () => {
    let tree, passes = 0;
    do {
      dirty = false; cursor = 0;
      tree = CloudResources({ project, latest, enabled: true, operation, onSaved: () => { saved++; } });
      while (effects.length) effects.shift()();
      assert.ok(++passes < 10, "form effects must settle");
    } while (dirty);
    return tree;
  };
  const nodes = (value) => !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
  return { calls, resourceForm, render, saved: () => saved,
    async configure(values) {
      const form = nodes(render()).find((node) => node.type === Form && node.props.form === resourceForm);
      form.props.onFinish(values);
      await new Promise(setImmediate); render();
    },
  };
}

const plain = (value) => JSON.parse(JSON.stringify(value));

test("new cloud resources prefill repositories and do not invent version selectors", async () => {
  const project = { repository_url: "https://git.example/sut", test_framework_repository_url: "https://git.example/framework" };
  const current = harness(async () => ({ operation: "CONFIGURE", config_id: "new", version: 1 }), { project });
  current.render();
  assert.equal(current.resourceForm.values.sut_url, project.repository_url);
  assert.equal(current.resourceForm.values.framework_url, project.test_framework_repository_url);
  await current.configure({ ...current.resourceForm.values, environment_name: "Test environment", expected_deployment: "UNKNOWN" });
  assert.equal(current.calls[0].configuration.sut.default_selector, undefined);
  assert.equal(current.calls[0].configuration.framework.default_selector, undefined);
  assert.equal(current.calls[0].configuration.environment.connection, "NONE");
});

test("saving a new revision retains the selector but drops obsolete platform connection and credentials", async () => {
  const configuration = {
    sut: { url: "https://git.example/sut", credential_version_id: "old-sut", default_selector: { kind: "BRANCH", value: "main" } },
    framework: { url: "https://git.example/framework", credential_version_id: "old-framework" },
    environment: { name: "Legacy", connection: "SSH", host: "test.example", user: "test", host_key: "public-key", credential_version_id: "old-env", network_requirements: "private", expected_deployment: "v1", require_matching_deployment: true, ssh_access: { profile: "legacy" } },
  };
  const current = harness(async () => ({ operation: "CONFIGURE", config_id: "next", version: 8 }), { latest: { id: "old", revision: 7, configuration } });
  current.render();
  await current.configure({ ...current.resourceForm.values, environment_name: "Renamed" });
  assert.equal(current.calls[0].expected_version, 7);
  assert.deepEqual(plain(current.calls[0].configuration), {
    sut: { url: configuration.sut.url, default_selector: configuration.sut.default_selector },
    framework: { url: configuration.framework.url },
    environment: { name: "Renamed", connection: "NONE", expected_deployment: "v1", require_matching_deployment: false },
  });
  assert.equal(current.saved(), 1);
});

test("a changed repository does not inherit an old repository credential or selector", async () => {
  const configuration = {
    sut: { url: "https://git.example/old", credential_version_id: "old-sut", default_selector: { kind: "BRANCH", value: "main" } },
    framework: { url: "https://git.example/framework", credential_version_id: "old-framework" },
    environment: { name: "Test", connection: "NONE", expected_deployment: "UNKNOWN", require_matching_deployment: false },
  };
  const current = harness(async () => ({ operation: "CONFIGURE", config_id: "next", version: 2 }), { latest: { id: "old", revision: 1, configuration } });
  current.render();
  await current.configure({ ...current.resourceForm.values, sut_url: "https://git.example/new" });
  assert.deepEqual(plain(current.calls[0].configuration.sut), { url: "https://git.example/new" });
  assert.deepEqual(plain(current.calls[0].configuration.framework), { url: configuration.framework.url });
});

test("existing access restrictions are not widened in a new revision", async () => {
  for (const policy of ["LOCAL_ONLY", "WEB_ONLY"]) {
    const environment = { name: "Restricted", connection: "HTTPS", host: "test.example", credential_version_id: "old-env", expected_deployment: "v1", require_matching_deployment: true, cloud_access_policy: policy };
    const configuration = { sut: { url: "https://git.example/sut" }, framework: { url: "https://git.example/framework" }, environment };
    const current = harness(async () => ({ operation: "CONFIGURE", config_id: "next", version: 2 }), { latest: { id: "old", revision: 1, configuration } });
    current.render();
    await current.configure({ ...current.resourceForm.values });
    const saved = plain(current.calls[0].configuration.environment);
    assert.equal(saved.cloud_access_policy, policy);
    if (policy === "WEB_ONLY") assert.deepEqual(saved, environment);
    else assert.equal(saved.credential_version_id, undefined);
  }
});
