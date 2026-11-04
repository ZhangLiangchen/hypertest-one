"""One-shot inspection claims are never replayed, including after a lost reply."""
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import native_session_restore as restore
from hypertest.cloud import native_worker as worker
from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def args(tmp_path):
    return SimpleNamespace(worker_id='synthetic-worker', lease_seconds=90, poll_seconds=.01,
                           once=False, dsh_home=str(tmp_path / 'dsh'))


class Api:
    def __init__(self, state, mode='success'):
        self.state, self.mode = state, mode
        self.calls = []
        self.inspection_id, self.attempt_id, self.task_id, self.project_id = (str(uuid4()) for _ in range(4))
        self.claim_request = None
        self.assertions = 0

    async def request_api(self, operation, body):
        self.calls.append(operation)
        if operation.endswith('/state'):
            return {'worker_id': body['worker_id'], 'sequence': 0, 'request_key': None,
                    'kind': 'EMPTY', 'closed': True, 'inspection_id': None}
        if operation.endswith('/claim'):
            self.claim_request = dict(body)
            pending = worker.pending_inspection_claim(self.state, body['worker_id'])
            assert pending and pending[1] == body
            assert 'token' not in pending[0].read_text()
            if self.mode in {'lost-empty', 'lost-inspection'}:
                raise OSError('synthetic lost response')
            if self.mode == 'empty':
                return {**body, 'kind': 'EMPTY', 'closed': True, 'inspection_id': None, 'inspection': None}
            item = {'id': self.inspection_id, 'project_id': self.project_id, 'task_id': self.task_id,
                    'attempt_id': self.attempt_id, 'worker_id': body['worker_id'], 'state': 'STARTED',
                    'session_id': 'cloud-' + self.attempt_id, 'token': 'synthetic-token-1234567890',
                    'identity_digest': 'a' * 64, 'input_digest': 'b' * 64, 'original_generation': 1,
                    'source': {'sut': 'c' * 40, 'framework': 'd' * 40}}
            return {**body, 'kind': 'INSPECTION', 'closed': False,
                    'inspection_id': self.inspection_id, 'inspection': item}
        if operation.endswith('/assert'):
            self.assertions += 1
            if self.mode == 'revoked':
                raise CloudBlocked('REVOKED', 'synthetic')
            return {'active': True}
        if operation.endswith('/finish'):
            if self.mode in {'finish-lost', 'finish-unknown'}:
                raise OSError('synthetic lost finish')
            return {'id': self.inspection_id, 'attempt_id': self.attempt_id, 'state': 'RESTORED'}
        if operation.endswith('/claim-state'):
            if self.mode == 'finish-lost':
                return {'id': self.inspection_id, 'attempt_id': self.attempt_id,
                        'claim_key': self.claim_request['request_key'], 'state': 'RESTORED'}
            return {'id': self.inspection_id, 'attempt_id': self.attempt_id,
                    'claim_key': self.claim_request['request_key'], 'state': 'UNKNOWN'}
        if operation.endswith('/claim-reconcile'):
            kind = 'ABANDONED' if self.mode == 'lost-empty' else 'INSPECTION'
            return {**body, 'kind': kind, 'closed': True, 'inspection_id': self.inspection_id if kind == 'INSPECTION' else None}
        raise AssertionError(operation)


def _allow_inspection(monkeypatch, calls):
    monkeypatch.setattr(restore, 'anchored_identity_for_inspection', lambda **kw: {'synthetic': True})
    async def inspect(**kwargs):
        calls.append('inspect')
        await kwargs['assert_active']()
        return {'restored': True}
    monkeypatch.setattr(restore, 'inspect_original_session_guarded', inspect)


@pytest.mark.asyncio
async def test_empty_inspection_is_a_single_sealed_claim(tmp_path, args):
    api = Api(tmp_path, 'empty')
    api.request = api.request_api
    assert not await worker.inspect_next_original_session(api, args, tmp_path)
    assert api.calls == ['native-session-inspection/state', 'native-session-inspection/claim']
    assert not (tmp_path / 'inspection-claim-pending.json').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['lost-empty', 'lost-inspection'])
