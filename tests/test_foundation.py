from fastapi.testclient import TestClient

from hypertest.application.services import canonical_json_sha256
from hypertest.common.ids import public_key, uuid7
from hypertest.main import app


def test_uuid7_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_public_key_keeps_domain_prefix() -> None:
    assert public_key("MIS").startswith("MIS-")


def test_public_keys_remain_unique_within_one_millisecond(monkeypatch) -> None:
    monkeypatch.setattr("hypertest.common.ids.time.time", lambda: 1_700_000_000.0)
    assert len({public_key("MIS") for _ in range(1000)}) == 1000


def test_canonical_hash_is_order_independent() -> None:
    left = canonical_json_sha256({"b": 2, "a": 1})
    right = canonical_json_sha256({"a": 1, "b": 2})
    assert left == right


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "hypertest-one"}
