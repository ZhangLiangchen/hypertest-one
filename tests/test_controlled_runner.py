"""Controlled dependency identity and service lifecycle, without application DB writes."""

from __future__ import annotations

import asyncio
import io
import json
import os
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hypertest.config import get_settings
from hypertest.domain.environments import EnvironmentRequest
from hypertest.runner import backends, environments
from hypertest.runner.backends import DockerRunner, ProcessResult, runner_job_id
from hypertest.runner.service_launcher import BASE_URL, probe, validate_app, validate_metadata


def request(profile="python-api-v1"):
    return EnvironmentRequest(profile_id=profile, **(
        {"service": {"app": "app:app"}} if profile == "python-api-v1" else {}
    ))


def image(profile="python-api-v1", digest="a"):
    manifest = environments.profile_manifest(profile)
    return {"Id": "sha256:" + digest * 64, "Os": "linux", "Architecture": "arm64", "Config": {
        "Labels": {**{environments.LABEL_PREFIX + key: manifest[key] for key in (
            "profile_id", "dependency_lock_sha256", "launcher_sha256",
        )}, environments.LABEL_PREFIX + "base_image_digest": "python@sha256:" + "b" * 64},
    }}


def binding(profile="python-api-v1"):
    details = image(profile)
    manifest = environments.profile_manifest(profile)
    return {"schema_version": environments.SCHEMA_VERSION,
            "request": request(profile).model_dump(mode="json", exclude_none=True),
            "image_id": details["Id"], "image_os": details["Os"],
            "image_architecture": details["Architecture"],
            **{key: value for key, value in manifest.items() if key != "profile_id"}}


def proof():
    timestamp = datetime.now(UTC).isoformat()
    return {"schema_version": "hypertest.service-execution/v1", "app": "app:app",
            "base_url": BASE_URL, "startup_timeout_seconds": 30,
            "health": {"method": "GET", "path": "/health", "status": 200, "body_sha256": "a" * 64},
            "service_started_at": timestamp, "ready_at": timestamp, "finished_at": timestamp,
            "service_early_exit": False, "service_exit_code": -15, "pytest_exit_code": 0,
            "cleanup_complete": True, "log_truncated": False, "error_code": None}


@pytest.mark.parametrize("payload", [
    {"profile_id": "unknown"}, {"profile_id": "python-api-v1"},
    {"profile_id": "python-pytest-v1", "service": {"app": "app:app"}},
    {"profile_id": "python-pytest-v1", "command": "pip install anything"},
    *[{"profile_id": "python-api-v1", "service": {"app": value}} for value in (
        "app:factory()", "app:app;whoami", "äpp:app", "../app:app", "a" * 257 + ":app",
    )],
    *[{"profile_id": "python-api-v1", "service": {"app": "app:app", "health_path": value}}
      for value in ("http://example.com", "//host/path", "/a/../b", "/x?q=1", "/x#f", "/%2e", "/a//b")],
    *[{"profile_id": "python-api-v1", "service": {"app": "app:app", "startup_timeout_seconds": value}}
      for value in (0, 121, True, "30")],
])
def test_requests_do_not_accept_commands_network_overrides_or_ambiguous_values(payload):
    with pytest.raises(ValidationError):
        EnvironmentRequest.model_validate(payload)


def test_normalized_request_and_transitive_pinned_dependencies():
    assert request().service.health_path == "/health"
    assert request().service.startup_timeout_seconds == 30
    assert request("python-pytest-v1").service is None
    manifest = environments.profile_manifest("python-api-v1")
    assert {"pytest", "fastapi", "uvicorn", "httpx", "pydantic-core"} <= set(manifest["dependencies"])
    for profile in environments.PROFILE_IDS:
        content = (Path(environments.__file__).parent / "locks" / f"{profile}.txt").read_text()
        assert all("==" in line and "--hash=sha256:" in line for line in content.splitlines() if not line.startswith("#"))


@pytest.mark.asyncio
async def test_resolution_pins_actual_image_and_execution_uses_id_not_mutable_tag(monkeypatch):
    calls = []

    async def inspect(command, **_options):
        calls.append(command)
        return ProcessResult(json.dumps(image()).encode(), b"", 0)

    monkeypatch.setattr(environments, "run_process", inspect)
    resolved = await environments.resolve_environment(request())
    assert resolved == binding()
    assert calls[-1][3] == get_settings().runner_api_image
    identity = await DockerRunner(resolved).fingerprint()
    assert calls[-1][3] == resolved["image_id"]
    assert identity["environment_definition"] == resolved
    assert identity["network"] == "none" and identity["read_only"]
    assert identity["base_image_digest"].startswith("python@sha256:")
    assert all(command[:3] == ["docker", "image", "inspect"] for command in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "lock", "launcher", "profile", "base", "image_id"])
