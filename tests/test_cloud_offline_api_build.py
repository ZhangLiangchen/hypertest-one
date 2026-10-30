"""The offline API image must not build from mutable or unpushed inputs."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def builder(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "ops/container/build_api_offline.py"
    spec = importlib.util.spec_from_file_location("offline_api_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commit = "a" * 40
    monkeypatch.setattr(module, "run", lambda args, **kwargs: "dirty" if args[:2] == ["git", "status"] else commit)
    return module, commit


def test_uncommitted_checkout_rejected_before_engine(builder, tmp_path, monkeypatch):
    module, commit = builder
    monkeypatch.setattr(module, "inspect", lambda *_: pytest.fail("must not contact engine"))
    with pytest.raises(ValueError, match="clean"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=tmp_path,
                     worker_id="sha256:" + "b" * 64, worker_tag="hypertest-mac-cloud-worker:testing")


def test_changed_api_dependencies_rejected(builder, tmp_path, monkeypatch):
    module, commit = builder
    monkeypatch.setattr(module, "run", lambda args, **kwargs: "" if args[:2] == ["git", "status"] else commit)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match="dependencies"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=tmp_path,
                     worker_id="sha256:" + "b" * 64, worker_tag="hypertest-mac-cloud-worker:testing")


def _wheelhouse(tmp_path, content):
    builder = tmp_path / "ops/deepseek/build_worker_offline.py"
    builder.parent.mkdir(parents=True)
    builder.write_text(f"WHEELS = {{'build.whl': '{hashlib.sha256(b'trusted').hexdigest()}'}}\n")
    directory = tmp_path / "wheels"
    directory.mkdir()
    (directory / "build.whl").write_bytes(content)
    return directory


def test_tampered_build_wheel_rejected_before_engine(builder, tmp_path, monkeypatch):
    module, commit = builder
    monkeypatch.setattr(module, "run", lambda args, **kwargs: "" if args[:2] == ["git", "status"] else commit)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(module, "inspect", lambda *_: pytest.fail("must not contact engine"))
    wheels = _wheelhouse(tmp_path, b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheels,
                     worker_id="sha256:" + "b" * 64, worker_tag="hypertest-mac-cloud-worker:testing")


def test_worker_image_identity_mismatch_rejected(builder, tmp_path, monkeypatch):
    module, commit = builder
    monkeypatch.setattr(module, "run", lambda args, **kwargs: "" if args[:2] == ["git", "status"] else commit)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    wheels = _wheelhouse(tmp_path, b"trusted")
    def inspect(image, _checkout):
        if image == module.API_TAG:
            return {"Id": module.API_ID, "Config": {"Labels": {"org.opencontainers.image.revision": module.API_COMMIT}}}
        return {"Id": "sha256:" + "c" * 64, "Config": {"Labels": {"org.opencontainers.image.revision": commit}}}
    monkeypatch.setattr(module, "inspect", inspect)
    with pytest.raises(ValueError, match="identity"):
        module.build(checkout=tmp_path, commit=commit, remote_ref="origin/main", wheelhouse=wheels,
                     worker_id="sha256:" + "b" * 64, worker_tag="hypertest-mac-cloud-worker:testing")