async def test_lost_claim_is_never_reposted(tmp_path, args, mode):
    api = Api(tmp_path, mode)
    api.request = api.request_api
    if mode == 'lost-empty':
        assert not await worker.inspect_next_original_session(api, args, tmp_path)
        assert not (tmp_path / 'inspection-claim-pending.json').exists()
    else:
        with pytest.raises(CloudBlocked):
            await worker.inspect_next_original_session(api, args, tmp_path)
        assert (tmp_path / 'inspection-claim-pending.json').exists()
    assert api.calls.count('native-session-inspection/claim') == 1
    assert api.calls.count('native-session-inspection/claim-reconcile') == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'finish-lost'])
async def test_success_or_lost_finish_reads_original_only(tmp_path, args, monkeypatch, mode):
    calls = []
    _allow_inspection(monkeypatch, calls)
    api = Api(tmp_path, mode)
    api.request = api.request_api
    assert await worker.inspect_next_original_session(api, args, tmp_path)
    assert calls == ['inspect'] and api.assertions == 2
    assert api.calls.count('native-session-inspection/finish') == 1
    assert api.calls.count('native-session-inspection/claim') == 1
    assert ('native-session-inspection/claim-state' in api.calls) == (mode == 'finish-lost')
    assert not (tmp_path / 'inspection-claim-pending.json').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['finish-unknown', 'revoked'])
async def test_unknown_or_revoked_inspection_never_retries_or_clears_original(tmp_path, args, monkeypatch, mode):
    calls = []
    _allow_inspection(monkeypatch, calls)
    api = Api(tmp_path, mode)
    api.request = api.request_api
    with pytest.raises(CloudBlocked):
        await worker.inspect_next_original_session(api, args, tmp_path)
    assert calls == ([] if mode == 'revoked' else ['inspect'])
    assert api.calls.count('native-session-inspection/claim') == 1
    assert api.calls.count('native-session-inspection/finish') <= 1
    assert (tmp_path / 'inspection-claim-pending.json').exists()


def test_anchored_identity_rejects_tampering_without_reading_profile(tmp_path, monkeypatch):
    attempt, project, task = (str(uuid4()) for _ in range(3))
    root = tmp_path.resolve() / ('attempt-' + attempt)
    root.mkdir(mode=0o700)
    workspace, home = root / 'workspace', tmp_path.resolve() / 'dsh'
    workspace.mkdir()
    home.mkdir()
    metadata = {'profile': 'hypertest-native-session-identity/v1', 'project_id': project, 'task_id': task,
                'attempt_id': attempt, 'session_id': 'cloud-' + attempt, 'input_digest': 'a' * 64,
                'worker_id': 'synthetic-worker', 'original_generation': 1, 'prompt_sha256': 'b' * 64,
                'title_sha256': 'f' * 64,
                'workspace': restore._directory(workspace)[1], 'dsh_home': restore._directory(home)[1],
                'source': {'sut': 'c' * 40, 'framework': 'd' * 40}, 'runtime': {'fixture': True}}
    encoded = restore._canonical(metadata)
    path = root / restore.FILENAME
    path.write_bytes(encoded)
    path.chmod(0o600)
    intent = root / 'prompt-intent.json'
    intent.write_text('{"state":"SENT","session_id":"cloud-' + attempt + '","prompt_sha256":"' + 'b' * 64 + '"}')
    intent.chmod(0o600)
    monkeypatch.setattr(restore, '_runtime_identity', lambda: {'fixture': True})
    inspection = {'project_id': project, 'task_id': task, 'attempt_id': attempt, 'session_id': 'cloud-' + attempt,
                  'input_digest': 'a' * 64, 'identity_digest': hashlib.sha256(encoded).hexdigest(),
                  'worker_id': 'synthetic-worker', 'original_generation': 1,
                  'sut_commit': 'c' * 40, 'framework_commit': 'd' * 40}
    found = restore.anchored_identity_for_inspection(attempt_root=root, dsh_home=home, inspection=inspection,
                                                      worker_id='synthetic-worker', environment={'PATH': '/bin'})
    assert found['selection'] is None and found['prompt_sha256'] == 'b' * 64 and found['title_sha256'] == 'f' * 64
    path.write_bytes(encoded + b' ')
    with pytest.raises(CloudBlocked):
        restore.anchored_identity_for_inspection(attempt_root=root, dsh_home=home, inspection=inspection,
                                                 worker_id='synthetic-worker', environment={'PATH': '/bin'})


