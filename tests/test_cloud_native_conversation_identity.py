"""Adoption records only a present baseline, never an earlier prompt anchor."""
import json

import pytest
from test_cloud_native_resume_identity import original as original

from hypertest.cloud import native_conversation_identity as adopted
from hypertest.cloud import native_resume_identity as anchored
from hypertest.cloud.errors import CloudBlocked


def present(original, monkeypatch):
    root, previous = original
    monkeypatch.setattr(adopted, "_runtime_identity", anchored._runtime_identity)
    values = {key: value for key, value in previous.items() if key not in {"original_generation", "prompt_sha256"}}
    values.update(generation=3, operation_key="operator-continuation-original", adopted_at="2026-11-04T00:00:00+00:00")
    return root, values


def test_adoption_is_nonsecret_immutable_current_identity_without_historical_anchor(original, monkeypatch):
    root, values = present(original, monkeypatch)
    digest = adopted.record_adopted_identity(root, **values)
    path = root / "adopted-identity-3.json"
    raw = path.read_text()
    record = json.loads(raw)
    assert record["source"] == "OPERATOR_ADOPTED" and not record["historical_identity_preanchored"]
    assert "prompt_sha256" not in record and not (root / anchored.FILENAME).exists()
    assert "SECRET_NOT_IN_IDENTITY" not in raw and "NEVER_READ_OR_STORE_THIS_TEST_SECRET" not in raw
    assert str(values["workspace"]) not in raw and path.stat().st_mode & 0o777 == 0o600
    assert adopted.verify_adopted_identity(root, expected_identity_digest=digest, **values) == record
    with pytest.raises(CloudBlocked):
        adopted.record_adopted_identity(root, **values)
    assert path.read_text() == raw


@pytest.mark.parametrize("change", ["generation", "operation_key", "source"])
def test_adoption_cannot_be_reused_with_changed_identity(original, monkeypatch, change):
    root, values = present(original, monkeypatch)
    digest = adopted.record_adopted_identity(root, **values)
    if change == "generation":
        values["generation"] = 4
    elif change == "operation_key":
        values["operation_key"] = "another-operator-key"
    else:
        values["sut_commit"] = "0" * 40
    with pytest.raises(CloudBlocked) as error:
        adopted.verify_adopted_identity(root, expected_identity_digest=digest, **values)
    assert error.value.code == "NATIVE_SESSION_IDENTITY_UNAVAILABLE"
