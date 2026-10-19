"""Source preparation retains actionable categories without any subprocess text."""

from __future__ import annotations

import asyncio
import errno
import json
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hypertest.application import workspaces
from hypertest.application.source_diagnostics import (
    GIT_OUTPUT_LIMIT,
    SOURCE_DIAGNOSTIC_VERSION,
    SOURCE_PREPARATION_CATEGORIES,
    SourcePreparationError,
    git_failure,
    safe_source_diagnostic,
)
from hypertest.config import get_settings
from hypertest.runner import source as runner_source
from hypertest.runner.backends import ProcessResult, run_process
from hypertest.runner.source import SourceGitError, SourceValidationError

SECRET = "credential-canary-never-retain"
REPOSITORY = "https://github.com/example/source"
COMMIT = "a" * 40
STAGES = ["git_init", "configure_remote", "fetch_commit", "checkout_commit"]


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    snapshot = SimpleNamespace(id=uuid4(), repository_url=REPOSITORY, commit_sha=COMMIT)
    run = SimpleNamespace(source_snapshot_id=snapshot.id)

    class Session:
        async def get(self, _model, _identity):
            return snapshot

    async def get_run(_session, _run_id):
        return run

    async def valid(*_args, **_options):
        return ["src/example.py"]

    monkeypatch.setattr(workspaces, "get_test_run", get_run)
    monkeypatch.setattr(workspaces, "validate_checkout", valid)
    monkeypatch.setattr(workspaces.shutil, "which", lambda _name: "/usr/bin/git")
    monkeypatch.setattr(get_settings(), "workspace_root", str(tmp_path))
    return Session(), snapshot, tmp_path


@pytest.mark.parametrize("stderr,category", [
    ("fatal: Authentication failed for 'https://user:password@github.com/a/b'", "authentication"),
    ("could not read Username: terminal prompts disabled", "authentication"),
    ("fatal: repository not found", "access_or_missing_repository"),
    ("fatal: unable to access 'https://a/b': The requested URL returned error: 403", "access_or_missing_repository"),
    ("fatal: unable to access 'https://a/b': The requested URL returned error: 404", "access_or_missing_repository"),
    ("fatal: could not resolve proxy: internal-proxy", "network"),
    ("fatal: could not resolve host: github.com", "network"),
    ("fatal: Failed to connect to github.com port 443", "network"),
    ("fatal: The requested URL returned error: 503", "network"),
    ("fatal: SSL certificate problem: unable to get local issuer certificate", "tls"),
    ("fatal: remote error: upload-pack: not our ref " + COMMIT, "revision_not_found"),
    ("fatal: reference is not a tree: " + COMMIT, "revision_not_found"),
    ("fatal: could not create work tree dir: Permission denied", "storage"),
    ("fatal: unable to write: No space left on device", "storage"),
    ("fatal: read-only file system", "storage"),
    ("fatal: arbitrary unknown text", "unknown"),
])
def test_git_categories_only_retain_allowlisted_observations(stderr, category):
    raw = (stderr + f"\nAuthorization: Bearer {SECRET}\nhttps://user:{SECRET}@proxy.invalid/private").encode()
    error = git_failure("fetch_commit", ProcessResult(raw, raw, 128))
    assert error.diagnostic["category"] == category
    assert error.diagnostic["exit_code"] == 128
    retained = json.dumps(error.diagnostic) + str(error)
    assert SECRET not in retained
    assert "https://" not in retained
    assert "Authorization" not in retained
    assert "stderr" not in error.diagnostic and "stdout" not in error.diagnostic
    assert len(retained) < 1500


def test_timeout_takes_precedence_and_reports_truncation_without_contents():
    error = git_failure("fetch_commit", ProcessResult(
        b"x" * (GIT_OUTPUT_LIMIT + 1), b"Authentication failed", -9, timed_out=True,
    ))
    assert error.diagnostic["category"] == "timeout"
    assert error.diagnostic["timed_out"] is True
    assert error.diagnostic["output_truncated"] is True


