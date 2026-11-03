import hashlib
import sys
from types import SimpleNamespace

import pytest
import yaml

from hypertest.cloud import native_cordis
from hypertest.cloud.errors import CloudBlocked


def test_overlay_uses_pinned_official_preset_and_empty_environment(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"pinned runtime")
    monkeypatch.setattr(native_cordis, "_RUNTIME_SHA256", hashlib.sha256(runtime.read_bytes()).hexdigest())
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    observed = {}

    def dump(command, **kwargs):
        observed.update(command=command, **kwargs)
        return SimpleNamespace(stdout=b"- id: preset-cordis\n  name: '@deepseek-ai/dsh-agent-preset'\n  config:\n    id: cordis\n    expression: !!js 'process.platform === \"win32\"'\n")

    monkeypatch.setattr(native_cordis.subprocess, "run", dump)
    monkeypatch.setenv("CLOUD_TEST_SECRET", "not-for-child")
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    result = native_cordis.prepare_cordis_overlay(private, title="任务标题")
    data = yaml.load(result.read_bytes(), Loader=native_cordis._Loader)
    inserted = data[-1]["insert"]
    preset = next(item for item in inserted if item["id"] == "preset-cordis")
    assert isinstance(preset["config"]["expression"], native_cordis._Expression)
    assert next(item for item in inserted if item["id"] == "hypertest-cordis-root")["name"] == str(private / "hypertest-cordis-root.mjs")
    assert next(item for item in inserted if item["id"] == "hypertest-cordis-root")["config"] == {"title": "任务标题"}
    assert "CLOUD_TEST_SECRET" not in observed["env"]
    assert "--dump-default-config" in observed["command"]
    assert observed["env"]["HOME"] == observed["env"]["DSH_HOME"]
    assert result.stat().st_mode & 0o777 == 0o600
    assert (private / "hypertest-cordis-root.mjs").stat().st_mode & 0o777 == 0o600


def test_overlay_rejects_runtime_drift_before_running_it(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"unapproved version")
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    monkeypatch.setattr(native_cordis.subprocess, "run", lambda *args, **kwargs: pytest.fail("unapproved runtime launched"))
    with pytest.raises(CloudBlocked) as error:
        native_cordis.prepare_cordis_overlay(tmp_path, title="任务标题")
    assert error.value.code == "HARNESS_CORDIS_UNAVAILABLE"
    assert not (tmp_path / "hypertest-cordis-overlay.yml").exists()


def test_overlay_rejects_missing_official_preset(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.write_bytes(b"pinned")
    monkeypatch.setattr(native_cordis, "_RUNTIME_SHA256", hashlib.sha256(runtime.read_bytes()).hexdigest())
    monkeypatch.setitem(sys.modules, "deepseek_harness_runtime", SimpleNamespace(resolve_bundled_launch_args=lambda: (str(runtime),)))
    monkeypatch.setattr(native_cordis.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=b"[]"))
    with pytest.raises(CloudBlocked) as error:
        native_cordis.prepare_cordis_overlay(tmp_path, title="任务标题")
    assert error.value.code == "HARNESS_CORDIS_UNAVAILABLE"
