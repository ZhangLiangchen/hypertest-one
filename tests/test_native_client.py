"""The Operator client persists intent before POST and never replays uncertainty."""
import json
import stat
from pathlib import Path

import httpx
import pytest

from hypertest.interactive_client.errors import ClientError
from hypertest.native_client import NativeClient


def client_at(tmp_path, handler, *, writer_file=True):
    root = tmp_path / "private"
    root.mkdir(mode=0o700, exist_ok=True)
    operator = root / "operator.key"
    operator.write_text("operator-secret-value")
    operator.chmod(0o600)
    return NativeClient("http://127.0.0.1:8097/api/v1", operator, root / "journal.db",
                        root / "writer.key" if writer_file else None,
                        transport=httpx.MockTransport(handler))


def test_response_loss_restart_not_found_only_reads_original_key(tmp_path):
    requests = []
    def handler(request):
        requests.append(request.method)
        if request.method == "POST":
            raise httpx.ReadError("simulated ACK loss")
        return httpx.Response(404, json={"detail": "not currently found"})
    client = client_at(tmp_path, handler)
    with pytest.raises(ClientError, match="NATIVE_RESPONSE_UNKNOWN"):
        client.submit("/native-runs/r/executions", {"idempotency_key": "original-key"},
                      "/native-runs/r/operations/original-key")
    client.close()
    restarted = client_at(tmp_path, handler)
    result = restarted.submit("/native-runs/r/executions", {"idempotency_key": "original-key"},
                              "/native-runs/r/operations/original-key")
    assert requests == ["POST", "GET"]
    assert result["original_result"]["status"] == "UNKNOWN"
    with pytest.raises(ClientError, match="IDEMPOTENCY_CONFLICT"):
        restarted.submit("/native-runs/r/executions", {"idempotency_key": "original-key", "different": True}, "/same-query")
    restarted.close()


def test_one_time_writer_secret_is_private_and_never_in_journal_or_stdout(tmp_path, capsys):
    def handler(_):
        return httpx.Response(201, json={"status": "ACCEPTED", "writer_token": "new-private-capability", "run_id": "r"})
    client = client_at(tmp_path, handler)
    result = client.submit("/native-runs", {"idempotency_key": "create-key"},
                           "/native-runs/submissions/p/create-key", issues_writer=True)
    assert "writer_token" not in result
    secret = Path(result["writer_key_file"])
    assert secret.read_text() == "new-private-capability"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    saved = client.journal.get("native", "/native-runs:create-key")
    assert "new-private-capability" not in json.dumps(saved)
    assert "operator-secret-value" not in json.dumps(saved)
    assert capsys.readouterr().out == ""
    client.close()


def test_plain_remote_http_and_credentials_in_api_origin_are_refused(tmp_path):
    for url in ["http://remote.example/api/v1", "https://user:password@example.invalid/api/v1"]:
        with pytest.raises(ClientError, match="NATIVE_API_REQUIRES"):
            NativeClient(url, tmp_path / "never-read", tmp_path / "journal")


def test_large_material_bytes_are_not_duplicated_in_recovery_journal(tmp_path):
    def handler(_):
        return httpx.Response(201, json={"status": "MATERIAL_RECEIVED"})
    client = client_at(tmp_path, handler)
    payload = {"idempotency_key": "large-material", "materials": [{"content_base64": "A" * 4_000_000}]}
    client.submit("/native-runs/r/executions", payload, "/native-runs/r/operations/large-material")
    client.close()
    assert (tmp_path / "private/journal.db").stat().st_size < 32_000
    reopened = client_at(tmp_path, handler)
    assert reopened.journal.get("native", "/native-runs/r/executions:large-material")["state"] == "SUCCEEDED"
    reopened.close()
