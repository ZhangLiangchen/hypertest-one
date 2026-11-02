const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const load = require('./load-helper.cjs');

const projectId = '00000000-0000-4000-8000-000000000001';
const taskId = '00000000-0000-4000-8000-000000000002';

function renderDraft(budgets, accepted = true) {
  const buttons = [];
  const passthrough = ({ children }) => React.createElement(React.Fragment, null, children);
  const Button = (props) => { buttons.push(props); return React.createElement('button', { disabled: props.disabled }, props.children); };
  const Form = Object.assign(passthrough, { Item: passthrough });
  const antd = { Alert: passthrough, Button, Descriptions: () => null, Form, Input: { TextArea: () => null },
    Modal: () => null, Space: passthrough, Steps: () => null, Table: () => null,
    Tabs: ({ items }) => React.createElement(React.Fragment, null, ...items.map((item) => item.children)),
    Tag: passthrough, Typography: { Title: passthrough, Paragraph: passthrough, Text: passthrough } };
  const task = { id: taskId, project_id: projectId, title: 'Fixture', version: 4, config_id: 'config', status: 'DRAFT',
    reported_result: 'NOT_RUN', frozen_manifest: null, inputs: { budgets, objective: 'test', basic_flow: 'flow', test_scope: 'scope' } };
  const resolutions = accepted ? [{ status: 'ACCEPTED', accepted_task_version: 4, id: 'resolution', result: {} }] : [];
  const detail = { task, resolutions, answers: [], questions: [], assets: [], attempts: [], artifacts: [], runs: [], run_cases: [], delegations: [] };
  const config = { id: 'config', configuration: { environment: { connection: 'NONE' },
    sut: { url: 'https://example.test/sut' }, framework: { url: 'https://example.test/framework' } } };
  const queries = { 'cloud-web-setup': { configured: true }, 'cloud-capabilities': { enabled: true, worker_enabled: true },
    'cloud-config': { items: [config] }, 'cloud-task-live': {}, 'cloud-task': detail };
  const cloud = { cloudOperationalView: () => ({ valid: true, status: 'DRAFT', resolutions, attempt: null }), cloudProgressTone: () => '',
    cloudCancellation: () => ({}), cloudConfiguration() {}, cloudDocument() {}, cloudSetup() {}, cloudSummary() {}, cloudCapabilities() {} };
  const component = load('app/cloud-tasks/[taskId]/page.tsx', { URLSearchParams, require: (name) => {
    if (name === 'antd') return antd;
    if (name === '@ant-design/icons') return { ReloadOutlined: () => null };
    if (name === 'next/navigation') return { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams({ projectId }) };
    if (name === '@tanstack/react-query') return { useQuery: ({ queryKey }) => ({ data: queries[queryKey[0]], refetch() {} }) };
    if (name === '@/lib/cloud') return cloud;
    if (name === '@/lib/i18n') return { useI18n: () => ({ t: (en) => en, label: (v) => v }) };
    if (name === '@/lib/cloud-operation') return { useCloudOperation: () => ({ blocked: false, submit() {} }) };
    if (name === '@/lib/run-polling') return { cloudPollingVersion: () => 4, cloudSummaryPollInterval() {}, readCloudPollingDocument() {} };
    if (name === '@/app/workspace-ui') return { WorkspaceHeading: passthrough, WorkspaceLoading: () => null };
    if (name === '@/app/tasks/task-records') return { ReportedResultTag: () => null };
    if (name === '@/app/projects/[projectId]/cloud/cloud-shared') return { CloudAttemptRecovery: () => null, CloudCapabilitiesNotice: () => null, CloudOperationNotice: () => null };
    if (name === '@/app/projects/[projectId]/cloud/task-form') return { CloudTaskForm: () => null };
    if (name === './records') return { CloudTaskRecords: () => null };
    if (name === './live-questions-panel') return { LiveQuestionsPanel: () => null };
    if (name === './retry-dialog') return { RetryDialog: () => null };
    if (name === './delete-task') return { CloudTaskDelete: () => null };
    return require(name);
  } });
  renderToStaticMarkup(React.createElement(component.default));
  return Object.fromEntries(buttons.filter((b) => typeof b.children === 'string').map((b) => [b.children, !!b.disabled]));
}

test('legacy budget draft can resolve again but cannot dispatch an old resolution', () => {
  const buttons = renderDraft({ total_seconds: 600 });
  assert.equal(buttons['Resolve both repositories'], false);
  assert.equal(buttons['Dispatch these exact versions'], true);
});

test('new budgetless draft keeps normal resolution and dispatch controls', () => {
  const accepted = renderDraft(null);
  assert.equal(accepted['Resolve both repositories'], true);
  assert.equal(accepted['Dispatch these exact versions'], false);
  const unresolved = renderDraft(null, false);
  assert.equal(unresolved['Resolve both repositories'], false);
  assert.equal(unresolved['Dispatch these exact versions'], true);
});
