"""Focused BFF route regression; no service, SUT or business task is started."""
import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'prepare-macos-cloud-worker.py'
spec = importlib.util.spec_from_file_location('prepare_native_worker_inspection', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('previous_routes', [module.CURRENT_ROUTES, module.INSPECTION_ROUTES])
def test_previous_worker_block_upgrades_only_exact_inspection_and_conversation_routes(previous_routes):
    old_location = module.LOCATION.replace(module.ROUTES, previous_routes)
    before = 'header\n' + old_location + module.ANCHOR + '\nfooter\n'
    result = module.bff_config(before)
    assert result == before.replace(old_location, module.LOCATION, 1)
    assert module.bff_config(result) == result
    assert result.count('location ~ ^/api/v1/cloud/worker/') == 1
    assert 'limit_except POST { deny all; }' in module.LOCATION
    assert 'proxy_set_header X-Hypertest-Operator-Key "";' in module.LOCATION
    pattern = re.compile(r'^/api/v1/cloud/worker/(' + module.ROUTES + r')$')
    for action in ('state', 'claim', 'claim-state', 'claim-reconcile', 'assert', 'finish'):
        assert pattern.fullmatch('/api/v1/cloud/worker/native-session-inspection/' + action)
    for action in ('validate', 'append', 'lookup', 'poll', 'ack', 'recover-append', 'recover-ack'):
        assert pattern.fullmatch('/api/v1/cloud/worker/conversation/' + action)
    assert pattern.fullmatch('/api/v1/cloud/worker/resume/identity')
    for path in ('/api/v1/cloud/worker/native-session-inspection/anything',
                 '/api/v1/cloud/worker/native-session-inspection/claim/extra',
                 '/api/v1/cloud/worker/native-session-inspection',
                 '/api/v1/cloud/worker/submit/extra',
                 '/api/v1/cloud/worker/conversation/anything',
                 '/api/v1/cloud/worker/conversation/poll/extra',
                 '/api/v1/cloud/worker/conversation/recover-ack/extra',
                 '/api/v1/cloud/worker/conversation',
                 '/api/v1/cloud/worker/resume',
                 '/api/v1/cloud/worker/resume/anything',
                 '/api/v1/cloud/worker/resume/identity/extra',
                 '/prefix/api/v1/cloud/worker/resume/identity',
                 '/prefix/api/v1/cloud/worker/conversation/poll',
                 'https://localhost:18444/api/v1/cloud/worker/conversation/poll'):
        assert not pattern.fullmatch(path)


def test_unrecognized_existing_worker_block_is_not_overwritten():
    for routes in (module.ROUTES, module.INSPECTION_ROUTES):
        altered = module.LOCATION.replace(module.ROUTES, routes).replace('proxy_read_timeout 60s;', 'proxy_read_timeout 99s;')
        with pytest.raises(ValueError, match='Unexpected existing Worker route'):
            module.bff_config(altered + module.ANCHOR)
