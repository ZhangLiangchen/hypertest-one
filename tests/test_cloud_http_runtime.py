"""HTTP admission/prompt boundaries without any model, network or SUT."""
import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hypertest.api.cloud_schemas import Environment, TaskInputs
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_profile import HTTPS_SOCKET, digest, validate_profile
from hypertest.cloud.manifests import task_prompt
from hypertest.cloud.sandbox import BubblewrapSandbox, SandboxPolicy


def environment():
    access = {"profile": "HTTPS_CONTROLLED_API_V1", "allowed_addresses": ["1.1.1.1"],
        "resources": [{"key": "status", "method": "GET", "path": "/status", "timeout_seconds": 5,
                       "response_limit_bytes": 1024}], "max_operations": 2}
    access["catalog_sha256"] = digest({**access, "target": "https://api.example.test:443"})
    return {"name": "Synthetic public fixture", "connection": "HTTPS", "host": "api.example.test",
        "port": 443, "cloud_access_policy": "WEB_ONLY", "https_access": access}


def manifest():
    return {"configuration": {"environment": environment()}, "inputs": {"framework_runtime": {"profile": "fixture"},
        "authorization": {"targets": ["https://api.example.test:443"],
            "network_targets": ["https://api.example.test:443"],
            "permitted_actions": ["git:read", "framework:execute", "environment:read"]},
        "budgets": {"total_seconds": 60}}}


def test_old_schema_serialization_never_adds_null_runtime_or_https_fields():
    from test_cloud_tasks import inputs
    old = inputs()
    assert "https_access" not in Environment(name="old").model_dump(mode="json")
    assert TaskInputs.model_validate(old).model_dump(mode="json")["framework_entrypoints"] == old["framework_entrypoints"]
    assert "framework_runtime" not in TaskInputs.model_validate(old).model_dump(mode="json")


@pytest.mark.parametrize("field", ["target", "network", "action", "framework"])
def test_https_policy_requires_exact_frozen_permission_and_framework(field):
    frozen = manifest()
    if field == "target":
        frozen["inputs"]["authorization"]["targets"] = ["api.example.test"]
    elif field == "network":
        frozen["inputs"]["authorization"]["network_targets"].append("https://other.example.test:443")
    elif field == "action":
        frozen["inputs"]["authorization"]["permitted_actions"].remove("environment:read")
    else:
        frozen["inputs"].pop("framework_runtime")
    with pytest.raises(CloudBlocked) as error:
        SandboxPolicy(60, 1, 1024, http_profile=validate_profile(environment())).validate(frozen)
    assert error.value.code == "HTTPS_AUTHORIZATION_MISMATCH"


def test_https_environment_schema_rejects_catalog_changes_credentials_and_local_only():
    for change in ({"credential_version_id": "00000000-0000-4000-8000-000000000001"},
                   {"cloud_access_policy": "LOCAL_ONLY"}, {"port": None}):
        with pytest.raises(ValidationError):
            Environment.model_validate({**environment(), **change})
    changed = deepcopy(environment())
    changed["https_access"]["resources"][0]["method"] = "POST"
    with pytest.raises(ValidationError):
        Environment.model_validate(changed)
    assert Environment.model_validate(environment()).https_access["profile"] == "HTTPS_CONTROLLED_API_V1"


async def test_http_mount_is_only_readonly_unix_socket_and_requires_matching_policy(tmp_path):
    socket = tmp_path / "https.sock"
    server = await asyncio.start_unix_server(lambda *_: None, path=socket)
    try:
        sandbox = BubblewrapSandbox(workspace=tmp_path, dsh_home=tmp_path, broker_socket=tmp_path / "model.sock",
            policy=SandboxPolicy(60, 1, 1024, http_profile=validate_profile(environment())), http_socket=socket)
        assert sandbox.http_mounts() == ["--ro-bind", str(socket), HTTPS_SOCKET]
        sandbox.policy = SandboxPolicy(60, 1, 1024)
        with pytest.raises(CloudBlocked) as error:
            sandbox.http_mounts()
        assert error.value.code == "HTTPS_SOCKET_UNAVAILABLE"
    finally:
        server.close()
        await server.wait_closed()


def test_prompt_declares_exact_resources_and_original_key_recovery_without_general_network():
    task = {"id": str(uuid4()), "frozen_manifest": manifest()}
    prompt = json.loads(task_prompt(task, {"id": str(uuid4())}, http_profile=validate_profile(environment())))
    assert prompt["capabilities"]["remote_network"] is False
    assert prompt["capabilities"]["https_controlled_api"]["resources"] == environment()["https_access"]["resources"]
    assert "query --key ORIGINAL_KEY" in " ".join(prompt["instructions"])
    assert "UNKNOWN" in " ".join(prompt["instructions"])
