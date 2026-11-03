import ast
import importlib.util
import plistlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/prepare-macos-cloud-worker.py"
spec = importlib.util.spec_from_file_location("prepare_macos_cloud_worker", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
installer_spec = importlib.util.spec_from_file_location("install_macos_cloud_worker", SCRIPT.parent / "install-macos-cloud-worker.py")
assert installer_spec and installer_spec.loader
installer = importlib.util.module_from_spec(installer_spec)
installer_spec.loader.exec_module(installer)


def test_worker_proxy_only_adds_narrow_post_routes():
    original = "server {\n        client_max_body_size 2m;\n" + module.ANCHOR + "\n}\n"
    staged = module.bff_config(original)
    assert staged.count(module.ANCHOR) == 1
    assert "location ~ ^/api/v1/cloud/worker/(" in staged
    assert "limit_except POST { deny all; }" in staged
    assert staged.count("client_max_body_size 2m;") == 1
    assert staged.count("client_max_body_size 12m;") == 1
    assert staged.index("client_max_body_size 12m;") > staged.index("location ~ ^/api/v1/cloud/worker/")
    assert staged.index("client_max_body_size 12m;") < staged.index(module.ANCHOR)
    assert 'proxy_set_header X-Hypertest-Operator-Key "";' in staged
    assert staged.index("location ~ ^/api/v1/cloud/worker/") < staged.index(module.ANCHOR)
    assert module.bff_config(staged) == staged
    previous = staged.replace(module.ROUTES, "auth-observation|" + module.LEGACY_ROUTES
                              + "|live-question/(open|lookup|poll|finish)")
    assert module.bff_config(previous) == staged
    with pytest.raises(ValueError):
        module.bff_config(original.replace(module.ANCHOR, "location ~ ^/api/v1/cloud/worker/.* {}\n" + module.ANCHOR))


def test_proxy_routes_match_worker_api():
    source = (SCRIPT.parents[1] / "src/hypertest/api/cloud_worker_routes.py").read_text()
    root = ast.parse(source)
    routes = {decorator.args[0].value.lstrip("/") for node in root.body
              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for decorator in node.decorator_list
              if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
              and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router"
              and decorator.func.attr == "post" and decorator.args and isinstance(decorator.args[0], ast.Constant)}
    assert set(module.ROUTES.split("|")) == routes


def test_worker_agent_has_separate_credential_path_and_verified_tls():
    paths = {name: Path("/tmp") / name for name in ("python", "source", "credential", "dsh_home", "state", "ca")}
    spec = module.agent_plist(**paths, api_url="https://localhost:18444", worker_id="worker-1",
                              path="/usr/bin:/bin", home="/tmp/home", ssh_auth_sock="/tmp/agent")
    encoded = plistlib.dumps(spec)
    assert b"--worker-credential-file" in encoded
    assert b"--ca-file" in encoded
    assert b"SSH_AUTH_SOCK" in encoded
    assert spec["KeepAlive"] is False
    assert "HYPERTEST_OPERATOR_KEY" not in spec["EnvironmentVariables"]
    installer.validate(spec)
    spec["EnvironmentVariables"]["HYPERTEST_OPERATOR_KEY"] = "secret"
    with pytest.raises(ValueError):
        installer.validate(spec)
    with pytest.raises(ValueError):
        module.agent_plist(**paths, api_url="http://localhost:18444", worker_id="worker-1",
                           path="/usr/bin", home="/tmp/home", ssh_auth_sock=None)
