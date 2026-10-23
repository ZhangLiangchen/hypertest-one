const assert = require("node:assert/strict");
const test = require("node:test");
const load = require("./load-helper.cjs");

// Exercise the actual form handlers/effects without a browser or a second
// operation stream. Full React/AntD rendering remains a separate UI check.
function harness(submit) {
  const states = [], effects = [], calls = [];
  let cursor = 0, formCursor = 0, dirty = false, saved = 0;
  const resourceForm = { values: {}, setFieldsValue() {} };
  const credentialForm = { values: { credential_id: "credential-1", kind: "GIT_TOKEN" }, setFieldValue(name, value) { this.values[name] = value; } };
  const Form = Object.assign(() => null, { Item: "Form.Item", useForm: () => [formCursor++ === 0 ? resourceForm : credentialForm], useWatch: (name, form) => form.values[name] });
  const react = {
    useState(initial) { const index = cursor++; if (!(index in states)) states[index] = initial; return [states[index], (next) => { const value = typeof next === "function" ? next(states[index]) : next; if (!Object.is(value, states[index])) { states[index] = value; dirty = true; } }]; },
    useRef(initial) { const index = cursor++; if (!(index in states)) states[index] = { current: initial }; return states[index]; },
    useEffect(effect, dependencies) { const index = cursor++, previous = states[index]; if (!previous || dependencies.some((value, i) => value !== previous[i])) { states[index] = dependencies; effects.push(effect); } },
  };
  const jsx = (type, props) => ({ type, props });
  const ui = Object.fromEntries(["Alert", "Button", "Col", "Divider", "InputNumber", "Row", "Select", "Space", "Table", "Tag"].map((name) => [name, name]));
  Object.assign(ui, { Form, Input: { TextArea: "Input.TextArea", Password: "Input.Password" }, Typography: { Paragraph: "Paragraph", Title: "Title" } });
  const { CloudResources } = load("app/projects/[projectId]/cloud/resources.tsx", { require: (name) => {
    if (name === "react") return react;
    if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "Fragment" };
    if (name === "antd") return ui;
    if (name === "@/lib/i18n") return { useI18n: () => ({ t: (en) => en, formatDate: (value) => value }) };
    if (name === "@/lib/cloud") return {};
    return require(name);
  } });
  const credential = { id: "credential-1", kind: "GIT_TOKEN", label: "Repo", purpose: "Read repository", allowed_targets: ["https://git.invalid/repo"], allowed_actions: ["git:read"], version: 1, status: "ACTIVE" };
  const operation = { blocked: false, busy: false, pending: null, issue: null, receipt: null,
    submit: async (request) => { calls.push(request); return submit(request); } };
  let credentials = [credential];
  const render = () => {
    let tree, passes = 0;
    do {
      dirty = false; cursor = 0; formCursor = 0;
      tree = CloudResources({ credentials, versions: [], enabled: true, operation, onSaved: () => { saved++; } });
      while (effects.length) effects.shift()();
      assert.ok(++passes < 10, "form effects must settle");
    } while (dirty);
    return tree;
  };
  const nodes = (value) => !value || typeof value !== "object" ? [] : Array.isArray(value) ? value.flatMap(nodes) : [value, ...nodes(value.props?.children)];
  return { calls, operation, credentialForm,
    render,
    refresh(version) { credentials = [{ ...credential, version }]; render(); },
    saved: () => saved,
    async rotate() {
      credentialForm.values.secret = "synthetic-private-value";
      const form = nodes(render()).find((node) => node.type === Form && node.props.form === credentialForm);
      form.props.onFinish({ ...credentialForm.values });
      await new Promise(setImmediate); render();
    },
  };
}

test("Consecutive accepted rotations advance only to their fully read-back receipt versions", async () => {
  const current = harness(async (request) => ({ operation: "STORE_CREDENTIAL", credential_id: request.credential_id, version: request.expected_version + 1 }));
  await current.rotate(); current.refresh(2);
  assert.equal(current.credentialForm.values.secret, "");
  await current.rotate();
  assert.deepEqual(current.calls.map((call) => call.expected_version), [1, 2]);
  assert.equal(current.saved(), 2);
  current.refresh(9); await current.rotate();
  assert.equal(current.calls[2].expected_version, 3, "an external version must not rebase the selected intention");
});

test("An uncertain or rejected rotation does not adopt an externally refreshed credential version", async () => {
  const current = harness(async () => null);
  await current.rotate(); current.refresh(2); await current.rotate();
  assert.deepEqual(current.calls.map((call) => call.expected_version), [1, 1]);
  assert.equal(current.saved(), 0);
});

test("Original-key reconciliation advances the selection only after its pending readback completes", async () => {
  const current = harness(async () => null);
  await current.rotate(); current.refresh(2);
  current.operation.receipt = { operation: "STORE_CREDENTIAL", credential_id: "credential-1", version: 2 };
  current.operation.pending = { state: "UNKNOWN" }; current.render();
  assert.equal(current.saved(), 0);
  current.operation.pending = null; current.operation.busy = true; current.render();
  assert.equal(current.saved(), 0);
  current.operation.busy = false; current.render();
  assert.equal(current.saved(), 1);
  await current.rotate();
  assert.equal(current.calls[1].expected_version, 2);
});
