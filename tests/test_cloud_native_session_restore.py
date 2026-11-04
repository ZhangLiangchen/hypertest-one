from pathlib import Path

import pytest
import yaml

from hypertest.cloud import native_session_restore as restore
from hypertest.cloud.errors import CloudBlocked


def _overlay(directory, *, title):
    (directory / "hypertest-cordis-root.mjs").write_text(restore._HOOK)
    path = directory / "overlay.yml"
    path.write_text("- id: example\n")
    return path


def test_inspection_overlay_disables_execution_and_redirects_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(restore, "prepare_cordis_overlay", _overlay)
    path = restore._prepare_inspection_overlay(tmp_path)
    rows = yaml.safe_load(path.read_text())
    disabled = {r["id"] for r in rows if r.get("disabled") is True}
    assert set(restore._DISABLED_FOR_INSPECTION) <= disabled
    creds = next(r["config"] for r in rows if r["id"] == "credentials")
    assert Path(creds["path"]).parent == tmp_path
    assert Path(creds["path"]).read_text() == "{}\n"
    assert Path(creds["path"]).stat().st_mode & 0o777 == 0o600
    assert creds["watch"] is False
    hook = (tmp_path / "hypertest-cordis-root.mjs").read_text()
    assert hook.index("return; // retain the original persisted preset") < hook.index('await ctx.agentPresets.select')
    assert hook.index("return; // retain the original persisted preset") < hook.index('ctx.sessionTitle.rename')



def test_all_sync_inspection_entry_points_refuse_before_starting_sdk(tmp_path, monkeypatch):
    def reject_open(*args, **kwargs):
        pytest.fail("inspection must not open the original session")

    monkeypatch.setattr(restore.os, "open", reject_open)
    for inspect in (restore._inspect_in_child, restore.inspect_original_session):
        with pytest.raises(CloudBlocked) as error:
            inspect(attempt_root=tmp_path, expected_identity_digest="a" * 64, identity={})
        assert error.value.code == "NATIVE_SESSION_RESTORE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_guarded_inspection_refuses_before_starting_sdk(tmp_path, monkeypatch):
    def reject_open(*args, **kwargs):
        pytest.fail("inspection must not open the original session")

    async def reject_authority():
        pytest.fail("disabled inspection must not request authority")

    monkeypatch.setattr(restore.os, "open", reject_open)
    with pytest.raises(CloudBlocked) as error:
        await restore.inspect_original_session_guarded(attempt_root=tmp_path,
            expected_identity_digest="a" * 64, identity={}, assert_active=reject_authority)
    assert error.value.code == "NATIVE_SESSION_RESTORE_UNAVAILABLE"
