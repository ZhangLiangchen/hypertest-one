"""Startup-only service admission; private readers are real, no provider or DB."""

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from hypertest.cloud import worker_admission as admission
from hypertest.cloud.errors import CloudBlocked
from hypertest.config import Settings


@pytest.fixture
def startup(tmp_path, monkeypatch):
    root = tmp_path / "release"
    root.mkdir()
    source, venv, runtime, payload = (root / name for name in ("source", "venv", "runtime", "delegates"))
    for path in (source, venv, runtime, payload):
        path.mkdir(mode=0o700 if path == runtime else 0o755)
    credentials_root = tmp_path / "credentials"
    credentials = credentials_root / "hypertest-cloud-worker.service"
    credentials.mkdir(parents=True)
    wrapping = base64.b64encode(b"w" * 32)  # Fixed test material, never a deployment secret.
    (credentials / "wrapping-key").write_bytes(wrapping)
    (credentials / "deepseek-key").write_bytes(b"fixture-deepseek-secret-never-emit")
    for path in credentials.iterdir():
        path.chmod(0o600)
    release = {"profile": "hypertest-cloud-worker-release/v1", "source_commit": "a" * 40,
        "source_archive_sha256": "b" * 64, "rootfs_image_sha256": "c" * 64,
        "venv_archive_sha256": "d" * 64, "sdk_version": "0.2.1rc2", "runtime_version": "0.2.1rc2"}
    manifest = root / "release.json"
    manifest.write_bytes(json.dumps(release, sort_keys=True).encode())
    expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
    settings = Settings(_env_file=None, cloud_enabled=True, cloud_worker_enabled=True,
        cloud_service_release_sha256=expected,
        cloud_runtime_root=str(runtime), cloud_credential_key_file=str(credentials / "wrapping-key"),
        cloud_model_key_file=str(credentials / "deepseek-key"), cloud_model_request_cost_microunits=1,
        cloud_codex_enabled=False, cloud_codex_payload=str(payload), cloud_codex_payload_sha256="e" * 64,
        cloud_codex_oauth_file=str(credentials / "codex-oauth"), cloud_codex_model="gpt-5.6-sol",
        cloud_attempt_timeout_seconds=900)
    for name, value in (("SOURCE_ROOT", source), ("VENV_ROOT", venv), ("RUNTIME_ROOT", runtime),
                        ("RELEASE_MANIFEST", manifest), ("CREDENTIALS_ROOT", credentials_root), ("PAYLOAD_ROOT", payload)):
        monkeypatch.setattr(admission, name, value)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setattr(admission, "sys", SimpleNamespace(prefix=str(venv), version_info=(3, 12, 0), platform="linux"))
    # Mount/ownership fixtures describe an immutable staged release; ordinary
    # 0600 credential reads still run through the actual descriptor reader.
    private_os = SimpleNamespace(**vars(os))
    original_stat, original_fstat = os.stat, os.fstat

    def release_owner(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if Path(path) in {source, venv, payload}:
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    def manifest_owner(descriptor):
        values = list(original_fstat(descriptor))
        values[4] = 0
        return os.stat_result(values)

    private_os.stat = release_owner
    private_os.fstat = manifest_owner
    private_os.statvfs = lambda path: SimpleNamespace(f_flag=0 if Path(path) == runtime else os.ST_RDONLY)
    private_os.fstatvfs = lambda _: SimpleNamespace(f_flag=os.ST_RDONLY)
    monkeypatch.setattr(admission, "os", private_os)
    monkeypatch.setattr(admission, "_outer_profile", lambda: {"nonroot": True,
        "resource_envelope": {"kind": "CGROUP_V2", "memory_max_bytes": 2 * 1024**3,
                              "swap_max_bytes": 0, "pids_max": 256}})
    metadata = SimpleNamespace(version=lambda _: "0.2.1rc2",
                               PackageNotFoundError=importlib.metadata.PackageNotFoundError)
    monkeypatch.setattr(admission, "importlib", SimpleNamespace(metadata=metadata))
    return SimpleNamespace(settings=settings, expected=expected, manifest=manifest,
        credentials=credentials, root=root, runtime=runtime, private_os=private_os, metadata=metadata)


def test_base_admission_reads_real_private_keys_without_codex_or_execution(startup, monkeypatch):
    monkeypatch.setattr(admission, "verify_payload", lambda *_: pytest.fail("Codex payload inspected"))
    monkeypatch.setattr(admission, "read_cloud_codex_identity", lambda *a, **k: pytest.fail("OAuth read"))
    observed = admission.inspect_admission(startup.settings, release_sha256=startup.expected)
    assert observed["status"] == "ADMITTED" and observed["scope"] == "SERVICE_STARTUP_ONLY"
    assert observed["credentials"] == {"wrapping_key_readable": True, "deepseek_key_readable": True}
    assert observed["codex"] == {"enabled": False}
    assert observed["release"]["manifest_sha256"] == startup.expected
    assert observed["release"]["archive_digest_verification"] == "OPERATOR_DEPLOYMENT_RECORD"
    assert all(observed[field] is False for field in
        ("database_contacted", "work_claimed", "sdk_started", "model_request_sent"))
    public = json.dumps(observed)
    assert "fixture-deepseek" not in public and "fixture-only-wrapping" not in public
    assert (startup.credentials / "wrapping-key").read_text() not in public
    assert "database_url" not in public and "key_length" not in public and "key_sha256" not in public


@pytest.mark.parametrize("mutation,expected", [
    ("disabled", "CLOUD_WORKER_DISABLED"),
    ("old_leaf", "WORKER_CREDENTIAL_PATH_MISMATCH"),
    ("old_unit", "WORKER_CREDENTIAL_PATH_MISMATCH"),
    ("group_read", "PRIVATE_FILE_UNSAFE"),
    ("runtime_mode", "WORKER_RUNTIME_ROOT_UNSAFE"),
    ("runtime_alias", "WORKER_RUNTIME_ROOT_UNSAFE"),
    ("zero_rate", "WORKER_MODEL_CONFIGURATION_INVALID"),
    ("multiline_key", "WORKER_MODEL_KEY_INVALID"),
])
def test_admission_refuses_configuration_and_file_boundaries(startup, monkeypatch, mutation, expected):
    if mutation == "disabled":
        startup.settings.cloud_worker_enabled = False
    elif mutation == "old_leaf":
        startup.settings.cloud_model_key_file = str(startup.credentials / "model-key")
    elif mutation == "old_unit":
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(startup.credentials.parent / "old.service"))
    elif mutation == "group_read":
        (startup.credentials / "deepseek-key").chmod(0o640)
    elif mutation == "runtime_mode":
        startup.runtime.chmod(0o755)
    elif mutation == "runtime_alias":
        alias = startup.root / "runtime-alias"
        alias.symlink_to(startup.runtime, target_is_directory=True)
        startup.settings.cloud_runtime_root = str(alias)
    elif mutation == "zero_rate":
        startup.settings.cloud_model_request_cost_microunits = 0
    elif mutation == "multiline_key":
        (startup.credentials / "deepseek-key").write_bytes(b"fixture\nprivate")
    with pytest.raises(CloudBlocked) as error:
        admission.inspect_admission(startup.settings, release_sha256=startup.expected)
    assert error.value.code == expected
    assert "fixture" not in str(error.value)


