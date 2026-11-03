const assert = require('node:assert/strict');
const test = require('node:test');
const load = require('./load-helper.cjs');
const cloud = load('lib/cloud.ts', { URL, TextEncoder, Uint8Array, DataView, Int32Array });
const { editedCloudInputs } = load('app/projects/[projectId]/cloud/task-form.tsx', { URL, require: (name) => name === "@/lib/cloud-test-prompt" ? load("lib/cloud-test-prompt.ts") : name === "@/lib/clipboard" ? load("lib/clipboard.ts") : name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? {} : name === 'next/link' ? {} : require(name) });
const plain = (v) => JSON.parse(JSON.stringify(v));
const original = {
  sut_selector: { kind: 'BRANCH', value: 'main', checkout_strategy: 'HEAD', extension: 'retained' },
  framework_selector: { kind: 'MR', value: '7', checkout_strategy: 'MERGE', base_ref: 'refs/heads/main' },
  mr_url: 'https://example.test/team/sut/-/merge_requests/7', prd_markdown: 'requirements', prd_version: 'v1', objective: 'objective', basic_flow: 'flow', test_scope: 'scope',
  expected_outputs: ['REPORT', 'CASE'], framework_entrypoints: [' command with spaces ', 'second'],
  authorization: { targets: ['https://example.test'], permitted_actions: ['git:read'], network_targets: ['example.test'], expires_at: '2027-02-03T08:11:12.123456Z', side_effect_limits: 'limits', other: 'keep' },
  budgets: { accounting_unit: 'REQUEST_CREDITS', total_seconds: 1800, total_cost_microunits: 1000, max_attempts: 3, max_concurrency: 2, other: 'keep' }, other: { untouched: true },
};
const values = () => ({ mr_url: original.mr_url, prompt: 'Use staging' });
test('editing a draft preserves test content and refreshes internal repository authorization', () => {
  const { authorization, ...content } = original;
  assert.deepEqual(plain(editedCloudInputs(original, values())), { ...content, prompt: 'Use staging' });
  const changed = plain(editedCloudInputs(original, { ...values(), prompt: 'new instructions' }));
  assert.equal(changed.prompt, 'new instructions');
  assert.equal(changed.objective, original.objective);
  assert.deepEqual(changed.budgets, original.budgets);
  assert.equal(changed.budgets.max_concurrency, 2);
  assert.equal(Object.hasOwn(changed, 'authorization'), false);
  assert.deepEqual(original.authorization, authorization);
  assert.deepEqual(changed.expected_outputs, original.expected_outputs);
  assert.deepEqual(changed.sut_selector, original.sut_selector);
  assert.deepEqual(changed.framework_entrypoints, original.framework_entrypoints);
  assert.deepEqual(changed.other, original.other);
});
test('draft edit uses current project repositories and preserves its task version through the shared operation', async () => {
  const React = require('react'), antd = require('antd');
  const { renderToStaticMarkup } = require('react-dom/server');
  const i18n = load('lib/i18n.tsx', { require });
  const forms = [], submitted = [], completed = [];
  const Form = Object.assign((props) => { forms.push(props); return React.createElement(antd.Form, props); }, antd.Form, { useWatch: () => null });
  const module = load('app/projects/[projectId]/cloud/task-form.tsx', { URL, require: (name) => name === "@/lib/cloud-test-prompt" ? load("lib/cloud-test-prompt.ts") : name === "@/lib/clipboard" ? load("lib/clipboard.ts") : name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? i18n : name === 'antd' ? { ...antd, Form } : name === 'next/link' ? { default: () => null } : require(name) });
  const project = { id: 'project-1', row_version: 8, repository_url: 'https://example.test/sut', test_framework_repository_url: 'https://example.test/framework' };
  const task = { id: 'task-original', title: 'Old title', version: 7, config_id: 'historic-config', inputs: original };
  const operation = { blocked: false, busy: false, pending: null, submit: async (payload) => { submitted.push(payload); return { task_id: task.id }; } };
  renderToStaticMarkup(React.createElement(i18n.I18nProvider, null, React.createElement(module.CloudTaskForm, { project, operation, enabled: true, editTask: task, onCreated: (id) => completed.push(id) })));
  forms[0].onFinish({ ...values(), title: 'Updated title' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(submitted.length, 1);
  assert.equal(submitted[0].operation, 'UPDATE_TASK');
  assert.equal(submitted[0].task_id, task.id);
  assert.equal(submitted[0].expected_version, 7);
  assert.equal(Object.hasOwn(submitted[0], 'config_id'), false);
  assert.equal(submitted[0].expected_project_version, 8);
  assert.equal(submitted[0].title, 'Updated title');
  const { authorization, ...content } = original;
  assert.deepEqual(plain(submitted[0].inputs), { ...content, prompt: 'Use staging' });
  assert.deepEqual(original.authorization, authorization);
  assert.deepEqual(completed, [task.id]);
});

test('MR context URL rejects credentials, non-HTTPS and unrelated pages', () => {
  const { validChangeUrl } = load('app/projects/[projectId]/cloud/task-form.tsx', { URL, require: (name) => name === "@/lib/cloud-test-prompt" ? load("lib/cloud-test-prompt.ts") : name === "@/lib/clipboard" ? load("lib/clipboard.ts") : name === '@/lib/cloud' ? cloud : name === '@/lib/i18n' ? {} : name === 'next/link' ? {} : require(name) });
  for (const url of ['https://git.test/team/sut/-/merge_requests/1', 'https://github.com/org/repo/pull/12']) assert.equal(validChangeUrl(url), true);
  for (const url of ['', 'http://git.test/team/sut/-/merge_requests/1', 'https://user:secret@git.test/team/sut/-/merge_requests/1', 'https://git.test/team/sut', 'https://git.test/team/sut/-/merge_requests/0', 'https://git.test/team/sut/-/merge_requests/1?token=secret']) assert.equal(validChangeUrl(url), false);
});

test('changing an MR drops the old SUT selector without mutating the historical input', () => {
  const changed = editedCloudInputs(original, { mr_url: 'https://example.test/team/sut/-/merge_requests/8', prompt: 'New focus' });
  assert.equal(Object.hasOwn(changed, 'sut_selector'), false);
  assert.deepEqual(plain(changed.framework_selector), original.framework_selector);
  assert.equal(original.sut_selector.value, 'main');
});
