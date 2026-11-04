"""Framework sessions reuse a real project without mixing task handoffs."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.cloud import native_framework_project as projects
from hypertest.cloud.errors import CloudBlocked


def git(path, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-c", "user.name=Framework fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=path, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"},
        stderr=subprocess.DEVNULL, text=True,
    ).strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "_PREPARE_LOCKS", {})
    root = tmp_path.resolve()
    snapshot = root / "snapshot"
    snapshot.mkdir()
    git(snapshot, "init")
    (snapshot / "framework.txt").write_text("accepted framework source\n")
    git(snapshot, "add", "framework.txt")
    git(snapshot, "commit", "-m", "fixture")
    state = root / "worker" / "state"
    state.mkdir(parents=True)
    return SimpleNamespace(root=root, snapshot=snapshot, state=state,
        resolved={"url": "https://gitlab.charprotocol.com/zhangliangchen/hypervise_pure.git",
                  "commit_sha": git(snapshot, "rev-parse", "HEAD")})


async def prepare(source, attempt, *, url=None):
    attempt_root = source.state / attempt
    attempt_root.mkdir()
    resolved = {**source.resolved, **({"url": url} if url is not None else {})}
    return await projects.prepare_framework_project(state=source.state, attempt_root=attempt_root,
        snapshot=source.snapshot, resolved=resolved)


@pytest.mark.asyncio
async def test_same_framework_reuses_project_and_preserves_agent_files_and_head(source):
    project = await prepare(source, "attempt-one")
    git(project, "checkout", "-b", "agent-work")
    (project / "agent-test.txt").write_text("Agent-created tests\n")
    git(project, "add", "agent-test.txt")
    git(project, "commit", "-m", "Agent contribution")
    head = git(project, "rev-parse", "HEAD")
    (project / "uncommitted-report.txt").write_text("retain these observations\n")
    assert head != source.resolved["commit_sha"]

    reused = await prepare(source, "attempt-two",
                           url="git@gitlab.charprotocol.com:zhangliangchen/hypervise_pure")
    assert reused == project
    assert git(project, "rev-parse", "HEAD") == head
    assert git(project, "branch", "--show-current") == "agent-work"
    assert (project / "agent-test.txt").read_text() == "Agent-created tests\n"
    assert (project / "uncommitted-report.txt").read_text() == "retain these observations\n"
    first = json.loads((source.state / "attempt-one" / projects.RECORD).read_bytes())
    second = json.loads((source.state / "attempt-two" / projects.RECORD).read_bytes())
    assert first == second
    assert first["title"] == "hypervise"
    assert first["path"] == str(project)


@pytest.mark.asyncio
async def test_different_repository_namespaces_never_share_a_project(source):
    first = await prepare(source, "attempt-one")
    second = await prepare(source, "attempt-two",
        url="https://gitlab.charprotocol.com/another-owner/hypervise_pure.git")
    assert first != second
    assert first.name == second.name == "hypervise_pure"
    assert projects.repository_identity(source.resolved["url"])[0] != projects.repository_identity(
        "https://gitlab.charprotocol.com/another-owner/hypervise_pure.git")[0]


@pytest.mark.asyncio
async def test_changed_repository_origin_is_rejected_without_rebinding(source):
    project = await prepare(source, "attempt-one")
    git(project, "remote", "set-url", "origin", "https://example.invalid/unrelated/hypervise_pure")
    with pytest.raises(CloudBlocked) as error:
        await prepare(source, "attempt-two")
    assert error.value.code == "FRAMEWORK_PROJECT_INVALID"
    assert not (source.state / "attempt-two" / projects.RECORD).exists()
    assert git(project, "remote", "get-url", "origin") == "https://example.invalid/unrelated/hypervise_pure"


def test_legacy_session_without_project_record_keeps_original_working_directory(tmp_path):
    workspace = tmp_path.resolve() / "old-attempt" / "workspace"
    workspace.mkdir(parents=True)
    assert projects.session_working_directory(workspace) == workspace
    assert not (workspace.parent / projects.RECORD).exists()


def test_framework_prompt_uses_task_specific_absolute_handoff_and_memory_paths(tmp_path):
    from hypertest.cloud.native_worker import native_prompt

    workspace = tmp_path.resolve() / "attempt-one" / "workspace"
    framework = tmp_path.resolve() / "shared" / "hypervise_pure"
    task = {"id": str(uuid4()), "frozen_manifest": {}}
    attempt = {"id": str(uuid4())}
    prompt = json.loads(native_prompt(task, attempt, workspace,
        framework_project=framework, memory_enabled=True))
    instructions = "\n".join(prompt["instructions"])
    assert str(framework) in instructions
    assert str(workspace / "sut") in instructions
    assert prompt["artifact_workspace"] == str(framework)
    assert prompt["handoff_directory"] == str(workspace / ".hypertest-cloud/ready")
    for key, relative in (("ready_directory", "ready"), ("receipt_directory", "receipts"),
                          ("local_rejection_directory", "rejections")):
        assert prompt["handoff_contract"][key] == str(workspace / ".hypertest-cloud" / relative)
    memory = prompt["memory_contract"]
    assert memory["ready_directory"] == str(workspace / ".hypertest-cloud/memory-ready")
    assert memory["response_directory"] == str(workspace / ".hypertest-cloud/memory-responses")
    assert memory["query_protocol"]["protocol_file"] == str(workspace / ".hypertest-cloud/memory-protocol/query.json")
    assert not prompt["handoff_directory"].startswith(str(framework))


def test_sdk_configuration_and_initialize_use_framework_directory(tmp_path, monkeypatch):
    from hypertest.cloud import native_cordis
    from hypertest.cloud import native_sdk_driver as driver

    workspace = tmp_path.resolve() / "attempt" / "workspace"
    workspace.mkdir(parents=True)
    framework = tmp_path.resolve() / "hypervise_pure"
    framework.mkdir()
    (workspace.parent / projects.RECORD).write_text(json.dumps({
        "profile": projects.PROFILE, "path": str(framework), "title": "hypervise",
        "repository": "gitlab.charprotocol.com/zhangliangchen/hypervise_pure",
    }))
    observed = {}
    module = ModuleType("deepseek_harness")

    class Config:
        def __init__(self, **values):
            observed["options"] = values
            self.values = values

    class Subscription:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def drain(self, observe): pass

    class Client:
        def __init__(self, config): self.env = config.values["env"]
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def initialize(self, **kwargs):
            observed["initialize"] = kwargs
            Path(self.env["DSH_SDK_CORDIS_HANDSHAKE"]).write_text(json.dumps({
                "phase": "registered", "nonce": self.env["DSH_SDK_CORDIS_NONCE"],
                "root": self.env["DSH_SDK_CORDIS_ROOT"],
            }))
            return SimpleNamespace(serverInfo=SimpleNamespace(name="deepseek-harness-sdk-runtime", version="0.0.1"))
        def subscribe_notifications(self): return Subscription()
        def session_prompt(self, session_id, *args, **kwargs): observed["session_id"] = session_id
        def request(self, *args, **kwargs): pass

    module.HarnessConfig, module.HarnessClient = Config, Client
    monkeypatch.setitem(sys.modules, "deepseek_harness", module)
    monkeypatch.setattr(native_cordis, "prepare_cordis_overlay", lambda directory, **kwargs: directory / "overlay.yml")
    def selection(**kwargs):
        observed["selection"] = kwargs
        return {"provider": "deepseek-official", "model": "deepseek-flash", "reasoning_effort": "max"}
    monkeypatch.setattr(driver, "read_native_selection", selection)
    driver.run({"workspace": str(workspace), "dsh_home": str(tmp_path), "session_id": "cloud-original-id",
                "title": "framework test", "prompt": "synthetic fixture only"}, lambda _: None)
    assert observed["options"]["cwd"] == str(framework)
    assert observed["initialize"]["cwd"] == str(framework)
    assert observed["selection"]["cwd"] == str(framework)
    assert observed["session_id"] == "cloud-original-id"


@pytest.fixture
def artifact_reporting(tmp_path, monkeypatch):
    from hypertest.cloud.reporter import CloudTaskReporter

    workspace = tmp_path.resolve() / "task-messages"
    framework = tmp_path.resolve() / "hypervise_pure"
    workspace.mkdir()
    framework.mkdir()
    deliveries, validations = [], []

    async def validate(request):
        validations.append(request)

    async def deliver(intent):
        deliveries.append(intent)
        return SimpleNamespace(synced=False)

    broker = SimpleNamespace(project_id=str(uuid4()), task_id=str(uuid4()), attempt_id=str(uuid4()),
        version=1, identity=SimpleNamespace(generation=1), validate_payload=validate)
    reporter = CloudTaskReporter(broker=broker, private_root=tmp_path / "private",
        workspace=workspace, artifact_workspace=framework)
    monkeypatch.setattr(reporter.core, "deliver", deliver)
    yield SimpleNamespace(reporter=reporter, broker=broker, workspace=workspace, framework=framework,
        deliveries=deliveries, validations=validations)
    reporter.close()


def artifact_handoff(fixture, path, content, *, key):
    import hashlib

    from hypertest.cloud.manifests import MANIFEST_PROFILE, Handoff

    return Handoff(profile=MANIFEST_PROFILE, task_id=fixture.broker.task_id,
        attempt_id=fixture.broker.attempt_id, key=key, operation="UPLOAD_ARTIFACT",
        payload={"path": path, "filename": Path(path).name, "media_type": "text/markdown",
            "sha256": hashlib.sha256(content).hexdigest(), "byte_count": len(content)})


@pytest.mark.asyncio
async def test_reporter_uploads_original_framework_report_without_copying_to_transport(artifact_reporting):
    import base64

    from hypertest.sync_core import digest

    fixture = artifact_reporting
    original = fixture.framework / "docs/reports/result.md"
    original.parent.mkdir(parents=True)
    content = "# Framework report\nOriginal test observations.\n".encode()
    original.write_bytes(content)
    handoff = artifact_handoff(fixture, "docs/reports/result.md", content, key="original-report")
    await fixture.reporter.submit_handoff(handoff, digest(handoff.model_dump(mode="json")))
    assert len(fixture.deliveries) == 1
    request = fixture.deliveries[0].payload
    assert base64.b64decode(request["content_base64"], validate=True) == content
    assert request["filename"] == "result.md"
    assert "path" not in request
    assert original.read_bytes() == content
    assert not (fixture.workspace / "docs").exists()
    assert not (fixture.workspace / "artifacts").exists()


@pytest.mark.asyncio
async def test_reporter_refuses_parent_and_symlink_escape_from_framework(artifact_reporting):
    from hypertest.sync_core import digest

    fixture = artifact_reporting
    content = b"outside framework\n"
    outside = fixture.framework.parent / "outside.md"
    outside.write_bytes(content)
    reports = fixture.framework / "docs/reports"
    reports.mkdir(parents=True)
    (reports / "leak.md").symlink_to(outside)
    for index, (path, code) in enumerate((
        ("../outside.md", "ARTIFACT_PATH_INVALID"),
        ("docs/reports/leak.md", "ARTIFACT_PATH_UNAVAILABLE"),
    )):
        handoff = artifact_handoff(fixture, path, content, key=f"escape-{index}")
        with pytest.raises(CloudBlocked) as error:
            await fixture.reporter.submit_handoff(handoff, digest(handoff.model_dump(mode="json")))
        assert error.value.code == code
    assert fixture.deliveries == fixture.validations == []
    assert fixture.reporter.pending() == []
