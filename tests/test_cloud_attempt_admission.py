"""Worker-wide admission must not consume an Attempt or contact a model."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from hypertest.cloud import worker
from hypertest.cloud.errors import CloudBlocked


class Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_):
        return False


def settings(key_path, rate=1):
    return SimpleNamespace(cloud_enabled=True, cloud_worker_enabled=True,
        cloud_worker_lease_seconds=30, cloud_model_request_cost_microunits=rate,
        cloud_model_key_file=str(key_path))


def install_inert_poll(monkeypatch, *, resolution=None):
    events = []
    monkeypatch.setattr(worker, "inspect_resource_envelope", lambda: events.append("resources"))

    async def probe():
        events.append("namespace")

    async def expire(*_args, **_kwargs):
        events.append("expire")

    async def claim_resolution(*_args, **_kwargs):
        events.append("resolution")
        return resolution

    async def claim_attempt(*_args, **_kwargs):
        events.append("attempt")
        return None

    monkeypatch.setattr(worker, "probe_namespace", probe)
    monkeypatch.setattr(worker.service, "expire_leases", expire)
    monkeypatch.setattr(worker.service, "claim_resolution", claim_resolution)
    monkeypatch.setattr(worker.service, "claim_attempt", claim_attempt)
    monkeypatch.setattr(worker, "ModelBroker", lambda *_a, **_kw: pytest.fail("model broker started"))
    return events


@pytest.mark.parametrize("failure,code", [
    ("rate", "MODEL_COST_UNCONFIGURED"),
    ("sdk", "SDK_UNAVAILABLE"),
    ("missing", "MODEL_KEY_UNAVAILABLE"),
    ("unsafe", "MODEL_KEY_PERMISSIONS"),
    ("multiline", "MODEL_IDENTITY_UNAVAILABLE"),
])
async def test_invalid_global_prerequisite_never_claims_attempt(monkeypatch, tmp_path, failure, code):
    path = tmp_path / "key"
    if failure != "missing":
        path.write_bytes(b"synthetic-key\nsecond-line" if failure == "multiline" else b"synthetic-key")
        path.chmod(0o644 if failure == "unsafe" else 0o600)
    events = install_inert_poll(monkeypatch)

    def inspect():
        events.append("sdk")
        if failure == "sdk":
            raise CloudBlocked("SDK_UNAVAILABLE", "private-canary")

    monkeypatch.setattr(worker, "inspect_sdk", inspect)
    instance = worker.CloudWorker(Session, settings(path, 0 if failure == "rate" else 1), "worker")
    with pytest.raises(CloudBlocked) as error:
        await instance.run_once()
    assert error.value.code == code
    assert instance._attempt_admission_failure == code
    assert "expire" in events and "resolution" in events and "attempt" not in events


async def test_resolution_does_not_require_model_setup(monkeypatch, tmp_path):
    events = install_inert_poll(monkeypatch, resolution={"fixture": True})
    monkeypatch.setattr(worker, "inspect_sdk", lambda: pytest.fail("SDK checked for resolution"))
    monkeypatch.setattr(worker, "read_model_key", lambda *_: pytest.fail("model identity read for resolution"))
    instance = worker.CloudWorker(Session, settings(tmp_path / "missing", 0), "worker")

    async def resolve(claim):
        assert claim == {"fixture": True}
        events.append("resolve")

    monkeypatch.setattr(instance, "resolve", resolve)
    assert await instance.run_once() is True
    assert events == ["resources", "expire", "namespace", "resolution", "resolve"]


async def test_sdk_checked_once_and_key_rechecked_before_each_attempt_claim(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_bytes(b"synthetic-key")
    key.chmod(0o600)
    events = install_inert_poll(monkeypatch)
    monkeypatch.setattr(worker, "inspect_sdk", lambda: events.append("sdk"))
    instance = worker.CloudWorker(Session, settings(key), "worker")
    assert await instance.run_once() is False
    key.unlink()
    with pytest.raises(CloudBlocked) as error:
        await instance.run_once()
    assert error.value.code == "MODEL_KEY_UNAVAILABLE"
    assert events.count("sdk") == 1 and events.count("expire") == 2
    assert events.count("resolution") == 2 and events.count("attempt") == 1


async def test_cli_logs_one_repeated_admission_failure_but_continues_resolution(monkeypatch, capsys):
    from hypertest.cloud import __main__ as cli

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(cloud_enabled=True,
        cloud_worker_enabled=True, cloud_service_release_sha256="", cloud_worker_poll_seconds=0.1))
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_: None)

    class Engine:
        async def dispose(self):
            pass

    class FailedWorker:
        _namespace_failure = None
        _attempt_admission_failure = None

        def __init__(self, *_):
            self.calls = 0

        async def run_once(self):
            self.calls += 1
            if self.calls == 3:
                self._attempt_admission_failure = None
                return True  # an independently processable resolution
            if self.calls == 5:
                raise asyncio.CancelledError
            self._attempt_admission_failure = "MODEL_KEY_UNAVAILABLE"
            raise CloudBlocked("MODEL_KEY_UNAVAILABLE", "synthetic-private-canary")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(worker, "CloudWorker", FailedWorker)
    monkeypatch.setattr(cli.asyncio, "sleep", no_sleep)
    monkeypatch.setitem(sys.modules, "hypertest.db.session", SimpleNamespace(AsyncSessionLocal=object(), engine=Engine()))
    assert await cli.run(once=False) == 130
    output = capsys.readouterr().out
    assert [json.loads(line)["code"] for line in output.splitlines()] == ["MODEL_KEY_UNAVAILABLE"] * 2
    assert "synthetic-private-canary" not in output