def test_unrecognized_suffix_beyond_classification_bound_is_never_scanned():
    error = git_failure("fetch_commit", ProcessResult(
        b"", b"x" * GIT_OUTPUT_LIMIT + b"Authentication failed " + SECRET.encode(), 128,
    ))
    assert error.diagnostic["category"] == "unknown"
    assert error.diagnostic["output_truncated"] is True
    assert SECRET not in str(error.diagnostic)


def test_collector_marker_reports_truncation():
    error = git_failure("git_init", ProcessResult(
        b"", b"failure\n[HyperTest collector truncated oversized output]\n", 1,
    ))
    assert error.diagnostic["output_truncated"] is True


@pytest.mark.parametrize("stage", STAGES)
async def test_each_git_stage_is_captured_and_staging_is_removed(preparation, monkeypatch, stage):
    session, snapshot, tmp_path = preparation
    calls = []

    async def process(command, **options):
        calls.append(command)
        assert options["output_limit"] == GIT_OUTPUT_LIMIT
        assert options["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert options["env"]["LC_ALL"] == "C"
        if len(calls) == STAGES.index(stage) + 1:
            return ProcessResult(SECRET.encode(), b"fatal: Authentication failed " + SECRET.encode(), 128)
        return ProcessResult(b"", b"", 0)

    monkeypatch.setattr(workspaces, "run_process", process)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    diagnostic = failure.value.diagnostic
    assert diagnostic["schema_version"] == SOURCE_DIAGNOSTIC_VERSION
    assert diagnostic["stage"] == stage
    assert diagnostic["category"] == "authentication"
    assert len(calls) == STAGES.index(stage) + 1
    assert SECRET not in str(failure.value) + json.dumps(diagnostic)
    assert list((tmp_path / ".hypertest-checkouts" / str(snapshot.id)).iterdir()) == []


@pytest.mark.parametrize("raised,category", [
    (FileNotFoundError(errno.ENOENT, SECRET, SECRET), "git_unavailable"),
    (PermissionError(errno.EACCES, SECRET, SECRET), "storage"),
    (OSError(errno.EIO, SECRET, SECRET), "storage"),
    (OSError(errno.EAGAIN, SECRET, SECRET), "unknown"),
])
async def test_spawn_errors_are_safe_and_never_copy_exception_details(preparation, monkeypatch, raised, category):
    session, _snapshot, _tmp_path = preparation

    async def process(*_args, **_options):
        raise raised

    monkeypatch.setattr(workspaces, "run_process", process)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "git_init"
    assert failure.value.diagnostic["category"] == category
    assert SECRET not in str(failure.value) + json.dumps(failure.value.diagnostic)
    assert failure.value.__suppress_context__ is True


async def test_missing_git_stops_before_creating_workspace(preparation, monkeypatch):
    session, _snapshot, tmp_path = preparation
    monkeypatch.setattr(workspaces.shutil, "which", lambda _name: None)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "validate_input"
    assert failure.value.diagnostic["category"] == "git_unavailable"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field,value", [
    ("repository_url", f"https://user:{SECRET}@github.com/a/b"),
    ("repository_url", f"https://github.com/a/b?token={SECRET}"),
    ("commit_sha", SECRET),
])
async def test_frozen_invalid_inputs_are_not_echoed_or_mutated(preparation, field, value):
    session, snapshot, tmp_path = preparation
    setattr(snapshot, field, value)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "validate_input"
    assert failure.value.diagnostic["category"] == "invalid_source"
    assert failure.value.diagnostic["retryable"] is False
    assert getattr(snapshot, field) == value
    assert SECRET not in str(failure.value) + json.dumps(failure.value.diagnostic)
    assert list(tmp_path.iterdir()) == []


async def test_storage_failure_before_git_never_exposes_path(preparation, monkeypatch):
    session, _snapshot, _tmp_path = preparation

    def directory(*_args, **_options):
        raise PermissionError(errno.EACCES, SECRET, SECRET)

    monkeypatch.setattr(workspaces.Path, "mkdir", directory)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "create_workspace"
    assert failure.value.diagnostic["category"] == "storage"
    assert SECRET not in str(failure.value) + json.dumps(failure.value.diagnostic)


