"""Only a frozen, authorized action profile can admit its brokered target."""
from copy import deepcopy

import pytest
from test_cloud_action_profile import profile

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.sandbox import SandboxPolicy


def manifest():
    action = profile()
    return {"inputs": {"authorization": {"network_targets": [action["target"]], "targets": [action["target"]],
        "permitted_actions": ["git:read", "framework:execute", "environment:read", "environment:write"]},
        "controlled_actions": action, "budgets": {"total_seconds": 60}},
        "configuration": {"environment": {"connection": "HTTPS", "host": "api.example.invalid", "port": 443,
            "cloud_access_policy": "WEB_ONLY"}},
        "resolution": {"repositories": {"framework": {"commit_sha": "a" * 40}}}}


def test_fixed_controlled_action_allows_only_its_frozen_environment():
    frozen = manifest()
    SandboxPolicy(60, 1, 1024, controlled_actions=deepcopy(frozen["inputs"]["controlled_actions"])).validate(frozen)


@pytest.mark.parametrize("change", ["missing_read", "missing_write", "extra_network", "wrong_target", "wrong_commit",
                                     "different_plan", "invalid_plan", "local_only", "unrelated_write"])
def test_controlled_actions_reject_missing_scope_or_changed_frozen_identity(change):
    frozen = manifest()
    policy = deepcopy(frozen["inputs"]["controlled_actions"])
    authorization = frozen["inputs"]["authorization"]
    if change == "missing_read":
        authorization["permitted_actions"].remove("environment:read")
    elif change == "missing_write":
        authorization["permitted_actions"].remove("environment:write")
    elif change == "extra_network":
        authorization["network_targets"].append("https://other.example.invalid:443")
    elif change == "wrong_target":
        frozen["configuration"]["environment"]["host"] = "other.example.invalid"
    elif change == "wrong_commit":
        frozen["resolution"]["repositories"]["framework"]["commit_sha"] = "b" * 40
    elif change == "different_plan":
        frozen["inputs"]["controlled_actions"]["actions"][0]["expected_body"]["amount"] = "4"
    elif change == "invalid_plan":
        policy["actions"][0]["method"] = "GET"
        frozen["inputs"]["controlled_actions"] = policy
    elif change == "local_only":
        frozen["configuration"]["environment"]["cloud_access_policy"] = "LOCAL_ONLY"
    else:
        authorization["permitted_actions"].append("ci:execute")
    with pytest.raises(CloudBlocked):
        SandboxPolicy(60, 1, 1024, controlled_actions=policy).validate(frozen)


def test_profile_cannot_be_assumed_from_network_authorization_alone():
    with pytest.raises(CloudBlocked, match="remote SUT"):
        SandboxPolicy(60, 1, 1024).validate(manifest())
