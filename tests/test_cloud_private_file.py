"""Descriptor reads and exact standard systemd credential ACL acceptance."""

import os
import stat
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest.cloud import private_file
from hypertest.cloud.errors import CloudBlocked

UNDEFINED = 0xFFFFFFFF


def acl(uid, permission, *, group=0, extra=()):
    entries = [(1, permission, UNDEFINED), (2, permission, uid), (4, group, UNDEFINED),
        (16, permission, UNDEFINED), (32, 0, UNDEFINED), *extra]
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *item) for item in entries)


@pytest.mark.parametrize("mode", [0o400, 0o600])
def test_ordinary_private_files_keep_owner_only_modes(tmp_path, mode):
    path = tmp_path / "identity"
    path.write_bytes(b"fixture-private-input")
    os.chmod(path, mode)
    assert private_file.read_private_file(path, max_bytes=128) == b"fixture-private-input"


@pytest.mark.parametrize("mode", [0o440, 0o640, 0o644, 0o700, 0o4600])
def test_group_read_or_executable_ordinary_file_never_gets_systemd_exception(tmp_path, mode):
    path = tmp_path / "identity"
    path.write_bytes(b"fixture")
    os.chmod(path, mode)
    with pytest.raises(CloudBlocked) as error:
        private_file.read_private_file(path, max_bytes=128)
    assert error.value.code == "PRIVATE_FILE_UNSAFE"


def test_symlink_hardlink_and_oversize_files_are_rejected(tmp_path):
    path = tmp_path / "identity"
    path.write_bytes(b"fixture-private-input")
    os.chmod(path, 0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(CloudBlocked):
        private_file.read_private_file(alias, max_bytes=128)
    alias.unlink()
    os.link(path, alias)
    with pytest.raises(CloudBlocked):
        private_file.read_private_file(path, max_bytes=128)
    alias.unlink()
    with pytest.raises(CloudBlocked) as error:
        private_file.read_private_file(path, max_bytes=4)
    assert error.value.code == "PRIVATE_FILE_SIZE"


def test_symlink_parent_is_not_followed(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    path = actual / "identity"
    path.write_bytes(b"fixture")
    os.chmod(path, 0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(CloudBlocked):
        private_file.read_private_file(alias / "identity", max_bytes=128)


@pytest.fixture
def systemd_input(tmp_path, monkeypatch):
    unit = tmp_path / "credentials"
    unit.mkdir()
    leaf = unit / "identity"
    leaf.write_bytes(b"fixture-systemd-identity")
    os.chmod(leaf, 0o440)
    os.chmod(unit, 0o550)
    apparent = Path("/run/credentials/fixture.service/identity")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(apparent.parent))
    # Replace only this module's OS view; never patch global os.fstat/geteuid
    # used by pytest or another concurrent module.
    private_os = SimpleNamespace(**vars(os))
    monkeypatch.setattr(private_file, "os", private_os)
    monkeypatch.setattr(private_file, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(private_os, "geteuid", lambda: 997)
    original_stat = os.fstat

    def root_owned_stat(descriptor):
        fields = list(original_stat(descriptor))
        fields[4], fields[5] = 0, 0
        return os.stat_result(fields)

    monkeypatch.setattr(private_os, "fstat", root_owned_stat)
    monkeypatch.setattr(private_file, "_open_parent", lambda _: os.open(unit, os.O_RDONLY | os.O_DIRECTORY))
    monkeypatch.setattr(private_os, "fstatvfs", lambda _: SimpleNamespace(f_flag=os.ST_RDONLY))

    def exact_getxattr(descriptor, name):
        assert name == "system.posix_acl_access"
        return acl(997, 5 if stat.S_ISDIR(original_stat(descriptor).st_mode) else 4)

    monkeypatch.setattr(private_os, "getxattr", exact_getxattr)
    try:
        yield apparent, unit, leaf, original_stat
    finally:
        os.chmod(unit, 0o700)


def test_exact_readonly_systemd_acl_accepts_only_current_service_uid(systemd_input):
    apparent, _, _, _ = systemd_input
    assert private_file.read_private_file(apparent, max_bytes=128) == b"fixture-systemd-identity"


@pytest.mark.parametrize("condition", ["root_group", "extra_user", "named_group", "missing_acl",
    "unknown_tag", "duplicate", "writable_mount", "wrong_unit", "missing_expected_directory",
    "root_caller", "hardlink"])
def test_systemd_exceptions_fail_closed_on_ambiguous_authority(systemd_input, monkeypatch, condition):
    apparent, unit, leaf, original_stat = systemd_input
    if condition == "writable_mount":
        monkeypatch.setattr(private_file.os, "fstatvfs", lambda _: SimpleNamespace(f_flag=0))
    elif condition == "wrong_unit":
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", "/run/credentials/other.service")
    elif condition == "missing_expected_directory":
        monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    elif condition == "root_caller":
        monkeypatch.setattr(private_file.os, "geteuid", lambda: 0)
    elif condition == "hardlink":
        os.chmod(unit, 0o750)
        os.link(leaf, unit / "second-name")
        os.chmod(unit, 0o550)
    else:
        def hostile_acl(descriptor, _):
            permission = 5 if stat.S_ISDIR(original_stat(descriptor).st_mode) else 4
            if condition == "missing_acl":
                raise OSError("not returned to caller")
            if condition == "root_group":
                return acl(997, permission, group=permission)
            extra = {"extra_user": (2, permission, 998), "named_group": (8, permission, 988),
                "unknown_tag": (64, permission, UNDEFINED), "duplicate": (2, permission, 997)}[condition]
            return acl(997, permission, extra=(extra,))

        monkeypatch.setattr(private_file.os, "getxattr", hostile_acl)
    with pytest.raises(CloudBlocked) as error:
        private_file.read_private_file(apparent, max_bytes=128)
    assert "not returned to caller" not in str(error.value)


def test_same_mode_with_foreign_uid_acl_is_rejected(systemd_input, monkeypatch):
    apparent, _, _, original_stat = systemd_input
    monkeypatch.setattr(private_file.os, "getxattr", lambda descriptor, _:
        acl(998, 5 if stat.S_ISDIR(original_stat(descriptor).st_mode) else 4))
    with pytest.raises(CloudBlocked):
        private_file.read_private_file(apparent, max_bytes=128)