async def test_existing_checkout_validation_failure_is_distinct_and_never_replaced(preparation, monkeypatch):
    session, snapshot, tmp_path = preparation
    existing = tmp_path / ".hypertest-checkouts" / str(snapshot.id) / "repo"
    existing.mkdir(parents=True)
    retained = existing / "existing-history"
    retained.write_text("retained")

    async def invalid(*_args, **_options):
        raise SourceValidationError(SECRET)

    monkeypatch.setattr(workspaces, "validate_checkout", invalid)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "validate_checkout"
    assert failure.value.diagnostic["category"] == "checkout_integrity"
    assert failure.value.diagnostic["retryable"] is False
    assert retained.read_text() == "retained"
    assert SECRET not in str(failure.value)


@pytest.mark.parametrize("failure,category", [
    (ProcessResult(b"", ("Authentication failed " + SECRET).encode(), 128), "authentication"),
    (ProcessResult(b"", ("Permission denied " + SECRET).encode(), 128), "storage"),
    (ProcessResult(b"", ("No space left on device " + SECRET).encode(), 128), "storage"),
    (ProcessResult(b"", ("Connection reset " + SECRET).encode(), 128), "network"),
    (ProcessResult(b"", SECRET.encode(), 0, timed_out=True), "timeout"),
])
async def test_validation_process_failures_remain_retryable_observations(
    preparation, monkeypatch, failure, category,
):
    session, snapshot, tmp_path = preparation
    existing = tmp_path / ".hypertest-checkouts" / str(snapshot.id) / "repo"
    existing.mkdir(parents=True)
    retained = existing / "operator-history"
    retained.write_text("preserve")

    async def process(command, **options):
        assert options["output_limit"] == GIT_OUTPUT_LIMIT
        assert "ls-files" not in command
        if command[3:] == ["rev-parse", "--show-toplevel"]:
            return ProcessResult(str(existing).encode(), b"", 0)
        if command[3:] == ["rev-parse", "HEAD"]:
            return ProcessResult(COMMIT.encode(), b"", 0)
        assert command[3] == "status"
        return failure

    monkeypatch.setattr(workspaces, "validate_checkout", runner_source.validate_checkout)
    monkeypatch.setattr(runner_source, "run_process", process)
    with pytest.raises(SourcePreparationError) as stopped:
        await workspaces.prepare_workspace(session, uuid4())
    diagnostic = stopped.value.diagnostic
    assert diagnostic["stage"] == "validate_checkout"
    assert diagnostic["category"] == category
    assert diagnostic["retryable"] is True
    assert diagnostic["timed_out"] is failure.timed_out
    assert SECRET not in str(stopped.value) + json.dumps(diagnostic)
    assert retained.read_text() == "preserve"


async def test_proven_checkout_mismatch_still_requires_integrity_review(preparation, monkeypatch):
    session, snapshot, tmp_path = preparation
    existing = tmp_path / ".hypertest-checkouts" / str(snapshot.id) / "repo"
    existing.mkdir(parents=True)

    async def process(command, **options):
        assert options["output_limit"] == GIT_OUTPUT_LIMIT
        if command[3:] == ["rev-parse", "--show-toplevel"]:
            return ProcessResult(str(existing).encode(), b"", 0)
        assert command[3:] == ["rev-parse", "HEAD"]
        return ProcessResult(("b" * 40).encode(), b"", 0)

    monkeypatch.setattr(workspaces, "validate_checkout", runner_source.validate_checkout)
    monkeypatch.setattr(runner_source, "run_process", process)
    with pytest.raises(SourcePreparationError) as stopped:
        await workspaces.prepare_workspace(session, uuid4())
    assert stopped.value.diagnostic["stage"] == "validate_checkout"
    assert stopped.value.diagnostic["category"] == "checkout_integrity"
    assert stopped.value.diagnostic["retryable"] is False