@pytest.mark.asyncio
async def test_default_disabled_never_polls_inspection_and_keeps_normal_claim(tmp_path, args, monkeypatch):
    from hypertest import config
    from hypertest.cloud import native_profile, sdk

    calls = []
    class WorkerApi:
        def __init__(self, *unused, **kwargs): pass
        async def request(self, operation, body):
            calls.append(operation)
            if operation == 'claim/state':
                return {'worker_id': args.worker_id, 'slot_id': body['slot_id'], 'sequence': 0, 'request_key': None,
                        'kind': 'EMPTY', 'closed': True}
            if operation == 'claim':
                return {'worker_id': args.worker_id, 'slot_id': body['slot_id'], 'sequence': body['sequence'],
                        'request_key': body['request_key'], 'kind': 'EMPTY', 'closed': True, 'claim': None}
            if operation == 'auth-observation':
                return {'recorded': True}
            raise AssertionError(operation)
        async def close(self): pass

    async def not_enabled(*unused):
        pytest.fail('disabled inspection must not be polled')
    token = tmp_path / 'worker-token'
    token.write_text('synthetic-token-' + 'x' * 32)
    token.chmod(0o600)
    args.state_dir, args.worker_credential_file, args.api_url, args.ca_file, args.once = (
        str(tmp_path), str(token), 'https://example.invalid', None, True)
    monkeypatch.setattr(worker, 'WorkerAPI', WorkerApi)
    monkeypatch.setattr(worker, 'check_cordis_runtime', lambda: None)
    monkeypatch.setattr(worker, 'inspect_next_original_session', not_enabled)
    monkeypatch.setattr(sdk, 'inspect_native_sdk', lambda: None)
    monkeypatch.setattr(native_profile, 'check_sdk_profile', lambda _: None)
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(cloud_native_session_inspection_enabled=False))
    assert await worker.run(args) == 0
    assert [name for name in calls if name != 'auth-observation'] == ['claim/state', 'claim']


@pytest.mark.asyncio
async def test_original_inspection_claim_is_sealed_before_sdk_preflight_even_when_disabled(tmp_path, args, monkeypatch):
    calls = []
    request = {'worker_id': args.worker_id, 'request_key': 'original-inspection-key-123456',
               'sequence': 1, 'lease_seconds': 90}
    worker.prepare_inspection_claim(tmp_path, request)
    token = tmp_path / 'worker-token'
    token.write_text('synthetic-token-' + 'x' * 32)
    token.chmod(0o600)
    args.state_dir, args.worker_credential_file, args.api_url, args.ca_file, args.once = (
        str(tmp_path), str(token), 'https://example.invalid', None, True)
    class WorkerApi:
        def __init__(self, *unused, **kwargs): pass
        async def request(self, operation, body):
            calls.append((operation, body))
            assert operation == 'native-session-inspection/claim-reconcile' and body == request
            return {**body, 'kind': 'ABANDONED', 'closed': True, 'inspection_id': None}
        async def close(self): pass
    monkeypatch.setattr(worker, 'WorkerAPI', WorkerApi)
    monkeypatch.setattr(worker, 'check_cordis_runtime', lambda: pytest.fail('recovery precedes SDK'))
    assert await worker.run(args) == 0
    assert calls == [('native-session-inspection/claim-reconcile', request)]
    assert not (tmp_path / 'inspection-claim-pending.json').exists()


@pytest.mark.asyncio
async def test_conflicting_original_claim_journals_block_before_api(tmp_path, args, monkeypatch):
    from hypertest.cloud import sdk

    normal = {'worker_id': args.worker_id, 'request_key': 'original-normal-claim-123456', 'sequence': 1,
              'lease_seconds': 90, 'supports_attempt_manifest': True}
    inspection = {'worker_id': args.worker_id, 'request_key': 'original-inspection-key-123456',
                  'sequence': 1, 'lease_seconds': 90}
    worker.prepare_claim(tmp_path, normal)
    worker.prepare_inspection_claim(tmp_path, inspection)
    args.state_dir = str(tmp_path)
    monkeypatch.setattr(worker, 'WorkerAPI', lambda *a, **kw: pytest.fail('API not allowed'))
    monkeypatch.setattr(sdk, 'inspect_native_sdk', lambda: pytest.fail('SDK not allowed'))
    with pytest.raises(CloudBlocked, match='Conflicting'):
        await worker.run(args)
    assert worker.pending_claim(tmp_path, args.worker_id)[1] == normal
    assert worker.pending_inspection_claim(tmp_path, args.worker_id)[1] == inspection