@pytest.mark.parametrize("mismatch", ["digest", "metadata_version", "python", "manifest_shape"])
def test_release_record_and_actual_sdk_environment_must_agree(startup, monkeypatch, mismatch):
    expected = startup.expected
    if mismatch == "digest":
        expected = "0" * 64
    elif mismatch == "metadata_version":
        startup.metadata.version = lambda _: "0.2.1rc1"
    elif mismatch == "python":
        monkeypatch.setattr(admission.sys, "prefix", "/usr/local")
    else:
        document = json.loads(startup.manifest.read_bytes())
        document["unexpected_secret_field"] = "fixture-must-not-emit"
        startup.manifest.write_bytes(json.dumps(document).encode())
        expected = hashlib.sha256(startup.manifest.read_bytes()).hexdigest()
        startup.settings.cloud_service_release_sha256 = expected
    with pytest.raises(CloudBlocked) as error:
        admission.inspect_admission(startup.settings, release_sha256=expected)
    assert error.value.code in {"WORKER_RELEASE_MISMATCH", "SDK_VERSION_MISMATCH",
                               "WORKER_PYTHON_MISMATCH", "WORKER_RELEASE_INVALID"}
    assert "fixture-must-not-emit" not in str(error.value)


def test_codex_opt_in_requires_payload_and_real_private_oauth_freshness(startup, monkeypatch):
    startup.settings.cloud_codex_enabled = True
    checked = []
    monkeypatch.setattr(admission, "verify_payload", lambda root, digest: checked.append((root, digest)))
    claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
    oauth = {"auth_mode": "chatgpt", "tokens": {"access_token": "fixture." + claims + ".signature",
                                                "account_id": "fixture-account"}}
    path = startup.credentials / "codex-oauth"
    path.write_bytes(json.dumps(oauth).encode())
    path.chmod(0o600)
    observed = admission.inspect_admission(startup.settings, release_sha256=startup.expected)
    assert checked == [(admission.PAYLOAD_ROOT, "e" * 64)]
    assert observed["credentials"]["codex_oauth_readable"] is True
    assert observed["codex"] == {"enabled": True, "model": "gpt-5.6-sol", "payload_manifest_sha256": "e" * 64}
    assert "fixture-account" not in json.dumps(observed) and oauth["tokens"]["access_token"] not in json.dumps(observed)
    monkeypatch.setattr(admission, "verify_payload", lambda *_: pytest.fail("payload rehashed before claim"))
    monkeypatch.setattr(admission, "_release", lambda *_: pytest.fail("release rechecked before claim"))
    assert admission.admit_credentials(startup.settings)["codex_oauth_readable"] is True
    assert len(checked) == 1
    claims = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 30}).encode()).decode().rstrip("=")
    oauth["tokens"]["access_token"] = "fixture." + claims + ".signature"
    path.write_bytes(json.dumps(oauth).encode())
    with pytest.raises(CloudBlocked) as error:
        admission.admit_credentials(startup.settings)
    assert error.value.code == "CODEX_OAUTH_EXPIRED"


