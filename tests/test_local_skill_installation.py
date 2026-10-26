"""Guide installation owns only the five explicitly selected skill files."""
import hashlib
import json
import sys

import pytest

from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_directory
from hypertest.local_sync import installer, skills


@pytest.fixture
def skill_install(tmp_path, monkeypatch):
    files = {name: ("Original guide: " + name + "\n").encode() for name in skills.SKILL_FILES}
    monkeypatch.setattr(skills, "bundled_skill", lambda: dict(files))
    return {"directory": tmp_path / "private-install", "skills_directory": tmp_path / "selected-skills"}, files


def test_resource_loader_reads_only_five_bundled_files_and_reports_missing_asset(tmp_path, monkeypatch):
    package = tmp_path / "local-sync"
    root = package / "assets" / "skills" / skills.SKILL_NAME
    expected = {}
    for name in skills.SKILL_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        expected[name] = ("Packaged: " + name).encode()
        path.write_bytes(expected[name])
    (root / "unrelated.md").write_bytes(b"must not export")
    monkeypatch.setattr(skills.resources, "files", lambda name: package)
    assert skills.bundled_skill() == expected
    (root / "SKILL.md").unlink()
    with pytest.raises(ClientError, match="LOCAL_BUNDLED_SKILL_MISSING"):
        skills.bundled_skill()


