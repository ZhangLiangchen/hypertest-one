"""Behavioral checks for explicit CLI delivery, credentials and safe installation."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from hypertest.api.archive_schemas import ArchiveSubmit
from hypertest.cli import PREFIX, PROFILE, archive, auth, skills
from hypertest.cli.manifest import load_manifest
from hypertest.cli.state import CLIError, State
from hypertest.cli.transport import HTTP, server_url
from hypertest.sync_core import canonical_json, digest

P, T, S = (str(uuid.uuid4()) for _ in range(3))
ACTOR = "interactive:" + str(uuid.uuid4())
SERVER = "https://hypertest.example"


@pytest.fixture
def state(tmp_path):
    instance = State(tmp_path / "private")
    instance.save_profile("default", SERVER, str(uuid.uuid4()), ACTOR, {
        "grant_id": str(uuid.uuid4()), "project_ids": [P],
        "scopes": ["archive:read", "archive:write"], "expires_at": "2099-01-01T00:00:00+00:00",
        "credential": "private-credential-value"})
    return instance


def manifest(tmp_path, *, child=None):
    (tmp_path / "report.txt").write_bytes("Original FAIL\r\n中文报告\n".encode())
    value = {"profile": PROFILE, "project_id": P, "task_id": T,
             "assets": [{"kind": "REPORT", "stable_key": "report", "title": "Report",
                         "path": "report.txt", "reported_result": "FAIL",
                         "origin": {"origin_session_ref": "old-session"}}]}
    if child:
        value["subtask_id"] = child
        value["subtask_update"] = {"reported_result": "FAIL", "status": "COMPLETED"}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    return path


class ArchiveServer:
    def __init__(self, child=None):
        self.target = {"profile": PROFILE, "project_id": P, "task_id": T,
                       "subtask_id": child, "target_kind": "SUBTASK" if child else "TASK"}
        self.snapshot = {**self.target, "archive_version": 1, "assets": []}
        if child:
            self.snapshot.update(status="DRAFT", reported_result="NOT_RUN")
        self.receipts, self.documents, self.calls = {}, {}, []
        self.lose_post, self.denied, self.tamper = False, False, False

    def factory(self, server, **kwargs):
        assert server == SERVER
        assert kwargs.get("token") == "private-credential-value"
        return self

    def page(self, document, query, submission_id=None):
        content = canonical_json(document)
        offset = query.get("offset", 0)
        chunk = content[offset:offset + 81]
        end = offset + len(chunk)
        return {**self.target, "submission_id": submission_id,
                "archive_version": document["archive_version"], "offset": offset,
                "total_chars": len(content), "next_offset": end if end < len(content) else None,
                "complete": end == len(content), "content": chunk}

    def call(self, method, path, *, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body), copy.deepcopy(query)))
        if self.denied:
            raise CLIError("ARCHIVE_NOT_AUTHORIZED", 3, status=403)
        if method == "POST":
            parsed = ArchiveSubmit.model_validate(body)
            assert parsed.wire() == body  # CLI's canonical request is the real API contract.
            key = body["idempotency_key"]
            if key in self.receipts:
                return self.receipts[key]
            if body["expected_archive_version"] != self.snapshot["archive_version"]:
                raise CLIError("ARCHIVE_VERSION_CONFLICT", 3, status=409)
            submission = str(uuid.uuid4())
            document = copy.deepcopy(self.snapshot)
            old = archive.asset_map(document)
            changed = False
            for asset in body["assets"]:
                identity = (asset["kind"], asset["stable_key"])
                previous = old.get(identity)
                if previous is None or archive.business(previous) != asset:
                    changed = True
                    old[identity] = {**asset, "id": str(uuid.uuid4()),
                        "revision": previous["revision"] + 1 if previous else 1,
                        "submission_id": submission, "accepted_at": "2026-10-27T01:00:00+00:00",
                        "uploader_actor_ref": ACTOR}
            document["assets"] = sorted(old.values(), key=lambda a: (a["kind"], a["stable_key"]))
            for key, value in body.get("subtask_update", {}).items():
                changed |= document[key] != value
                document[key] = value
            document["archive_version"] += changed
            receipt = {**self.target, "submission_id": submission,
                       "uploader_actor_ref": ACTOR, "idempotency_key": body["idempotency_key"],
                       "request_digest": digest(body), "outcome": "ACCEPTED" if changed else "UNCHANGED",
                       "accepted_version": document["archive_version"]}
            self.receipts[body["idempotency_key"]] = receipt
            self.documents[submission] = document
            self.snapshot = document
            if self.lose_post:
                self.lose_post = False
                raise CLIError("TRANSPORT_UNCERTAIN", 4)
            return copy.deepcopy(receipt)
        if path == PREFIX + "/submissions/by-key":
            return copy.deepcopy(self.receipts[query["idempotency_key"]])
        if path.startswith(PREFIX + "/submissions/"):
            key = path.rsplit("/", 1)[-1]
            doc = copy.deepcopy(self.documents[key])
            if self.tamper:
                doc["assets"][0]["markdown"] += "corrupted"
            return self.page(doc, query, key)
        return self.page(self.snapshot, query)


@pytest.mark.parametrize("child", [None, S])
def test_archive_preserves_original_body_and_complete_fixed_readback(state, tmp_path, child):
    server = ArchiveServer(child)
    result, code = archive.archive(state, profile_name=None, project_id=P, task_id=T,
        subtask_id=child, manifest=manifest(tmp_path, child=child), http_factory=server.factory)
    assert code == 0 and result["status"] == "ARCHIVED" and result["readback_complete"]
    assert result["target_kind"] == ("SUBTASK" if child else "TASK")
    assert server.snapshot["assets"][0]["markdown"] == "Original FAIL\r\n中文报告\n"
    assert server.snapshot["assets"][0]["reported_result"] == "FAIL"
    assert all(call[3]["archive_version"] == 2 for call in server.calls
               if call[1].startswith(PREFIX + "/submissions/") and call[0] == "GET")
    second, code = archive.archive(state, profile_name=None, project_id=P, task_id=T,
        subtask_id=child, manifest=tmp_path / "missing.json", request_id=result["request_id"],
        http_factory=server.factory)
    assert code == 0 and second == result
    assert sum(call[0] == "POST" for call in server.calls) == 1


def test_uncertain_post_survives_restart_and_only_gets_original_key(state, tmp_path):
    server = ArchiveServer()
    server.lose_post = True
    result, code = archive.archive(state, profile_name=None, project_id=P, task_id=T, subtask_id=None,
                                  manifest=manifest(tmp_path), http_factory=server.factory)
    assert code == 4 and result["status"] == "UNKNOWN"
    before = len(server.calls)
    (tmp_path / "report.txt").write_text("Changed after uncertain send")
    restarted = State(state.directory)
    result, code = archive.status(restarted, result["request_id"], remote=True, http_factory=server.factory)
    assert code == 0 and result["status"] == "ARCHIVED"
    assert all(call[0] == "GET" for call in server.calls[before:])
    assert "Changed" not in server.snapshot["assets"][0]["markdown"]


def test_unchanged_does_not_advance_version_and_readback_mismatch_never_success(state, tmp_path):
    server = ArchiveServer()
    path = manifest(tmp_path)
    arguments = dict(profile_name=None, project_id=P, task_id=T, subtask_id=None,
                     manifest=path, http_factory=server.factory)
    assert archive.archive(state, **arguments)[1] == 0
    result, code = archive.archive(state, **arguments)
    assert code == 0 and result["status"] == "UNCHANGED" and result["accepted_version"] == 2
    server.tamper = True
    result, code = archive.archive(state, **arguments)
    assert code == 4 and result["code"] == "READBACK_CONTENT_MISMATCH"
    assert not result["readback_complete"]


def test_revoked_recovery_is_not_resent(state, tmp_path):
    server = ArchiveServer()
    server.lose_post = True
    result, _ = archive.archive(state, profile_name=None, project_id=P, task_id=T, subtask_id=None,
        manifest=manifest(tmp_path), http_factory=server.factory)
    server.denied = True
    before = len(server.calls)
    result, code = archive.status(state, result["request_id"], remote=True, http_factory=server.factory)
    assert code == 4 and not result["readback_complete"]
    assert all(call[0] == "GET" for call in server.calls[before:])


def test_wrong_target_and_binary_secret_sources_fail_before_network(state, tmp_path):
    path = manifest(tmp_path)
    server = ArchiveServer()
    with pytest.raises(CLIError, match="MANIFEST_TARGET_MISMATCH"):
        archive.archive(state, profile_name=None, project_id=P, task_id=T, subtask_id=S,
                        manifest=path, http_factory=server.factory)
    assert not server.calls
    (tmp_path / "report.txt").write_text("-----BEGIN PRIVATE KEY-----")
    with pytest.raises(CLIError, match="SECRET_MATERIAL_REJECTED"):
        load_manifest(path, project_id=P, task_id=T)
    (tmp_path / "report.txt").write_bytes(b"binary\x00data")
    with pytest.raises(CLIError, match="BINARY_ARTIFACT_UNSUPPORTED"):
        load_manifest(path, project_id=P, task_id=T)


class PairingServer:
    def __init__(self):
        self.calls, self.operations = [], {}
        self.lose_create, self.lose_redeem, self.revoked = False, False, False
        self.view = None

    def factory(self, server, **kwargs):
        assert server == SERVER
        self.proof = kwargs["proof"]
        return self

    def receipt(self, phase, body):
        result = {**copy.deepcopy(self.view), "operation": phase,
                  "idempotency_key": body["idempotency_key"], "request_digest": digest(body)}
        self.operations[phase] = result
        return result

    def call(self, method, path, *, query=None, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == "POST" and path.endswith("/requests"):
            self.view = {"request_id": body["request_id"], "status": "PENDING",
                "client_instance_id": body["client_instance_id"], "client_name": body["client_name"],
                "server_url": body["server_url"], "short_code": "ABCD-1234",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "verification_url": SERVER + "/cli-authorizations?request_id=" + body["request_id"],
                "credential_fingerprint": body["credential_hash"][:16], "approval": None, "grants": []}
            assert body["verifier_challenge"] == auth.sha256(self.proof)
            result = self.receipt("CREATE", body)
            self.view.update(status="APPROVED", approval={"actor_ref": ACTOR,
                "actor_identity_id": ACTOR.split(":")[1], "project_ids": [P],
                "scopes": ["archive:read", "archive:write"], "expires_at": "2099-01-01T00:00:00+00:00",
                "approval_digest": "a" * 64})
            if self.lose_create:
                self.lose_create = False
                raise CLIError("TRANSPORT_UNCERTAIN", 4)
            return result
        if method == "POST" and path.endswith("/redeem"):
            self.view.update(status="BOUND", grants=[{"grant_id": str(uuid.uuid4()), "project_id": P,
                "scopes": ["archive:read", "archive:write"], "expires_at": "2099-01-01T00:00:00+00:00",
                "status": "ACTIVE"}])
            result = self.receipt("REDEEM", body)
            if self.lose_redeem:
                self.lose_redeem = False
                raise CLIError("TRANSPORT_UNCERTAIN", 4)
            return result
        if path.endswith("by-key"):
            return copy.deepcopy(self.operations[query["operation"]])
        result = copy.deepcopy(self.view)
        if self.revoked and result["grants"]:
            result["grants"][0]["status"] = "REVOKED"
        return result


def test_pairing_one_confirmation_no_secret_output_and_global_profile(tmp_path):
    state = State(tmp_path / "private")
    server = PairingServer()
    result, code = auth.bind(state, server=SERVER, open_browser=False, wait_seconds=1,
                            sleep=lambda _: None, http_factory=server.factory)
    assert code == 0 and result["profile_saved"]
    record = state.read(state.pairings, result["request_id"])
    assert record["credential"] not in json.dumps(result) and record["verifier"] not in json.dumps(result)
    profile = state.profile(None, project_id=P)
    assert profile["grant"]["credential"] == record["credential"]
    assert len([c for c in server.calls if c[0] == "POST"]) == 2
    with pytest.raises(CLIError, match="PROJECT_NOT_AUTHORIZED"):
        state.profile("default", project_id=str(uuid.uuid4()))
    assert state.profiles.joinpath("default.json").stat().st_mode & 0o777 == 0o600


def test_pairing_create_unknown_reconcile_does_not_redeem_but_explicit_resume_can(tmp_path):
    state, server = State(tmp_path / "private"), PairingServer()
    server.lose_create = True
    result, code = auth.bind(state, server=SERVER, open_browser=False, wait_seconds=1,
                            sleep=lambda _: None, http_factory=server.factory)
    assert code == 4
    result, code = auth.reconcile(state, result["request_id"], http_factory=server.factory)
    assert code == 4 and result["status"] == "APPROVED"
    assert sum(c[0] == "POST" for c in server.calls) == 1
    result, code = auth.bind(state, server=None, request_id=result["request_id"], resume=True,
                            open_browser=False, wait_seconds=0, http_factory=server.factory)
    assert code == 0
    assert sum(c[0] == "POST" for c in server.calls) == 2


@pytest.mark.parametrize("revoked", [False, True])
def test_pairing_redeem_unknown_recovery_checks_current_grant(tmp_path, revoked):
    state, server = State(tmp_path / "private"), PairingServer()
    server.lose_redeem = True
    result, code = auth.bind(state, server=SERVER, open_browser=False, wait_seconds=1,
                            sleep=lambda _: None, http_factory=server.factory)
    assert code == 4
    server.revoked = revoked
    before = len(server.calls)
    result, code = auth.reconcile(State(state.directory), result["request_id"], http_factory=server.factory)
    assert all(call[0] == "GET" for call in server.calls[before:])
    assert code == (4 if revoked else 0)
    assert result["profile_saved"] is (not revoked)


def test_profile_never_overwrites_server_client_or_actor(state):
    original = state.safe_profiles()
    with pytest.raises(CLIError, match="PROFILE_IDENTITY_CONFLICT"):
        state.save_profile("default", SERVER, str(uuid.uuid4()), ACTOR, {})
    assert state.safe_profiles() == original


def test_explicit_skill_installer_preserves_user_modifications(state, tmp_path):
    result, code = skills.install(state, directory=tmp_path / "skills", globally=False, host=None)
    assert code == 0 and result["implicit_invocation"] is False
    destination = Path(result["directory"])
    (destination / "SKILL.md").write_text("custom user instructions")
    with pytest.raises(CLIError, match="SKILL_CUSTOMIZATION_CONFLICT"):
        skills.install(state, directory=tmp_path / "skills", globally=False, host=None)
    assert (destination / "SKILL.md").read_text() == "custom user instructions"


def test_https_and_route_boundary():
    for value in ("http://hypertest.example", "https://user:pass@host", "https://host/path", "https://host?token=x"):
        with pytest.raises(CLIError):
            server_url(value)
    transport = HTTP(SERVER)
    with pytest.raises(CLIError, match="API_ROUTE_REJECTED"):
        transport.call("POST", "/api/v1/cloud/tasks")


def test_preview_and_not_found_recovery_never_post(state, tmp_path):
    server = ArchiveServer()
    args = dict(profile_name=None, project_id=P, task_id=T, subtask_id=None,
                manifest=manifest(tmp_path), http_factory=server.factory)
    result, code = archive.archive(state, **args, dry_run=True)
    assert code == 0 and result["status"] == "PREVIEW" and not result["readback_complete"]
    assert not list(state.requests.glob("*.json"))
    assert all(call[0] == "GET" for call in server.calls)
    server.lose_post = True
    result, _ = archive.archive(state, **args)
    original = server.call

    def not_found(method, path, **kwargs):
        if path.endswith("/by-key"):
            server.calls.append((method, path, None, None))
            raise CLIError("ARCHIVE_SUBMISSION_NOT_FOUND", 3, status=404)
        return original(method, path, **kwargs)

    server.call = not_found
    before = len(server.calls)
    result, code = archive.status(state, result["request_id"], remote=True, http_factory=server.factory)
    assert code == 4 and result["status"] == "UNKNOWN"
    assert all(call[0] == "GET" for call in server.calls[before:])


def test_tampered_pairing_receipt_cannot_persist_profile(tmp_path):
    state, server = State(tmp_path / "private"), PairingServer()
    original = server.receipt

    def wrong_digest(phase, body):
        result = original(phase, body)
        result["request_digest"] = "0" * 64
        return result

    server.receipt = wrong_digest
    result, code = auth.bind(state, server=SERVER, open_browser=False, wait_seconds=0,
                            http_factory=server.factory)
    assert code == 4 and result["code"] == "PAIRING_RECEIPT_MISMATCH"
    assert not list(state.profiles.glob("*.json"))
    assert len([c for c in server.calls if c[0] == "POST"]) == 1


def test_lightweight_release_fixture_installs_bundled_skill_and_preserves_modified_command(tmp_path, monkeypatch):
    import importlib.util
    import os
    import subprocess
    import sys
    import zipfile

    repository = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("cli_release_builder", repository / "scripts/build-cli-release.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    # Synthetic build identity only: these fixture artifacts are never published.
    monkeypatch.setattr(builder, "run_git", lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    output = tmp_path / "release"
    monkeypatch.setattr(sys, "argv", ["build-cli-release.py", "--source-sha", "a" * 40,
                                      "--version", "0.1.0", "--output-dir", str(output)])
    builder.main()
    artifact = output / "hypertest-cli-0.1.0.pyz"
    release = json.loads((output / "hypertest-cli-0.1.0.manifest.json").read_text())
    with zipfile.ZipFile(artifact) as bundle:
        assert not any(name.endswith(("mcp_server.py", "hooks.py", "ipc.py")) for name in bundle.namelist())
        assert "hypertest/cli/assets/skills/hypertest-archive/SKILL.md" in bundle.namelist()
    command = [sys.executable, str(repository / "scripts/install-cli-release.py"), "--artifact", str(artifact),
               "--sha256", release["sha256"], "--version", "0.1.0", "--bin-dir", str(tmp_path / "bin"),
               "--install-dir", str(tmp_path / "installed")]
    installed = subprocess.run(command, capture_output=True, text=True)
    assert installed.returncode == 0, installed.stderr
    cli = tmp_path / "bin/hypertest"
    assert subprocess.check_output([str(cli), "--version"], text=True).strip() == "hypertest 0.1.0"
    result = subprocess.run([str(cli), "skill", "install", "--directory", str(tmp_path / "skills"), "--json"],
        env={**os.environ, "HYPERTEST_CLI_HOME": str(tmp_path / "cli-state")}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (tmp_path / "skills/hypertest-archive/agents/openai.yaml").is_file()
    cli.write_text("user customization")
    refused = subprocess.run(command, capture_output=True, text=True)
    assert refused.returncode != 0 and cli.read_text() == "user customization"


def test_binding_different_approved_actor_preserves_existing_profile(state):
    before = state.safe_profiles()
    server = PairingServer()
    original = server.call

    def other_actor(method, path, **kwargs):
        value = original(method, path, **kwargs)
        if server.view and server.view.get("approval"):
            server.view["approval"]["actor_ref"] = "interactive:" + "00000000-0000-4000-8000-000000000099"
        if value.get("approval"):
            value["approval"]["actor_ref"] = server.view["approval"]["actor_ref"]
        return value

    server.call = other_actor
    result, code = auth.bind(state, server=SERVER, open_browser=False, wait_seconds=1,
                            sleep=lambda _: None, http_factory=server.factory)
    assert code == 5 and result["code"] == "PROFILE_IDENTITY_CONFLICT"
    assert state.safe_profiles() == before