def test_disabled_cli_does_not_inspect_release_or_keys(monkeypatch, capsys):
    monkeypatch.setattr(admission, "Settings", lambda: SimpleNamespace(cloud_enabled=False, cloud_worker_enabled=False))
    monkeypatch.setattr(admission, "_outer_profile", lambda: pytest.fail("admission entered while disabled"))
    assert admission.main(["--release-sha256", "a" * 64]) == 78
    result = json.loads(capsys.readouterr().out)
    assert result["code"] == "CLOUD_WORKER_DISABLED" and result["check_work_claimed"] is False


def test_cli_never_emits_native_exception_or_secret(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("fixture-secret-private-path")

    monkeypatch.setattr(admission, "inspect_admission", fail)
    assert admission.main(["--release-sha256", "a" * 64]) == 1
    output = capsys.readouterr().out
    assert "fixture-secret" not in output and json.loads(output)["code"] == "WORKER_ADMISSION_FAILED"


def test_import_does_not_load_database_or_sdk_runtime():
    code = ("import sys; import hypertest.cloud.worker_admission; "
            "assert 'hypertest.db.session' not in sys.modules; "
            "assert 'deepseek_harness' not in sys.modules; "
            "assert 'deepseek_harness_runtime' not in sys.modules")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=10, check=False)
    assert result.returncode == 0


def test_templates_are_opt_in_and_bind_the_same_credential_names():
    root = Path(__file__).resolve().parents[1] / "ops" / "deepseek"
    unit = (root / "hypertest-cloud-worker.service.in").read_text()
    dropin = (root / "hypertest-cloud-worker-codex.conf.in").read_text()
    environment = (root / "cloud-worker.env.example").read_text()
    assert "[Install]" not in [line.strip() for line in unit.splitlines()]
    assert "Restart=no" in unit and "Type=simple" in unit
    assert "User=hypertest-cloud" in unit and "Group=hypertest-cloud" in unit
    assert "MemoryMax=2G" in unit and "MemorySwapMax=0" in unit and "TasksMax=256" in unit
    assert "CapabilityBoundingSet=\n" in unit and "NoNewPrivileges=yes" in unit
    assert "hypertest.cloud.worker_admission" in unit and "ExecStart=/opt/hypertest-cloud/venv/bin/python -m hypertest.cloud\n" in unit
    assert unit.index("ExecStartPre=") < unit.index("ExecStart=")
    for leaf in ("wrapping-key", "deepseek-key"):
        assert "LoadCredential=" + leaf + ":" in unit and "%d/" + leaf in unit
    assert "HYPERTEST_CLOUD_CODEX_ENABLED=false" in unit and "codex-oauth" not in unit
    assert "HYPERTEST_CLOUD_CODEX_ENABLED=true" in dropin and "LoadCredential=codex-oauth:" in dropin
    assert "%d/codex-oauth" in dropin and "HYPERTEST_CLOUD_CODEX_MODEL=gpt-5.6-sol" in dropin
    assert "HYPERTEST_CLOUD_ENABLED=false" in environment and "HYPERTEST_CLOUD_WORKER_ENABLED=false" in environment
    assert "HYPERTEST_CLOUD_MODEL_REQUEST_COST_MICROUNITS=0" in environment