async def test_missing_or_changed_trusted_images_fail_closed(monkeypatch, change):
    details = image()
    if change in {"lock", "launcher", "profile", "base"}:
        key = {"lock": "dependency_lock_sha256", "launcher": "launcher_sha256",
               "profile": "profile_id", "base": "base_image_digest"}[change]
        details["Config"]["Labels"][environments.LABEL_PREFIX + key] = "changed"
    if change == "image_id":
        details["Id"] = "sha256:" + "c" * 64

    async def inspect(*_args, **_options):
        return ProcessResult(json.dumps(details).encode(), b"", 1 if change == "missing" else 0)

    monkeypatch.setattr(environments, "run_process", inspect)
    with pytest.raises((ValueError, RuntimeError)):
        await environments.validate_environment_binding(binding())


def test_pure_binding_validation_does_not_perform_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("pure validation must not inspect Docker")

    monkeypatch.setattr(environments, "run_process", forbidden)
    assert environments.validate_binding_content(binding()) == request()
    for key, value in (("dependencies", {}), ("launcher_sha256", "c" * 64), ("image_id", "tag:mutable")):
        changed = binding()
        changed[key] = value
        with pytest.raises(ValueError):
            environments.validate_binding_content(changed)


def test_service_app_is_real_tracked_application_source_not_overlay(tmp_path):
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/api.py").write_text("app = object()")
    validate_app(tmp_path, "pkg.api:app")
    environments.validate_service_app(tmp_path, "pkg.api:app", ["src/pkg/api.py"])
    with pytest.raises(ValueError, match="tracked"):
        environments.validate_service_app(tmp_path, "pkg.api:app", [])
    for value in ("missing:app", "tests.test_example:app", "pkg.api:factory()"):
        with pytest.raises(ValueError):
            validate_app(tmp_path, value)
    (tmp_path / "app.py").symlink_to(tmp_path / "src/pkg/api.py")
    with pytest.raises(ValueError):
        validate_app(tmp_path, "app:app")


@pytest.mark.parametrize("key,value", [
    ("health", None), ("service_early_exit", True), ("cleanup_complete", False),
    ("pytest_exit_code", 1), ("base_url", "http://example.com"), ("error_code", "raw private error"),
    ("service_exit_code", None),
])
def test_missing_inconsistent_or_unsafe_service_proof_cannot_pass(key, value):
    metadata = proof()
    metadata[key] = value
    with pytest.raises(ValueError):
        validate_metadata(metadata, request().service.model_dump(), 0)


def test_proof_has_fixed_fields_and_typed_failure_is_valid():
    metadata = proof()
    validate_metadata(metadata, request().service.model_dump(), 0)
    metadata["error_code"] = "SERVICE_EXITED"
    metadata["service_early_exit"] = True
    validate_metadata(metadata, request().service.model_dump(), 3)
    metadata["raw_environment"] = "private"
    with pytest.raises(ValueError):
        validate_metadata(metadata, request().service.model_dump(), 0)


def test_readiness_probe_disables_proxy_redirects_and_bounds_body(monkeypatch):
    from hypertest.runner import service_launcher

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, count):
            assert count == 4097
            return b"healthy"

    class Opener:
        def open(self, url, timeout):
            assert url == BASE_URL + "/health" and timeout == 0.25
            return Response()

    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], service_launcher.NoRedirect)
        assert handlers[1].redirect_request(None, None, 302, None, None, "https://example.com") is None
        return Opener()

    monkeypatch.setattr(service_launcher.urllib.request, "build_opener", opener)
    assert probe("/health", 0.25)["status"] == 200
    monkeypatch.setattr(Response, "read", lambda self, count: b"x" * 4097)
    assert probe("/health", 0.25) is None
    monkeypatch.setattr(Response, "status", 201)
    assert probe("/health", 0.25) is None


def archive(name, content, *, symlink=False):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as bundle:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        if symlink:
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
        bundle.addfile(info, None if symlink else io.BytesIO(content))
    return data.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "missing", "malformed", "early_exit", "oom", "symlink"])
