const assert = require('node:assert/strict');
const test = require('node:test');
const load = require('./load-helper.cjs');
const cloud = load('lib/cloud.ts', { URL, TextEncoder, Uint8Array, DataView, Int32Array });
const { editedCloudInputs, localCloudExpiry } = load('app/projects/[projectId]/cloud/task-form.tsx', { require: (name) => name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? {} : name === 'next/link' ? {} : require(name) });
const plain = (v) => JSON.parse(JSON.stringify(v));
const original = {
  sut_selector: { kind: 'BRANCH', value: 'main', checkout_strategy: 'HEAD', extension: 'retained' },
  framework_selector: { kind: 'MR', value: '7', checkout_strategy: 'MERGE', base_ref: 'refs/heads/main' },
  prd_markdown: 'requirements', prd_version: 'v1', objective: 'objective', basic_flow: 'flow', test_scope: 'scope',
  expected_outputs: ['REPORT', 'CASE'], framework_entrypoints: [' command with spaces ', 'second'],
  authorization: { targets: ['https://example.test'], permitted_actions: ['git:read'], network_targets: ['example.test'], expires_at: '2027-02-03T08:11:12.123456Z', side_effect_limits: 'limits', other: 'keep' },
  budgets: { accounting_unit: 'REQUEST_CREDITS', total_seconds: 1800, total_cost_microunits: 1000, max_attempts: 3, max_concurrency: 2, other: 'keep' }, other: { untouched: true },
};
const values = () => ({ sut_kind:'BRANCH', sut_ref:'main', sut_strategy:'HEAD', framework_kind:'MR', framework_ref:'7', framework_strategy:'MERGE', framework_base:'refs/heads/main', prd:'requirements', prd_version:'v1', objective:'objective', basic_flow:'flow', test_scope:'scope', entrypoints:' command with spaces \nsecond', side_effect_limits:'limits', authorization_expires_at:localCloudExpiry(original.authorization.expires_at), accounting_unit:'REQUEST_CREDITS', total_seconds:1800, cost:1000, max_attempts:3 });
test('editing a draft leaves untouched fields and exact expiry intact', () => {
  assert.deepEqual(plain(editedCloudInputs(original, values())), original);
  const changed = plain(editedCloudInputs(original, { ...values(), objective: 'new objective', cost: 2000 }));
  assert.equal(changed.objective, 'new objective');
  assert.equal(changed.budgets.total_cost_microunits, 2000);
  assert.equal(changed.budgets.max_concurrency, 2);
  assert.deepEqual(changed.authorization, original.authorization);
  assert.deepEqual(changed.expected_outputs, original.expected_outputs);
  assert.deepEqual(changed.sut_selector, original.sut_selector);
  assert.deepEqual(changed.framework_entrypoints, original.framework_entrypoints);
  assert.deepEqual(changed.other, original.other);
});
test('changing authorization expiry is explicit and interpreted in local time', () => {
  const local = '2027-06-04T16:20:30.000';
  const changed = plain(editedCloudInputs(original, { ...values(), authorization_expires_at: local }));
  assert.equal(changed.authorization.expires_at, new Date(local).toISOString());
  assert.deepEqual(changed.authorization.targets, original.authorization.targets);
  assert.deepEqual(changed.authorization.permitted_actions, original.authorization.permitted_actions);
  assert.throws(() => editedCloudInputs(original, { ...values(), authorization_expires_at: 'invalid' }));
});

test('draft edit submits its original config and version through the shared operation', async () => {
  const React = require('react'), antd = require('antd');
  const { renderToStaticMarkup } = require('react-dom/server');
  const i18n = load('lib/i18n.tsx', { require });
  const forms = [], submitted = [], completed = [];
  const Form = Object.assign((props) => { forms.push(props); return React.createElement(antd.Form, props); }, antd.Form, { useWatch: () => null });
  const module = load('app/projects/[projectId]/cloud/task-form.tsx', { require: (name) => name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? i18n : name === 'antd' ? { ...antd, Form } : name === 'next/link' ? { default: () => null } : require(name) });
  const config = { id: 'config-original', revision: 4, configuration: { environment: { connection: 'NONE' }, sut: { url: 'https://example.test/sut' }, framework: { url: 'https://example.test/framework' } } };
  const task = { id: 'task-original', title: 'Old title', version: 7, config_id: config.id, inputs: original };
  const operation = { blocked: false, busy: false, pending: null, submit: async (payload) => { submitted.push(payload); return { task_id: task.id }; } };
  renderToStaticMarkup(React.createElement(i18n.I18nProvider, null, React.createElement(module.CloudTaskForm, { config, operation, enabled: true, editTask: task, onCreated: (id) => completed.push(id) })));
  forms[0].onFinish({ ...values(), title: 'Updated title' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submitted.length, 1);
  assert.equal(submitted[0].operation, 'UPDATE_TASK');
  assert.equal(submitted[0].task_id, task.id);
  assert.equal(submitted[0].expected_version, 7);
  assert.equal(submitted[0].config_id, config.id);
  assert.equal(submitted[0].title, 'Updated title');
  assert.deepEqual(plain(submitted[0].inputs), original);
  assert.deepEqual(completed, [task.id]);
});

test('changing resource revision appends only missing repositories to existing authorization', () => {
  const { resourceAuthorizationInputs } = load('app/projects/[projectId]/cloud/task-form.tsx', { require: (name) => name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? {} : name === 'next/link' ? {} : require(name) });
  const config = { configuration: { sut: { url: 'https://example.test' }, framework: { url: 'https://example.test/new-framework' } } };
  const next = plain(resourceAuthorizationInputs(original, config));
  assert.deepEqual(next.authorization.targets, ['https://example.test', 'https://example.test/new-framework']);
  assert.deepEqual(next.authorization.permitted_actions, original.authorization.permitted_actions);
  assert.deepEqual(next.authorization.network_targets, original.authorization.network_targets);
  assert.equal(next.authorization.expires_at, original.authorization.expires_at);
  assert.equal(next.authorization.other, 'keep');
  assert.deepEqual(next.other, original.other);
  const full = { ...original, authorization: { ...original.authorization, targets: Array.from({ length: 64 }, (_, i) => `https://repo${i}.test`) } };
  assert.throws(() => resourceAuthorizationInputs(full, config), /AUTHORIZATION_TARGET_LIMIT/);
});
