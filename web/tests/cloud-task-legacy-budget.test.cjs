const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const load = require('./load-helper.cjs');

const projectId = '00000000-0000-4000-8000-000000000001';
const taskId = '00000000-0000-4000-8000-000000000002';

function renderDraft(budgets, accepted = true, options = {}) {
  const buttons = [];
  const descriptions = [];
  const submissions = [];
  const passthrough = ({ children }) => React.createElement(React.Fragment, null, children);
  const Button = (props) => { buttons.push(props); return React.createElement('button', { disabled: props.disabled }, props.children); };
  const Form = Object.assign(passthrough, { Item: passthrough });
  const antd = { Alert: passthrough, Button, Descriptions: ({ items }) => { descriptions.push(...items); return null; }, Form, Input: { TextArea: () => null },
    Modal: () => null, Space: passthrough, Steps: () => null, Table: () => null,
    Tabs: ({ items }) => React.createElement(React.Fragment, null, ...items.map((item) => item.children)),
    Tag: passthrough, Typography: { Title: passthrough, Paragraph: passthrough, Text: passthrough } };
  const task = { id: taskId, project_id: projectId, title: 'Fixture', version: 4, config_id: 'config', status: 'DRAFT',
    reported_result: 'NOT_RUN', frozen_manifest: null, inputs: { budgets, objective: 'test', basic_flow: 'flow', test_scope: 'scope', framework_entrypoints: options.entrypoints ?? [] } };
  const resolutions = options.resolutions ?? (accepted ? [{ status: 'ACCEPTED', accepted_task_version: 4, id: 'resolution', result: {} }] : []);
  const detail = { task, resolutions, answers: [], questions: [], assets: [], attempts: [], artifacts: [], runs: [], run_cases: [], delegations: [] };
  const config = { id: 'config', configuration: { environment: { connection: 'NONE' },
    sut: { url: 'https://example.test/sut' }, framework: { url: 'https://example.test/framework' } } };
  const queries = { 'cloud-web-setup': { configured: true }, 'cloud-capabilities': { enabled: true, worker_enabled: options.workerEnabled ?? true },
    'cloud-config': { items: [config] }, 'cloud-task-live': {}, 'cloud-task': detail };
  const cloud = { cloudOperationalView: () => ({ valid: true, status: 'DRAFT', resolutions, attempt: null }), cloudProgressTone: () => '',
    cloudCancellation: () => ({}), cloudConfiguration() {}, cloudDocument() {}, cloudSetup() {}, cloudSummary() {}, cloudCapabilities() {} };
  const component = load('app/cloud-tasks/[taskId]/page.tsx', { URLSearchParams, require: (name) => {
    if (name === 'antd') return antd;
    if (name === '@ant-design/icons') return { ReloadOutlined: () => null };
    if (name === 'next/navigation') return { useParams: () => ({ taskId }), useSearchParams: () => new URLSearchParams({ projectId }) };
    if (name === '@tanstack/react-query') return { useQuery: ({ queryKey }) => ({ data: queries[queryKey[0]], isError: queryKey[0] === 'cloud-task-live' && options.liveError, refetch() {} }) };
    if (name === '@/lib/api') return { getProject() {} };
    if (name === '@/lib/cloud') return cloud;
    if (name === '@/lib/i18n') return { useI18n: () => ({ t: (en) => en, label: (v) => v }) };
    if (name === '@/lib/cloud-operation') return { useCloudOperation: () => ({ blocked: false, submit(fields) { submissions.push(fields); } }) };
    if (name === '@/lib/run-polling') return { cloudPollingVersion: () => 4, cloudSummaryPollInterval() {}, readCloudPollingDocument() {} };
    if (name === '@/app/workspace-ui') return { WorkspaceHeading: passthrough, WorkspaceLoading: () => null };
    if (name === '@/app/tasks/task-records') return { ReportedResultTag: () => null };
    if (name === '@/app/projects/[projectId]/cloud/cloud-shared') return { CloudAttemptRecovery: () => null, CloudCapabilitiesNotice: () => null, CloudOperationNotice: () => null };
    if (name === '@/app/projects/[projectId]/cloud/task-form') return { CloudTaskForm: () => null };
    if (name === './records') return { CloudTaskRecords: () => null };
    if (name === './live-questions-panel') return { LiveQuestionsPanel: () => null };
    if (name === './retry-dialog') return { RetryDialog: () => null };
    if (name === './recovery-choice') return { RecoveryChoice: () => null };
    if (name === './delete-task') return { CloudTaskDelete: () => null };
    return require(name);
  } });
  const html = renderToStaticMarkup(React.createElement(component.default));
  return { buttons: Object.fromEntries(buttons.filter((b) => typeof b.children === 'string').map((b) => [b.children, b])), descriptions, submissions, html };
}

test('legacy budget drafts use the same start operation so the server can refresh old inputs', () => {
  const page = renderDraft({ total_seconds: 600 });
  assert.equal(page.buttons['Start test'].disabled, false);
  page.buttons['Start test'].onClick();
  assert.equal(page.submissions[0].operation, 'START_TASK');
});

test('one start request works with or without previously accepted source versions', () => {
  for (const accepted of [true, false]) {
    const page = renderDraft(null, accepted);
    assert.equal(page.buttons['Start test'].disabled, false);
    assert.equal(page.buttons['Prepare source context'], undefined);
    assert.equal(page.buttons['Dispatch test task'], undefined);
    assert.equal(page.submissions.length, 0);
    page.buttons['Start test'].onClick();
    assert.deepEqual(JSON.parse(JSON.stringify(page.submissions)), [{ operation: 'START_TASK', task_id: taskId, expected_version: 4 }]);
  }
});

test('active preparation and unknown outcomes cannot submit another start', () => {
  for (const status of ['PENDING', 'RESOLVING', 'RECOVERY_REQUIRED']) {
    const page = renderDraft(null, false, { resolutions: [{ status, source_draft_version: 4, start_requested: true }] });
    assert.equal((page.buttons['Start test'] || page.buttons['Preparing test']).disabled, true);
    if (status !== 'RECOVERY_REQUIRED') assert.match(page.html, /dispatched automatically/);
  }
  for (const options of [{ workerEnabled: false }, { liveError: true }]) {
    assert.equal(renderDraft(null, false, options).buttons['Start test'].disabled, true);
  }
  assert.equal(renderDraft(null, false, { resolutions: [{ status: 'FAILED', source_draft_version: 4 }] }).buttons['Start test'].disabled, false);
});

test('task intent omits framework entrypoints and code versions are collapsed', () => {
  for (const entrypoints of [[], ['pytest']]) {
    const page = renderDraft(null, true, { entrypoints });
    assert.equal(page.descriptions.some((item) => item.key === 'entrypoints'), false);
    assert.match(page.html, /<details class="cloud-task-source-details"><summary>Code version details<\/summary>/);
  }
});