@pytest.mark.parametrize("position", ["root", "parent", "destination"])
async def test_symlink_loops_have_safe_retryable_diagnostics_and_preserve_links(
    preparation, monkeypatch, position,
):
    session, snapshot, tmp_path = preparation
    if position == "root":
        loop = tmp_path / SECRET
        monkeypatch.setattr(get_settings(), "workspace_root", str(loop))
    elif position == "parent":
        managed = tmp_path / ".hypertest-checkouts"
        managed.mkdir()
        loop = managed / str(snapshot.id)
    else:
        parent = tmp_path / ".hypertest-checkouts" / str(snapshot.id)
        parent.mkdir(parents=True)
        loop = parent / "repo"
    loop.symlink_to(loop)
    with pytest.raises(SourcePreparationError) as stopped:
        await workspaces.prepare_workspace(session, uuid4())
    assert stopped.value.diagnostic["stage"] == (
        "validate_checkout" if position == "destination" else "create_workspace"
    )
    assert stopped.value.diagnostic["category"] == "storage"
    assert stopped.value.diagnostic["retryable"] is True
    assert SECRET not in str(stopped.value) + json.dumps(stopped.value.diagnostic)
    assert str(tmp_path) not in str(stopped.value) + json.dumps(stopped.value.diagnostic)
    assert loop.is_symlink() and loop.readlink() == loop


async def test_unrelated_runtime_errors_are_not_disguised_as_source_diagnostics(preparation, monkeypatch):
    session, snapshot, tmp_path = preparation
    existing = tmp_path / ".hypertest-checkouts" / str(snapshot.id) / "repo"
    existing.mkdir(parents=True)

    async def programmer_error(*_args, **_options):
        raise RuntimeError("unexpected application error")

    monkeypatch.setattr(workspaces, "validate_checkout", programmer_error)
    with pytest.raises(RuntimeError, match="unexpected application error") as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert not isinstance(failure.value, SourcePreparationError)


async def test_validation_git_timeout_has_safe_typed_error(monkeypatch, tmp_path):
    async def process(*_args, **options):
        assert options["output_limit"] == GIT_OUTPUT_LIMIT
        return ProcessResult(SECRET.encode(), SECRET.encode(), 0, timed_out=True)

    monkeypatch.setattr(runner_source, "run_process", process)
    with pytest.raises(SourceGitError) as failure:
        await runner_source.git(tmp_path, "rev-parse", "HEAD", output_limit=GIT_OUTPUT_LIMIT)
    assert isinstance(failure.value, SourceValidationError)
    assert failure.value.result.timed_out is True
    assert SECRET not in str(failure.value)


async def test_validation_can_skip_unused_file_listing_without_changing_default_semantics(
    tmp_path, monkeypatch,
):
    source = tmp_path / "real-source"
    source.mkdir()
    tracked = [f"source_{index:04d}_{'x' * 35}.py" for index in range(400)]
    for filename in tracked:
        (source / filename).write_text("value = 1\n")

    def git(*arguments):
        return subprocess.run(
            ["git", "-C", str(source), *arguments], check=True, capture_output=True,
        ).stdout.decode().strip()

    git("init")
    git("remote", "add", "origin", REPOSITORY)
    git("add", ".")
    git("-c", "user.name=Source Test", "-c", "user.email=source-test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-m", "Pinned validation fixture")
    commit = git("rev-parse", "HEAD")
    assert len(git("ls-files").encode()) > GIT_OUTPUT_LIMIT
    calls = []

    async def process(command, **options):
        calls.append((command, options))
        return await run_process(command, **options)

    monkeypatch.setattr(runner_source, "run_process", process)
    assert await runner_source.validate_checkout(source, commit, REPOSITORY) == tracked
    assert len(calls) == 5
    assert all(options["output_limit"] == 8 * 1024 * 1024 for _, options in calls)
    calls.clear()
    assert await runner_source.validate_checkout(
        source, commit, REPOSITORY, include_files=False, output_limit=GIT_OUTPUT_LIMIT,
    ) == []
    assert len(calls) == 4
    assert all("ls-files" not in command for command, _ in calls)
    assert all(options["output_limit"] == GIT_OUTPUT_LIMIT for _, options in calls)


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_cancellation_propagates_even_when_cleanup_fails(preparation, monkeypatch, cleanup_fails):
    session, snapshot, tmp_path = preparation

    async def cancelled(*_args, **_options):
        raise asyncio.CancelledError()

    def failed_cleanup(*_args, **_options):
        raise OSError(errno.EACCES, SECRET, SECRET)

    monkeypatch.setattr(workspaces, "run_process", cancelled)
    if cleanup_fails:
        monkeypatch.setattr(workspaces.shutil, "rmtree", failed_cleanup)
    with pytest.raises(asyncio.CancelledError):
        await workspaces.prepare_workspace(session, uuid4())
    if not cleanup_fails:
        assert list((tmp_path / ".hypertest-checkouts" / str(snapshot.id)).iterdir()) == []


