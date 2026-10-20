from uuid import uuid4

import pytest
from pydantic import ValidationError

from hypertest.api.connector_schemas import CapabilityRequest


def test_managed_harness_scope_compatibility_and_explicit_interactive_host_policy():
    base = {"project_id": uuid4(), "capability": "harness"}
    assert CapabilityRequest(**base).constraints == {}
    approved = {"interactive_host_adapters": ["codex-desktop-stdio/v1"]}
    assert CapabilityRequest(**base, constraints=approved).constraints == approved


@pytest.mark.parametrize("constraints", [
    {"token": "not-a-configuration-field"},
    {"interactive_host_adapters": []},
    {"interactive_host_adapters": ["duplicate", "duplicate"]},
    {"interactive_host_adapters": ["https://arbitrary.invalid/endpoint"]},
    {"interactive_host_adapters": "codex-desktop-stdio/v1"},
])
def test_interactive_scope_does_not_accept_credentials_or_arbitrary_configuration(constraints):
    with pytest.raises(ValidationError):
        CapabilityRequest(project_id=uuid4(), capability="harness", constraints=constraints)
