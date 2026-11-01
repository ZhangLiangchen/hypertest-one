"""Dedicated cloud profile projection; no personal home or real credentials."""
from pathlib import Path

import pytest

from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.native_profile import snapshot_sdk_profile


def test_snapshots_only_sdk_profile_and_internal_package_links(tmp_path):
    cloud = tmp_path / "cloud-harness"
    sdk = cloud / "profiles" / "sdk"
    package = sdk / "node_modules" / ".pnpm" / "fixture"
    package.mkdir(parents=True)
    (package / "index.js").write_text("fixture")
    (sdk / "node_modules" / "fixture").symlink_to(".pnpm/fixture", target_is_directory=True)
    (sdk / "cordis.patch.yml").write_text("[]")
    (cloud / ".credentials.yaml").write_text("private credential sentinel")
    (cloud / "sessions").mkdir()
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    snapshot_sdk_profile(cloud_home=str(cloud), attempt_home=attempt)
    copied = attempt / "dsh" / "profiles" / "sdk"
    assert (copied / "node_modules" / "fixture" / "index.js").read_text() == "fixture"
    assert (copied / "node_modules" / "fixture").is_symlink()
    assert not (attempt / "dsh" / ".credentials.yaml").exists()
    assert not (attempt / "dsh" / "sessions").exists()


def test_profile_symlink_cannot_import_external_files(tmp_path):
    cloud = tmp_path / "cloud-harness"
    sdk = cloud / "profiles" / "sdk"
    sdk.mkdir(parents=True)
    private = tmp_path / "private"
    private.write_text("private")
    (sdk / "outside").symlink_to(Path("../../../private"))
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    with pytest.raises(CloudBlocked):
        snapshot_sdk_profile(cloud_home=str(cloud), attempt_home=attempt)
    assert not (attempt / "dsh").exists()
