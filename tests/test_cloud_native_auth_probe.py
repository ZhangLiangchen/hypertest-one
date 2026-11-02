"""Only a fixed provider and the actual private profile credential are observed."""
from types import SimpleNamespace

from hypertest.cloud import native_auth_probe as probe


def test_private_key_is_used_only_for_fixed_official_get(tmp_path, monkeypatch):
    home = tmp_path / "dsh"
    home.mkdir()
    key_file = home / ".credentials.yaml"
    key_file.write_text("refs:\n  DEEPSEEK_API_KEY: synthetic-key\n")
    key_file.chmod(0o600)
    dump = b"""- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config: {provider: deepseek-official, model: fixture}
- id: llm-deepseek
  name: '@deepseek-ai/dsh-llm-deepseek-api-key'
- id: credentials
  name: '@deepseek-ai/dsh-credentials-local'
"""
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=dump))
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    calls = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.get_method(), request.get_header("X-api-key"), timeout))
            return Response()

    monkeypatch.setattr(probe.urllib.request, "build_opener", lambda *args: Opener())
    assert probe._check(str(home)) == "VALID"
    assert calls == [("https://api.deepseek.com/models", "GET", "synthetic-key", 5)]
    key_file.chmod(0o644)
    assert probe._check(str(home)) == "UNKNOWN"
    assert len(calls) == 1


def test_probe_never_reports_unrecognized_child_output(monkeypatch):
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"secret\n"))
    assert probe.probe_native_auth("/tmp/example") == "UNKNOWN"
