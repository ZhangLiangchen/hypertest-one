"""The integrated Cloud schema must extend, never fork, Local management history."""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_cloud_migrations_have_one_head_after_local_binding_without_historical_number_collision():
    root = Path(__file__).resolve().parents[1]
    config = Config()
    config.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0028_cloud_http_operations"]
    assert scripts.get_revision("0028_cloud_http_operations").down_revision == "0027_project_memory"
    assert scripts.get_revision("0027_project_memory").down_revision == "0026_cloud_ssh_operations"
    assert scripts.get_revision("0026_cloud_ssh_operations").down_revision == "0025_cloud_tasks"
    assert scripts.get_revision("0025_cloud_tasks").down_revision == "0024_local_task_binding"
    assert scripts.get_revision("0024_local_task_binding").down_revision == "0023_project_task_management"
    assert scripts.get_revision("0023_project_task_management").down_revision == "0022_session_task_sync"
    revisions = [row.revision for row in scripts.walk_revisions()]
    assert len(revisions) == len(set(revisions))
    assert "0023_cloud_tasks" not in revisions and "0024_cloud_ssh_operations" not in revisions
