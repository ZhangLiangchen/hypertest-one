"""BuildKit archive input remains bounded, pinned, and optional."""
import base64
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def installer():
    source = Path(__file__).resolve().parents[1] / "ops/deepseek/install_sdk_landlock.py"
    spec = importlib.util.spec_from_file_location("offline_landlock_installer", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_archive(machine=183):
    binary = bytearray(32)
    binary[:6] = b"\x7fELF\x02\x01"
    binary[18:20] = machine.to_bytes(2, "little")
    entries = (("package/package.json", json.dumps({"name": "@deepseek-ai/node-addon-system-linux-arm64", "version": "0.1.2"}).encode(), 0o644),
               ("package/bin/landlock-run", bytes(binary), 0o755), ("package/LICENSE", b"license", 0o644))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content, mode in entries:
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), mode
            archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def test_optional_archive_is_checked_without_network(installer, tmp_path, monkeypatch):
    path = tmp_path / "archive"
    raw = sample_archive()
    path.write_bytes(raw)
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("unexpected network"))
    loaded = installer.read_archive("https://example.invalid", offline_archive=path)
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    binary, license_text = installer.validate_package(loaded, "arm64", integrity, 183)
    assert binary[:4] == b"\x7fELF" and license_text == b"license"
    with pytest.raises(ValueError, match="integrity"):
        installer.validate_package(loaded, "arm64", "sha512-invalid", 183)
    with pytest.raises(ValueError, match="architecture"):
        installer.validate_package(loaded, "arm64", integrity, 62)


def test_missing_archive_uses_official_fetch(installer, tmp_path, monkeypatch):
    response = io.BytesIO(b"official")
    calls = []
    def fetch(url, *, timeout):
        calls.append((url, timeout))
        return response
    monkeypatch.setattr(installer, "urlopen", fetch)
    assert installer.read_archive("https://registry.npmjs.org/package", offline_archive=tmp_path / "missing") == b"official"
    assert calls == [("https://registry.npmjs.org/package", 60)]


def test_present_unsafe_archive_never_falls_back(installer, tmp_path, monkeypatch):
    path = tmp_path / "archive"
    target = tmp_path / "target"
    target.write_bytes(b"data")
    path.symlink_to(target)
    monkeypatch.setattr(installer, "urlopen", lambda *_a, **_k: pytest.fail("unexpected network"))
    with pytest.raises(OSError):
        installer.read_archive("https://example.invalid", offline_archive=path)
    path.unlink()
    path.write_bytes(b"")
    with pytest.raises(ValueError):
        installer.read_archive("https://example.invalid", offline_archive=path)