async def test_docker_service_uses_bound_image_isolation_and_bounded_fixed_evidence(tmp_path, monkeypatch, fault):
    source, output = tmp_path / "repo", tmp_path / "results"
    source.mkdir()
    output.mkdir()
    (source / "app.py").write_text("app = object()")
    commands = []
    metadata = proof()
    if fault == "early_exit":
        metadata.update(error_code="SERVICE_EXITED", service_early_exit=True)

    async def inspect(*args, **kwargs):
        return ProcessResult(json.dumps(image()).encode(), b"", 0)

    async def docker(command, **options):
        commands.append(command)
        if command[1] == "inspect":
            return ProcessResult(json.dumps({"ExitCode": 0, "OOMKilled": fault == "oom"}).encode(), b"", 0)
        if command[1] == "cp" and command[-1] == "-":
            filename = command[2].split("/")[-1]
            if filename == "service-metadata.json":
                if fault == "missing":
                    return ProcessResult(b"", b"", 1)
                content = b"invalid JSON" if fault == "malformed" else json.dumps(metadata).encode()
            else:
                content = b"<testsuites/>" if filename == "junit.xml" else b"bounded service log"
            return ProcessResult(archive(filename, content, symlink=fault == "symlink" and filename == "service.log"), b"", 0)
        return ProcessResult(b"pytest output", b"", 0)

    monkeypatch.setattr(environments, "run_process", inspect)
    monkeypatch.setattr(backends, "run_process", docker)
    runner = DockerRunner(binding())
    token = runner_job_id.set("00000000-0000-4000-8000-000000000001")
    try:
        result = await runner.execute(source, output, ["tests/test_api.py::test_health"], 10, await runner.fingerprint())
    finally:
        runner_job_id.reset(token)
    assert bool(result.error_code) == bool(fault)
    if fault is None:
        assert result.service_metadata == metadata
        assert result.service_log == b"bounded service log"
    execution = next(command for command in commands if "/opt/hypertest/service_launcher.py" in command)
    assert execution[execution.index("--network") + 1] == "none"
    assert "--pull=never" in execution
    assert "--read-only" in execution and "--cap-drop" in execution and "--pids-limit" in execution
    assert execution[execution.index("--user") + 1] == "65534:65534"
    assert not {"--publish", "-p", "--privileged", "--env-file"} & set(execution)
    assert binding()["image_id"] in execution
    assert all("org.hypertest.job_id=00000000-0000-4000-8000-000000000001" in c for c in commands if c[1:3] == ["volume", "create"])
    assert commands[-2][1:4] == ["rm", "-f", "-v"] and commands[-1][1:3] == ["volume", "rm"]
    assert {c[2].split("/")[-1] for c in commands if c[1] == "cp" and c[-1] == "-"} <= {
        "junit.xml", "service.log", "service-metadata.json",
    }


@pytest.mark.asyncio
async def test_environment_catalog_reports_api_host_inspection_only(monkeypatch):
    async def inspect(command, **_kwargs):
        return ProcessResult(b"", b"", 1)

    monkeypatch.setattr(environments, "run_process", inspect)
    catalog = await environments.environment_catalog()
    assert len(catalog) == 2
    assert all(not item["available"] and item["reason_code"] == "CONTROLLED_IMAGE_UNAVAILABLE" for item in catalog)
    assert all("checked_at" in item and item["network"] == "none" for item in catalog)


@pytest.mark.asyncio
async def test_cancellation_during_service_container_run_cleans_owned_resources(tmp_path, monkeypatch):
    source, output = tmp_path / "repo", tmp_path / "results"
    source.mkdir()
    output.mkdir()
    (source / "app.py").write_text("app=object()")
    started = asyncio.Event()
    commands = []

    async def inspect(*args, **kwargs):
        return ProcessResult(json.dumps(image()).encode(), b"", 0)

    async def docker(command, **options):
        commands.append(command)
        if command[1] == "start":
            started.set()
            await asyncio.Future()
        return ProcessResult(b"", b"", 0)

    monkeypatch.setattr(environments, "run_process", inspect)
    monkeypatch.setattr(backends, "run_process", docker)
    runner = DockerRunner(binding())
    task = asyncio.create_task(runner.execute(source, output, ["tests/a.py::test_a"], 20, await runner.fingerprint()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert commands[-2][1:4] == ["rm", "-f", "-v"]
    assert commands[-1][1:3] == ["volume", "rm"]


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("HYPERTEST_TEST_CONTROLLED_DOCKER") != "1", reason="explicit isolated Docker smoke")
async def test_real_api_service_runner_preserves_isolation_and_reliably_cleans(tmp_path):
    source, output = tmp_path / "repo", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "tests").mkdir()
    # Source files cannot replace the trusted image launcher or tool entry points.
    for name in ("asyncio", "json", "pytest", "uvicorn"):
        (source / (name + ".py")).write_text("raise RuntimeError('untrusted tool shadow')\n")
    (source / "app.py").write_text('from fastapi import FastAPI\napp=FastAPI()\n@app.get("/health")\ndef health(): return {"ok": True}\n')
    (source / "tests/test_api.py").write_text('import os,httpx,socket\ndef test_health():\n    assert httpx.get(os.environ["HYPERTEST_BASE_URL"]+"/health",trust_env=False).json()=={"ok":True}\n    assert os.getuid()==65534\n    assert not os.access("/repo/app.py",os.W_OK)\n    assert open("/proc/net/route").read().count("\\n")==1\n')
    resolved = await environments.resolve_environment(request())
    runner = DockerRunner(resolved)
    result = await runner.execute(source, output, ["tests/test_api.py::test_health"], 30, await runner.fingerprint())
    assert result.exit_code == 0, result.stderr.decode()
    assert result.error_code is None and not result.timed_out
    assert result.service_metadata["health"]["status"] == 200
    assert result.service_metadata["cleanup_complete"]
    assert b"1 passed" in result.stdout and (output / "junit.xml").exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("HYPERTEST_TEST_CONTROLLED_DOCKER") != "1", reason="explicit isolated Docker smoke")
