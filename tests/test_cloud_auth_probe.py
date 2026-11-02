"""Only fake provider responses; no model, account, or network requests."""
import io
import subprocess
import urllib.error
from types import SimpleNamespace

import pytest

from hypertest.cloud import auth_probe


@pytest.fixture
def key_file(tmp_path):
    path = tmp_path / "model-key"
    path.write_bytes(b"synthetic-test-key")
    path.chmod(0o600)
    return path


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@pytest.mark.parametrize(("http_status", "expected"), [(200, "VALID"), (401, "INVALID"),
    (403, "UNKNOWN"), (429, "UNKNOWN"), (500, "UNKNOWN"), (302, "UNKNOWN")])
def test_fixed_provider_and_closed_status_mapping(monkeypatch, key_file, http_status, expected):
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request, timeout))
            if http_status != 200:
                raise urllib.error.HTTPError(request.full_url, http_status, "sensitive response", {}, io.BytesIO(b"secret"))
            return FakeResponse()

    def build(*handlers):
        assert isinstance(handlers[0], auth_probe._NoRedirect)
        assert handlers[1].proxies == {}
        return Opener()

    monkeypatch.setattr(auth_probe.urllib.request, "build_opener", build)
    assert auth_probe._probe_once(str(key_file)) == expected
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == "https://api.deepseek.com/models"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer synthetic-test-key"
    assert timeout == 5


def test_network_failure_and_key_rotation_are_unknown(monkeypatch, key_file):
    class Opener:
        def open(self, request, *, timeout):
            raise TimeoutError("sensitive exception")

    monkeypatch.setattr(auth_probe.urllib.request, "build_opener", lambda *_: Opener())
    assert auth_probe._probe_once(str(key_file)) == "UNKNOWN"

    class RotatingOpener:
        def open(self, request, *, timeout):
            key_file.write_bytes(b"new-synthetic-key")
            return FakeResponse()

    monkeypatch.setattr(auth_probe.urllib.request, "build_opener", lambda *_: RotatingOpener())
    assert auth_probe._probe_once(str(key_file)) == "UNKNOWN"


def test_absent_invalid_or_unsafe_key_never_contacts_provider(monkeypatch, key_file, tmp_path):
    monkeypatch.setattr(auth_probe.urllib.request, "build_opener", lambda *_: pytest.fail("unexpected network"))
    assert auth_probe._probe_once(str(tmp_path / "missing")) == "INVALID"
    key_file.write_bytes(b"bad\nheader")
    assert auth_probe._probe_once(str(key_file)) == "INVALID"
    key_file.write_bytes(b"valid-format")
    key_file.chmod(0o644)
    assert auth_probe._probe_once(str(key_file)) == "UNKNOWN"
    key_file.chmod(0o600)
    link = tmp_path / "symlink"
    link.symlink_to(key_file)
    assert auth_probe._probe_once(str(link)) == "UNKNOWN"


def test_subprocess_has_hard_timeout_and_discards_nonstatus_output(monkeypatch, key_file):
    captured = []

    def run(args, **kwargs):
        captured.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"VALID\nsensitive output")

    monkeypatch.setattr(auth_probe.subprocess, "run", run)
    assert auth_probe.probe_deepseek_auth(key_file) == "UNKNOWN"
    args, kwargs = captured[0]
    assert str(key_file) not in args
    assert kwargs["input"] == str(key_file).encode()
    assert kwargs["timeout"] == 8
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "HYPERTEST_CLOUD_MODEL_KEY_FILE" not in kwargs["env"]

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 8, output=b"sensitive output")

    monkeypatch.setattr(auth_probe.subprocess, "run", timeout)
    assert auth_probe.probe_deepseek_auth(key_file) == "UNKNOWN"


def test_real_child_reads_missing_path_without_exposing_it(tmp_path, capsys):
    assert auth_probe.probe_deepseek_auth(tmp_path / "missing-private-name") == "INVALID"
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
