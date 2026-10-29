"""Original Docker recovery authority stays private and cannot be recreated."""

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from hypertest.cloud import container_recovery as recovery
from hypertest.cloud.errors import CloudBlocked


@pytest.fixture
def private_root(tmp_path):
    root = tmp_path.resolve() / "private"
    root.mkdir(mode=0o700)
    return root


@pytest.fixture
def identity():
    return recovery.RecoveryIdentity(project_id=str(uuid4()), task_id=str(uuid4()), attempt_id=str(uuid4()),
        create_key="create:original-1", generation=1, worker_id="cloud-worker-original")


def test_original_capability_round_trip_and_nonsecret_projection(private_root, identity):
    first = recovery.create_recovery_capability(private_root, identity)
    path = private_root / "container-recovery.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(first.secret) == 32 and len(first.sha256) == 64
    assert first.secret.hex() not in repr(first)
    assert base64.b64encode(first.secret).decode() not in repr(first)
    again = recovery.load_recovery_capability(private_root, identity, first.sha256)
    assert again.identity == identity and again.secret == first.secret and again.sha256 == first.sha256


def test_new_process_reopens_original_capability_without_outputting_secret(private_root, identity):
    first = recovery.create_recovery_capability(private_root, identity)
    script = (
        "import json,sys; from hypertest.cloud.container_recovery import RecoveryIdentity,load_recovery_capability; "
        "identity=RecoveryIdentity(**json.loads(sys.argv[2])); "
        "cap=load_recovery_capability(sys.argv[1],identity,sys.argv[3]); "
        "print('RECOVERED' if cap.sha256==sys.argv[3] else 'INVALID')"
    )
    identity_fields = {key: value for key, value in identity.document().items() if key != "profile"}
    completed = subprocess.run([sys.executable, "-c", script, str(private_root), json.dumps(identity_fields), first.sha256],
        env={"PATH": os.defpath}, text=True, capture_output=True, timeout=10, check=True)
    assert completed.stdout == "RECOVERED\n" and completed.stderr == ""


def test_existing_file_is_never_replaced_or_removed(private_root, identity):
    first = recovery.create_recovery_capability(private_root, identity)
    path = private_root / "container-recovery.json"
    before = path.read_bytes()
    with pytest.raises(CloudBlocked) as error:
        recovery.create_recovery_capability(private_root, identity)
    assert error.value.code == "CONTAINER_RECOVERY_EXISTS"
    assert path.read_bytes() == before
    assert recovery.load_recovery_capability(private_root, identity, first.sha256).secret == first.secret


@pytest.mark.parametrize("change", [
    {"project_id": str(uuid4())}, {"task_id": str(uuid4())}, {"attempt_id": str(uuid4())},
    {"worker_id": "different-worker"}, {"create_key": "create:different"}, {"generation": 2},
])
def test_original_identity_and_digest_must_match(private_root, identity, change):
    cap = recovery.create_recovery_capability(private_root, identity)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, replace(identity, **change), cap.sha256)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, "0" * 64)


@pytest.mark.parametrize("change", [
    {"project_id": "../other"}, {"task_id": ""}, {"attempt_id": "NOT-A-UUID"},
    {"worker_id": "../worker"}, {"create_key": "\n"}, {"generation": True}, {"generation": 0},
])
def test_invalid_identity_is_rejected_before_file_creation(private_root, identity, change):
    with pytest.raises(CloudBlocked):
        recovery.create_recovery_capability(private_root, replace(identity, **change))
    assert not (private_root / "container-recovery.json").exists()


@pytest.mark.parametrize("fault", ["extra", "duplicate", "bad_secret", "bool_generation"])
def test_tampered_or_noncanonical_document_is_rejected(private_root, identity, fault):
    cap = recovery.create_recovery_capability(private_root, identity)
    path = private_root / "container-recovery.json"
    data = json.loads(path.read_bytes())
    if fault == "extra":
        data["extra"] = "untrusted"
        raw = json.dumps(data)
    elif fault == "duplicate":
        raw = json.dumps(data)[:-1] + ',"profile":"' + recovery.PROFILE + '"}'
    elif fault == "bad_secret":
        data["secret_base64"] = "AAAA"
        raw = json.dumps(data)
    else:
        data["generation"] = True
        raw = json.dumps(data)
    path.write_text(raw)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)


def test_private_root_file_mode_and_aliases_are_required(private_root, identity, tmp_path):
    cap = recovery.create_recovery_capability(private_root, identity)
    path = private_root / "container-recovery.json"
    private_root.chmod(0o755)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)
    private_root.chmod(0o700)
    path.chmod(0o644)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)
    path.chmod(0o600)
    os.link(path, tmp_path / "alias")
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)


def test_symlink_root_or_file_is_rejected(private_root, identity, tmp_path):
    cap = recovery.create_recovery_capability(private_root, identity)
    link = tmp_path.resolve() / "linked-root"
    link.symlink_to(private_root, target_is_directory=True)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(link, identity, cap.sha256)
    path = private_root / "container-recovery.json"
    path.rename(private_root / "original")
    path.symlink_to(private_root / "original")
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)


def test_read_rejects_file_changed_during_inspection(monkeypatch, private_root, identity):
    cap = recovery.create_recovery_capability(private_root, identity)
    path = private_root / "container-recovery.json"
    read = recovery.os.read

    def changed_read(fd, length):
        data = read(fd, length)
        path.write_bytes(data + b" ")
        return data

    monkeypatch.setattr(recovery.os, "read", changed_read)
    with pytest.raises(CloudBlocked):
        recovery.load_recovery_capability(private_root, identity, cap.sha256)


def test_fsync_failure_keeps_unknown_partial_file_and_blocks_recreation(monkeypatch, private_root, identity):
    monkeypatch.setattr(recovery.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(CloudBlocked):
        recovery.create_recovery_capability(private_root, identity)
    assert (private_root / "container-recovery.json").exists()
    with pytest.raises(CloudBlocked) as error:
        recovery.create_recovery_capability(private_root, identity)
    assert error.value.code == "CONTAINER_RECOVERY_EXISTS"


def test_concurrent_creation_allows_one_original_only(private_root, identity):
    def create_once():
        try:
            return recovery.create_recovery_capability(private_root, identity)
        except CloudBlocked as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: create_once(), range(4)))
    successes = [item for item in outcomes if isinstance(item, recovery.RecoveryCapability)]
    assert len(successes) == 1 and outcomes.count("CONTAINER_RECOVERY_EXISTS") == 3
    assert recovery.load_recovery_capability(private_root, identity, successes[0].sha256) == successes[0]
