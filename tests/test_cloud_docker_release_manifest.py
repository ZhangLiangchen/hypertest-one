"""Release manifests bind a clean pushed commit and exact immutable image."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def tool(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "ops/deepseek/prepare_docker_manifest.py"
    spec = importlib.util.spec_from_file_location("cloud_docker_manifest", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commit, image = "a" * 40, "sha256:" + "b" * 64
    def output(args, _cwd):
        if args[:2] == ["git", "rev-parse"]:
            return commit
        if args[:2] == ["git", "status"]:
            return ""
        if args[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"Id": image, "Config": {"Labels": {"org.opencontainers.image.revision": commit}}}])
        return "0.2.1rc2\n0.2.1rc2"
    monkeypatch.setattr(module, "output", output)
    monkeypatch.setattr(module, "hash_command", lambda args, cwd: "c" * 64)
    return module, commit, image


def test_manifest_is_bound_and_never_overwrites(tool, tmp_path):
    module, commit, image = tool
    destination = tmp_path / "release.json"
    result = module.prepare(checkout=tmp_path, commit=commit, remote_ref="origin/main", image_id=image, destination=destination)
    content = json.loads(destination.read_text())
    assert content["source_commit"] == commit and content["rootfs_image_sha256"] == image[7:]
    assert result["work_claimed"] is False and result["model_started"] is False
    with pytest.raises(ValueError):
        module.prepare(checkout=tmp_path, commit=commit, remote_ref="origin/main", image_id=image, destination=destination)


def test_manifest_refuses_wrong_image_and_missing_revision(tool, tmp_path, monkeypatch):
    module, commit, image = tool
    with pytest.raises(ValueError):
        module.prepare(checkout=tmp_path, commit=commit, remote_ref="origin/main", image_id="tag", destination=tmp_path / "x")
    old = module.output
    monkeypatch.setattr(module, "output", lambda args, cwd: "dirty" if args[:2] == ["git", "status"] else old(args, cwd))
    with pytest.raises(ValueError):
        module.prepare(checkout=tmp_path, commit=commit, remote_ref="origin/main", image_id=image, destination=tmp_path / "x")
    assert not (tmp_path / "x").exists()
