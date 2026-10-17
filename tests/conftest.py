"""Keep test workspaces and artifacts independent of operator runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# Select an explicitly provisioned test database before test modules import the
# application's engine. CI can continue to provide its disposable DATABASE_URL.
test_database_url = os.environ.get("HYPERTEST_TEST_DATABASE_URL") or dotenv_values(
    REPOSITORY_ROOT / ".env"
).get("HYPERTEST_TEST_DATABASE_URL")
if test_database_url:
    os.environ["HYPERTEST_DATABASE_URL"] = test_database_url

from hypertest.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "workspace_root", str(REPOSITORY_ROOT))
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