@pytest.mark.parametrize("scenario,error_code,exit_code", [
    ("assertion", None, 1),
    ("startup", "SERVICE_START_FAILED", 3),
    ("unready", "SERVICE_NOT_READY", 3),
    ("redirect", "SERVICE_NOT_READY", 3),
    ("early_exit", "SERVICE_EXITED", 3),
    ("timeout", "SERVICE_EVIDENCE_MISSING", None),
])
async def test_real_service_failure_timeout_and_cleanup_are_not_passing_facts(tmp_path, scenario, error_code, exit_code):
    source, output = tmp_path / "repo", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "tests").mkdir()
    (source / "pytest.py").write_text("raise RuntimeError('untrusted pytest shadow')\n")
    app = 'from fastapi import FastAPI\napp=FastAPI()\n@app.get("/health")\ndef health(): return {"ok":True}\n'
    body = "def test_health():\n    assert True\n"
    if scenario == "assertion":
        body = "def test_health():\n    assert False, 'SUT assertion failure'\n"
    elif scenario == "startup":
        app = "raise RuntimeError('fixture cannot start')\n"
    elif scenario == "unready":
        app = "from fastapi import FastAPI\napp=FastAPI()\n"
    elif scenario == "redirect":
        app = 'from fastapi import FastAPI\nfrom fastapi.responses import RedirectResponse\napp=FastAPI()\n@app.get("/health")\ndef health(): return RedirectResponse("https://example.invalid/health")\n'
    elif scenario == "early_exit":
        app = 'from fastapi import FastAPI\nimport os,threading\napp=FastAPI()\n@app.get("/health")\ndef health():\n    threading.Timer(0.5,lambda:os._exit(17)).start()\n    return {"ok":True}\n'
        body = "import time\ndef test_health():\n    time.sleep(5)\n    assert True\n"
    elif scenario == "timeout":
        body = "import time\ndef test_health():\n    time.sleep(10)\n"
    (source / "app.py").write_text(app)
    (source / "tests/test_api.py").write_text(body)
    environment_request = EnvironmentRequest(profile_id="python-api-v1", service={
        "app": "app:app", "startup_timeout_seconds": 1,
    })
    resolved = await environments.resolve_environment(environment_request)
    runner = DockerRunner(resolved)
    job_id = uuid4()
    token = runner_job_id.set(str(job_id))
    try:
        result = await runner.execute(source, output, ["tests/test_api.py::test_health"],
                                      1 if scenario == "timeout" else 10, await runner.fingerprint())
    finally:
        runner_job_id.reset(token)
    assert result.error_code == error_code, (result, scenario)
    if exit_code is not None:
        assert result.exit_code == exit_code
    assert result.timed_out == (scenario == "timeout")
    assert result.timed_out or result.error_code or result.exit_code != 0
    for command in (["docker", "ps", "-aq", "--filter", f"label={backends.JOB_LABEL}={job_id}"],
                    ["docker", "volume", "ls", "-q", "--filter", f"label={backends.JOB_LABEL}={job_id}"]):
        remaining = await backends.run_process(command, cwd=tmp_path, timeout=10)
        assert remaining.exit_code == 0 and remaining.stdout.strip() == b""


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("HYPERTEST_TEST_CONTROLLED_DOCKER") != "1", reason="explicit isolated Docker smoke")
async def test_real_controlled_pytest_profile_uses_approved_dependencies_without_service(tmp_path):
    source, output = tmp_path / "repo", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    (source / "tests").mkdir()
    (source / "pytest.py").write_text("raise RuntimeError('untrusted pytest shadow')\n")
    (source / "tests/test_plain.py").write_text('import pytest\ndef test_plain():\n    assert pytest.__version__=="8.3.5"\n')
    runner = DockerRunner(await environments.resolve_environment(request("python-pytest-v1")))
    result = await runner.execute(source, output, ["tests/test_plain.py::test_plain"], 10, await runner.fingerprint())
    assert result.exit_code == 0 and result.error_code is None
    assert result.service_metadata is None and result.service_log is None
    assert (output / "junit.xml").is_file()