async def test_service_full_admission_failure_occurs_before_database_import(startup, monkeypatch, capsys):
    from hypertest.cloud import __main__ as cli

    startup.settings.cloud_service_release_sha256 = startup.expected
    startup.settings.cloud_model_key_file = str(startup.credentials / "obsolete-model-key")
    monkeypatch.setattr(cli, "get_settings", lambda: startup.settings)
    forbidden_db = ModuleType("hypertest.db.session")

    def database_access(name):
        pytest.fail("database imported before admission: " + name)

    forbidden_db.__getattr__ = database_access
    monkeypatch.setitem(sys.modules, "hypertest.db.session", forbidden_db)
    assert await cli.run(once=True) == 1
    observed = json.loads(capsys.readouterr().out)
    assert observed["code"] == "WORKER_CREDENTIAL_PATH_MISMATCH"
    assert observed["scope"] == "SERVICE_STARTUP_ONLY" and observed["check_work_claimed"] is False


@pytest.fixture
def worker_cli(startup, monkeypatch):
    from hypertest.cloud import __main__ as cli

    events = []

    class Engine:
        async def dispose(self):
            events.append("engine_disposed")

    class Worker:
        def __init__(self, sessions, settings, identity):
            events.append("worker_constructed")

        async def run_once(self):
            events.append("run_once")
            (startup.credentials / "deepseek-key").chmod(0o640)
            return False

    async def sleep(_):
        events.append("sleep")

    monkeypatch.setattr(cli, "get_settings", lambda: startup.settings)
    monkeypatch.setattr(cli, "asyncio", SimpleNamespace(**{
        **vars(asyncio), "sleep": sleep,
        "get_running_loop": lambda: SimpleNamespace(add_signal_handler=lambda *args: None)}))
    monkeypatch.setitem(sys.modules, "hypertest.db.session",
                        SimpleNamespace(AsyncSessionLocal=object(), engine=Engine()))
    monkeypatch.setitem(sys.modules, "hypertest.cloud.worker", SimpleNamespace(CloudWorker=Worker))
    return cli, events


async def test_service_rechecks_credentials_before_next_claim_and_stops_without_retry(startup, worker_cli, monkeypatch, capsys):
    cli, events = worker_cli
    startup.settings.cloud_service_release_sha256 = startup.expected
    original_full = admission.inspect_admission
    original_credentials = admission.admit_credentials

    def full(settings, **kwargs):
        events.append("full_admission")
        return original_full(settings, **kwargs)

    def credentials(settings):
        events.append("credentials")
        return original_credentials(settings)

    monkeypatch.setattr(admission, "inspect_admission", full)
    monkeypatch.setattr(admission, "admit_credentials", credentials)
    assert await cli.run(once=False) == 1
    assert events == ["full_admission", "credentials", "worker_constructed", "credentials",
                      "run_once", "sleep", "credentials", "engine_disposed"]
    observed = json.loads(capsys.readouterr().out)
    assert observed["scope"] == "BEFORE_NEXT_CLAIM" and observed["code"] == "PRIVATE_FILE_UNSAFE"
    assert observed["check_work_claimed"] is False and "fixture-deepseek" not in json.dumps(observed)


async def test_default_cli_does_not_enable_the_new_service_profile(startup, worker_cli, monkeypatch, capsys):
    cli, events = worker_cli
    startup.settings.cloud_service_release_sha256 = ""
    monkeypatch.setattr(admission, "inspect_admission", lambda *a, **k: pytest.fail("new profile enabled"))
    monkeypatch.setattr(admission, "admit_credentials", lambda *a, **k: pytest.fail("new profile enabled"))
    assert await cli.run(once=True) == 0
    assert events == ["worker_constructed", "run_once", "engine_disposed"]
    assert json.loads(capsys.readouterr().out) == {"work_claimed": False}
