"""Canonical source review reads platform artifacts without invoking the Harness."""

import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from test_test_design import create_run

from hypertest.api.schemas import TestRunCreate as RunCreate
from hypertest.application.services import create_test_run
from hypertest.common.ids import public_key, uuid7
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.models import SourceSnapshot
from hypertest.domain.models import TestImplementation as Implementation
from hypertest.main import app
from hypertest.runner.artifacts import artifact_root, store_content


async def saved_implementation(session, run, content: bytes | None):
    snapshot = await session.get(SourceSnapshot, run.source_snapshot_id)
    digest, uri = store_content(content) if content is not None else (None, None)
    item = Implementation(
        key=public_key("IMP"), project_id=run.project_id, source_snapshot_id=run.source_snapshot_id,
        repository_url=snapshot.repository_url, commit_sha=snapshot.commit_sha,
        file_path="tests/test_saved.py", symbol="test_saved", framework="pytest", language="python",
        implementation_fingerprint=hashlib.sha256(str(uuid7()).encode()).hexdigest(),
        artifact_uri=uri, source_sha256=digest, created_by_type="USER",
    )
    session.add(item)
    await session.commit()
    return item


@pytest.mark.asyncio
async def test_review_source_is_exact_verified_plaintext_and_available_to_same_snapshot_run():
    content = '# 真实测试源码 <script>not executable</script>\n\ndef test_saved():\n    assert "中文"\n'.encode()
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        item = await saved_implementation(session, run, content)
        another_round = await create_test_run(session, RunCreate(
            project_id=run.project_id, source_snapshot_id=run.source_snapshot_id,
            policy_snapshot_id=run.policy_snapshot_id,
        ))
        run_ids, item_id, digest = [run.id, another_round.id], item.id, item.source_sha256
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for run_id in run_ids:
            response = await client.get(f"/api/v1/test-runs/{run_id}/implementations/{item_id}/content")
            assert response.status_code == 200, response.text
            assert response.content == content
            assert response.headers["content-type"].startswith("text/plain")
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-sha256"] == digest
            assert int(response.headers["content-length"]) == len(content)


@pytest.mark.asyncio
async def test_review_source_cannot_cross_project_or_source_snapshot():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        item = await saved_implementation(session, run, b"PRIVATE_TEST_SOURCE")
        another_project = await create_run(session)
        another_snapshot = await create_run(session, project_id=run.project_id)
        denied_run_ids = [another_project.id, another_snapshot.id, uuid7()]
        run_id, item_id = run.id, item.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for denied_run_id in denied_run_ids:
            response = await client.get(f"/api/v1/test-runs/{denied_run_id}/implementations/{item_id}/content")
            assert response.status_code == 404
            assert "PRIVATE_TEST_SOURCE" not in response.text
        assert (await client.get(f"/api/v1/test-runs/{run_id}/implementations/{uuid7()}/content")).status_code == 404


@pytest.mark.asyncio
async def test_tracked_implementation_does_not_read_a_checkout_or_provider_workspace():
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        item = await saved_implementation(session, run, None)
        run_id, item_id = run.id, item.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/test-runs/{run_id}/implementations/{item_id}/content")
        assert response.status_code == 409
        assert response.json()["detail"] == "implementation source belongs to the pinned repository"


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "tampered", "symlink-inside", "symlink-outside", "symlink-loop", "non-utf8"])
async def test_review_source_rejects_missing_corrupt_symlink_or_non_text_artifacts(tmp_path: Path, damage):
    content = b"\xff\xfe" if damage == "non-utf8" else b"def test_saved():\n    assert True\n"
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        item = await saved_implementation(session, run, content)
        run_id, item_id, digest = run.id, item.id, item.source_sha256
    path = artifact_root() / "sha256" / digest[:2] / digest
    if damage == "tampered":
        path.chmod(0o600)
        path.write_bytes(b"CORRUPTED_SOURCE_MUST_NOT_BE_RETURNED")
    elif damage == "symlink-loop":
        path.unlink()
        path.symlink_to(path)
    elif damage in {"symlink-inside", "symlink-outside"}:
        destination = artifact_root() / "moved" if damage == "symlink-inside" else tmp_path / "PRIVATE_OUTSIDE"
        destination.write_bytes(content)
        path.unlink()
        path.symlink_to(destination)
    elif damage == "missing":
        path.unlink()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/test-runs/{run_id}/implementations/{item_id}/content")
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "implementation artifact unavailable or checksum mismatch"
        assert "CORRUPTED_" not in response.text and "PRIVATE_OUTSIDE" not in response.text


@pytest.mark.asyncio
async def test_review_source_uses_existing_root_confined_legacy_artifact_reader(tmp_path: Path):
    content = b"# legacy generated source\ndef test_saved():\n    assert True\n"
    inside = artifact_root() / "legacy-generated.py"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(content)
    outside = tmp_path / "PRIVATE_SOURCE.py"
    outside.write_bytes(content)
    async with AsyncSessionLocal() as session:
        run = await create_run(session)
        accepted = await saved_implementation(session, run, None)
        accepted.artifact_uri, accepted.source_sha256 = str(inside), hashlib.sha256(content).hexdigest()
        blocked = await saved_implementation(session, run, None)
        blocked.artifact_uri, blocked.source_sha256 = outside.as_uri(), hashlib.sha256(content).hexdigest()
        await session.commit()
        run_id, accepted_id, blocked_id = run.id, accepted.id, blocked.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        good = await client.get(f"/api/v1/test-runs/{run_id}/implementations/{accepted_id}/content")
        assert good.status_code == 200 and good.content == content
        bad = await client.get(f"/api/v1/test-runs/{run_id}/implementations/{blocked_id}/content")
        assert bad.status_code == 409 and "PRIVATE_SOURCE" not in bad.text
