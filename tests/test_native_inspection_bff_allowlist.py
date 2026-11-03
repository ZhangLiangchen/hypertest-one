"""Focused BFF route regression; no service, SUT or business task is started."""
import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'prepare-macos-cloud-worker.py'
spec = importlib.util.spec_from_file_location('prepare_native_worker_inspection', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_previous_worker_block_upgrades_only_exact_inspection_routes():
    old_location = module.LOCATION.replace(module.ROUTES, module.CURRENT_ROUTES)
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
    for path in ('/api/v1/cloud/worker/native-session-inspection/anything',
                 '/api/v1/cloud/worker/native-session-inspection/claim/extra',
                 '/api/v1/cloud/worker/native-session-inspection',
                 '/api/v1/cloud/worker/submit/extra'):
        assert not pattern.fullmatch(path)


def test_unrecognized_existing_worker_block_is_not_overwritten():
    altered = module.LOCATION.replace('proxy_read_timeout 60s;', 'proxy_read_timeout 99s;')
    with pytest.raises(ValueError, match='Unexpected existing Worker route'):
        module.bff_config(altered + module.ANCHOR)
