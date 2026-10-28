"""Cutover refuses new Local sync writes while preserving accepted original keys."""
import sys
from pathlib import Path

import pytest

from hypertest.local_sync.__main__ import hook, main


async def test_retired_hook_does_not_read_configuration_or_connect():
    assert await hook(Path("/does-not-exist/private.json")) == {"status": "IGNORED", "code": "LOCAL_SYNC_RETIRED"}


def test_retired_command_does_not_direct_users_to_removed_recovery(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hypertest-local", "drain-source", "--config", "/missing", "--session-id", "old"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 3
    message = capsys.readouterr().err
    assert "recovery is unavailable" in message and "do not replay" in message
    assert "legacy reconcile" not in message