def test_install_is_explicit_idempotent_and_preserves_unrelated_state(skill_install, tmp_path):
    args, files = skill_install
    state = tmp_path / "client.sqlite3"
    state.write_bytes(b"pending UNKNOWN original key")
    other = args["skills_directory"] / "other-skill" / "SKILL.md"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"user owned")
    result = skills.install_skill(**args)
    target = args["skills_directory"] / skills.SKILL_NAME
    for name, content in files.items():
        assert (target / name).read_bytes() == content
    receipt_file = next(args["directory"].glob("installed-skill-*.json"))
    receipt = json.loads(receipt_file.read_bytes())
    assert receipt["skill_directory"] == str(target)
    assert receipt["files"] == {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    assert receipt_file.stat().st_mode & 0o077 == 0
    assert args["directory"].stat().st_mode & 0o077 == 0
    transactions = list((args["directory"] / "backups").iterdir())
    assert result["configuration"] == "WRITTEN"
    assert skills.install_skill(**args)["configuration"] == "UNCHANGED"
    assert list((args["directory"] / "backups").iterdir()) == transactions
    assert other.read_bytes() == b"user owned" and state.read_bytes() == b"pending UNKNOWN original key"


def test_owned_upgrade_changes_only_recorded_files(skill_install):
    args, files = skill_install
    skills.install_skill(**args)
    target = args["skills_directory"] / skills.SKILL_NAME
    extra = target / "user-notes.md"
    extra.write_bytes(b"Keep my notes")
    files["references/setup.md"] = b"Updated fixed guide\n"
    result = skills.install_skill(**args)
    assert result["configuration"] == "WRITTEN"
    assert (target / "references/setup.md").read_bytes() == b"Updated fixed guide\n"
    assert extra.read_bytes() == b"Keep my notes"


@pytest.mark.parametrize("removed", [False, True])
def test_user_edits_or_deleted_owned_file_block_upgrade_without_overwriting(skill_install, removed):
    args, files = skill_install
    result = skills.install_skill(**args)
    target = args["skills_directory"] / skills.SKILL_NAME
    edited = target / "references/setup.md"
    if removed:
        edited.unlink()
    else:
        edited.write_bytes(b"user revision")
    receipt = (args["directory"] / result["receipt_file"]).read_bytes()
    files["SKILL.md"] = b"New bundle"
    with pytest.raises(ClientError, match="MANAGED_SKILL_CHANGED"):
        skills.install_skill(**args)
    assert (target / "SKILL.md").read_bytes() == b"Original guide: SKILL.md\n"
    if removed:
        assert not edited.exists()
    else:
        assert edited.read_bytes() == b"user revision"
    assert (args["directory"] / result["receipt_file"]).read_bytes() == receipt


def test_unowned_same_name_skill_is_not_adopted_even_if_bytes_match(skill_install):
    args, files = skill_install
    target = args["skills_directory"] / skills.SKILL_NAME
    target.mkdir(parents=True)
    (target / "SKILL.md").write_bytes(files["SKILL.md"])
    with pytest.raises(ClientError, match="INSTALL_UNOWNED_SKILL_CONFLICT"):
        skills.install_skill(**args)
    assert (target / "SKILL.md").read_bytes() == files["SKILL.md"]
    assert not list(args["directory"].glob("installed-skill-*.json"))


@pytest.mark.parametrize("placement", ["skills-ancestor", "receipt-ancestor", "target", "resource-parent", "resource"])
def test_symlink_paths_are_rejected_and_outside_files_preserved(skill_install, tmp_path, placement):
    args, _ = skill_install
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "SKILL.md"
    sentinel.write_bytes(b"outside user guide")
    target = args["skills_directory"] / skills.SKILL_NAME
    if placement == "skills-ancestor":
        args["skills_directory"].symlink_to(outside, target_is_directory=True)
    elif placement == "receipt-ancestor":
        link = tmp_path / "receipt-link"
        link.symlink_to(outside, target_is_directory=True)
        args["directory"] = link / "private-install"
    elif placement == "target":
        target.parent.mkdir()
        target.symlink_to(outside, target_is_directory=True)
    else:
        skills.install_skill(**args)
        if placement == "resource-parent":
            for path in (target / "references").iterdir():
                path.unlink()
            (target / "references").rmdir()
            (target / "references").symlink_to(outside, target_is_directory=True)
        else:
            (target / "SKILL.md").unlink()
            (target / "SKILL.md").symlink_to(sentinel)
    with pytest.raises(ClientError, match="INSTALL_SYMLINK_REJECTED"):
        skills.install_skill(**args)
    assert sentinel.read_bytes() == b"outside user guide"


@pytest.mark.parametrize("upgrade", [False, True])
def test_transaction_failure_rolls_back_files_and_receipt_and_allows_retry(skill_install, monkeypatch, upgrade):
    args, files = skill_install
    if upgrade:
        skills.install_skill(**args)
        original_receipt = next(args["directory"].glob("installed-skill-*.json")).read_bytes()
        old_files = dict(files)
        for name in files:
            files[name] = b"upgraded: " + files[name]
    original = installer.atomic_write
    count = 0

    def fail_second(path, data):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("injected disk failure")
        return original(path, data)

    monkeypatch.setattr(installer, "atomic_write", fail_second)
    with pytest.raises(OSError, match="injected disk failure"):
        skills.install_skill(**args)
    target = args["skills_directory"] / skills.SKILL_NAME
    if upgrade:
        assert {name: (target / name).read_bytes() for name in files} == old_files
        assert next(args["directory"].glob("installed-skill-*.json")).read_bytes() == original_receipt
    else:
        assert not any((target / name).exists() for name in files)
        assert not list(args["directory"].glob("installed-skill-*.json"))
    assert installer.recover_install(directory=args["directory"])["configuration"] == "NO_PENDING_TRANSACTION"
    assert skills.install_skill(**args)["configuration"] == "WRITTEN"


def test_interrupted_skill_transaction_uses_existing_recover_install(skill_install):
    args, _ = skill_install
    skills.install_skill(**args)
    target = args["skills_directory"] / skills.SKILL_NAME / "SKILL.md"
    before, after = target.read_bytes(), b"interrupted replacement"
    transaction = private_directory(args["directory"] / "backups" / "interrupted")
    private_create(transaction / "0.before", before)
    private_create(transaction / "transaction.json", json.dumps({"changes": [{"path": str(target),
        "existed": True, "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest()}]}).encode())
    target.write_bytes(after)
    with pytest.raises(ClientError, match="INSTALL_RECOVERY_REQUIRED"):
        skills.install_skill(**args)
    assert installer.recover_install(directory=args["directory"])["transactions"] == 1
    assert target.read_bytes() == before
    assert skills.install_skill(**args)["configuration"] == "UNCHANGED"


def test_cli_requires_explicit_skills_directory_without_creating_default(skill_install, monkeypatch, tmp_path):
    from hypertest.local_sync.__main__ import main

    args, _ = skill_install
    monkeypatch.setenv("HOME", str(tmp_path / "unused-home"))
    monkeypatch.setattr(sys, "argv", ["hypertest-local", "install-skill", "--directory", str(args["directory"])])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not args["directory"].exists() and not (tmp_path / "unused-home").exists()
    monkeypatch.setattr(sys, "argv", ["hypertest-local", "install-skill", "--directory", str(args["directory"]),
                                     "--skills-directory", str(args["skills_directory"])])
    main()
    assert (args["skills_directory"] / skills.SKILL_NAME / "SKILL.md").exists()
    assert not (tmp_path / "unused-home").exists()