async def test_cleanup_error_cannot_replace_primary_diagnostic(preparation, monkeypatch):
    session, _snapshot, _tmp_path = preparation

    async def failed(*_args, **_options):
        return ProcessResult(b"", b"authentication failed", 128)

    def failed_cleanup(*_args, **_options):
        raise OSError(errno.EACCES, SECRET, SECRET)

    monkeypatch.setattr(workspaces, "run_process", failed)
    monkeypatch.setattr(workspaces.shutil, "rmtree", failed_cleanup)
    with pytest.raises(SourcePreparationError) as failure:
        await workspaces.prepare_workspace(session, uuid4())
    assert failure.value.diagnostic["stage"] == "git_init"
    assert failure.value.diagnostic["category"] == "authentication"


def test_safe_projection_rebuilds_fixed_text_and_drops_arbitrary_fields():
    original = SourcePreparationError(stage="fetch_commit", category="invalid_source").diagnostic
    poisoned = {**original, "summary": SECRET, "action": SECRET, "stderr": SECRET,
                "command": SECRET, "repository_url": SECRET, "retryable": True}
    assert safe_source_diagnostic(poisoned) == original
    assert SECRET not in json.dumps(safe_source_diagnostic(poisoned))
    assert poisoned["summary"] == SECRET


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unknown"), ("stage", "unknown"), ("stage", []),
    ("category", "new_category"), ("category", {}), ("retryable", "false"),
    ("timed_out", 0), ("output_truncated", None), ("exit_code", True),
    ("exit_code", 256), ("exit_code", -256), ("exit_code", SECRET),
])
def test_safe_projection_rejects_unknown_or_malformed_payload(field, value):
    payload = deepcopy(SourcePreparationError(stage="fetch_commit", category="unknown").diagnostic)
    payload[field] = value
    assert safe_source_diagnostic(payload) is None


@pytest.mark.parametrize("value", [None, SECRET, [], 1, {"schema_version": SOURCE_DIAGNOSTIC_VERSION}])
def test_safe_projection_rejects_non_diagnostic_values(value):
    assert safe_source_diagnostic(value) is None


@pytest.mark.parametrize("category", SOURCE_PREPARATION_CATEGORIES)
def test_diagnostic_catalog_is_bounded_and_round_trips(category):
    diagnostic = SourcePreparationError(stage="fetch_commit", category=category).diagnostic
    assert len(json.dumps(diagnostic)) < 1024
    assert safe_source_diagnostic(diagnostic) == diagnostic
    assert diagnostic["retryable"] is (category not in {"invalid_source", "checkout_integrity"})


async def test_real_process_drains_both_streams_but_retains_only_bounded_output(tmp_path):
    result = await run_process(
        [sys.executable, "-c", "import os; os.write(1,b'a'*262144); os.write(2,b'b'*262144)"],
        cwd=tmp_path, timeout=10, output_limit=GIT_OUTPUT_LIMIT,
    )
    assert result.exit_code == 0 and not result.timed_out
    for value in (result.stdout, result.stderr):
        assert GIT_OUTPUT_LIMIT < len(value) < GIT_OUTPUT_LIMIT + 100
        assert value.endswith(b"[HyperTest collector truncated oversized output]\n")
