"""The offline image builder rejects mutable input and changed dependency contracts."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def builder(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "ops/deepseek/build_worker_offline.py"
    spec = importlib.util.spec_from_file_location("offline_worker_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commit = "a" * 40
    monkeypatch.setattr(module, "run", lambda args, **kwargs: "" if args[:2] == ["git", "status"] else commit)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(module, "WHEELS", {"build-1-py3-none-any.whl": hashlib.sha256(b"trusted").hexdigest()})
    monkeypatch.setattr(module, "RUNTIME_WHEELS", {})
    return module, commit


def test_invalid_wheel_rejected_before_engine(builder, tmp_path, monkeypatch):
    module, commit = builder
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / "build-1-py3-none-any.whl").write_bytes(b"different")
    monkeypatch.setattr(module, "inspect", lambda *_a: pytest.fail("must not contact engine"))
    with pytest.raises(ValueError, match="integrity"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheelhouse, runtime_wheelhouse=tmp_path)


def test_changed_dependency_contract_is_rejected(builder, tmp_path, monkeypatch):
    module, commit = builder
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    with pytest.raises(ValueError, match="dependencies"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheelhouse, runtime_wheelhouse=tmp_path)


def test_base_identity_is_checked_before_build(builder, tmp_path, monkeypatch):
    module, commit = builder
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / "build-1-py3-none-any.whl").write_bytes(b"trusted")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(module, "inspect", lambda *_a: {"Id": "other"})
    with pytest.raises(ValueError, match="runtime base"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheelhouse, runtime_wheelhouse=runtime)


def test_tampered_adapter_runtime_wheel_rejected_before_engine(builder, tmp_path, monkeypatch):
    module, commit = builder
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / "build-1-py3-none-any.whl").write_bytes(b"trusted")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "runtime.whl").write_bytes(b"tampered")
    monkeypatch.setattr(module, "RUNTIME_WHEELS", {"runtime.whl": hashlib.sha256(b"trusted").hexdigest()})
    monkeypatch.setattr(module, "inspect", lambda *_a: pytest.fail("must not contact engine"))
    with pytest.raises(ValueError, match="runtime wheel integrity"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheelhouse, runtime_wheelhouse=runtime)


def test_staging_rejects_tampered_cache_and_never_overwrites(builder, tmp_path, monkeypatch):
    import sys

    module, _ = builder
    monkeypatch.setitem(sys.modules, "build_worker_offline", module)
    path = Path(__file__).resolve().parents[1] / "ops/deepseek/stage_offline_build_wheels.py"
    spec = importlib.util.spec_from_file_location("offline_worker_staging", path)
    staging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staging)
    monkeypatch.setattr(staging, "CACHE_KEYS", {"build-1-py3-none-any.whl": "abcdekey"})
    cache = tmp_path / "cache"
    source = cache.joinpath(*"abcde", "abcdekey.body")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"bad")
    destination = tmp_path / "new"
    with pytest.raises(ValueError, match="hash"):
        staging.stage(cache, destination)
    assert not (destination / "build-1-py3-none-any.whl").exists()
    source.write_bytes(b"trusted")
    with pytest.raises(ValueError, match="unsafe"):
        staging.stage(cache, destination)
    final = tmp_path / "other"
    staging.stage(cache, final)
    assert (final / "build-1-py3-none-any.whl").read_bytes() == b"trusted"
