"""Current Cloud task contract; synthetic data only in the dedicated test DB."""
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_cloud_tasks import cloud_context as _cloud_context
from test_cloud_tasks import configuration, new_inputs, post

from hypertest.api.cloud_schemas import CloudTaskCreate
from hypertest.application import cloud_tasks as service
from hypertest.cloud.native_worker import native_prompt
from hypertest.db.session import AsyncSessionLocal
from hypertest.domain.cloud_tasks import CloudTask, ProjectCloudConfigRevision
from hypertest.domain.models import Project

cloud_context = _cloud_context

MR = "https://git.example.invalid/team/sut/-/merge_requests/12"
FRAMEWORK = "https://git.example.invalid/team/framework.git"


def task_inputs(**changes):
    value = new_inputs(**{"authorization": None, "mr_url": MR, **changes})
    value.pop("sut_selector", None)
    value.pop("framework_selector", None)
    return value


def payload(**changes):
    return {"project_id": uuid4(), "operation_key": "task-fixture", "expected_version": 0,
            "expected_project_version": 1, "title": "Fixture", "inputs": task_inputs(), **changes}


@pytest.mark.parametrize("url", [
    "https://user:token@git.example.invalid/team/sut/-/merge_requests/12",
    "http://git.example.invalid/team/sut/-/merge_requests/12",
    "https://git.example.invalid/team/sut/-/merge_requests/0",
    "https://git.example.invalid/team/sut/-/merge_requests/12?token=secret",
    "https://git.example.invalid/team/sut/-/merge_requests/12#note",
    "https://git.example.invalid/team/%2e%2e/sibling/-/merge_requests/12",
    "https://git.example.invalid/team/../sibling/-/merge_requests/12",
    "https://git.example.invalid/team/a%2fb/-/merge_requests/12",
    "https://git.example.invalid/team/a\\b/-/merge_requests/12",
    "https://git.example.invalid/team/sut/-/merge_requests/12 ",
])
def test_mr_rejects_credentials_and_ambiguous_paths(url):
    with pytest.raises(ValidationError):
        CloudTaskCreate.model_validate(payload(inputs=task_inputs(mr_url=url)))


def test_task_schema_requires_mr_and_project_version_without_resource_id():
    current = CloudTaskCreate.model_validate(payload())
    assert current.inputs.sut_selector.value == current.inputs.framework_selector.value == "HEAD"
    for change in ({"config_id": str(uuid4())}, {"expected_project_version": 0},
                   {"inputs": task_inputs(authorization={"targets": ["https://other.invalid/repo"], "permitted_actions": ["git:read"], "side_effect_limits": "unexpected"})}):
        with pytest.raises(ValidationError):
            CloudTaskCreate.model_validate(payload(**change))
    data = payload()
    data["inputs"].pop("mr_url")
    with pytest.raises(ValidationError):
        CloudTaskCreate.model_validate(data)


@pytest.mark.parametrize(("origin", "mr", "expected"), [
    ("https://git.example.invalid/groups/team", MR, "https://git.example.invalid/team/sut.git"),
    ("https://git.example.invalid/groups/team", "https://git.example.invalid/team/sub/sut/-/merge_requests/1", "https://git.example.invalid/team/sub/sut.git"),
    ("https://git.example.invalid/team/sut.git", MR, "https://git.example.invalid/team/sut.git"),
    ("git@git.example.invalid:team", MR, "git@git.example.invalid:team/sut.git"),
    ("ssh://git@git.example.invalid:2222/team", MR, "ssh://git@git.example.invalid:2222/team/sut.git"),
    ("https://github.com/team", "https://github.com/team/sut/pull/1", "https://github.com/team/sut.git"),
])
def test_mr_repository_preserves_project_group_and_transport(origin, mr, expected):
    assert service._sut_repository_from_mr(origin, mr) == expected


@pytest.mark.parametrize(("origin", "mr"), [
    ("https://git.example.invalid/groups/team", "https://git.example.invalid/team-other/sut/-/merge_requests/12"),
    ("https://git.example.invalid/groups/team", "https://other.example.invalid/team/sut/-/merge_requests/12"),
    ("https://git.example.invalid/groups/team", "https://git.example.invalid:444/team/sut/-/merge_requests/12"),
    ("https://git.example.invalid/team/sut.git", "https://git.example.invalid/team/sut/other/-/merge_requests/12"),
])
def test_mr_repository_refuses_sibling_and_cross_host_scope(origin, mr):
    with pytest.raises(HTTPException) as error:
        service._sut_repository_from_mr(origin, mr)
    assert error.value.status_code == 422


async def repositories(context, *, sut="https://git.example.invalid/groups/team", framework=FRAMEWORK, version=1):
    async with AsyncSessionLocal() as db:
        row = await db.get(Project, UUID(context["project_id"]))
        row.repository_url, row.test_framework_repository_url = sut, framework
        row.row_version = version
        await db.commit()


async def create(context, **changes):
    fields = {"title": "Synthetic MR context task", "expected_project_version": 1, "inputs": task_inputs(), **changes}
    return await post(context, "CREATE_TASK", **fields)


async def test_task_uses_project_repositories_without_resource_configuration(cloud_context):
    context = cloud_context
    await repositories(context)
    created = await create(context, operation_key="create-from-project")
    assert created.status_code == 200, created.text
    task_id = UUID(created.json()["task_id"])
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, task_id)
        config = await db.get(ProjectCloudConfigRevision, task.config_id)
        assert set(config.configuration) == {"sut", "framework"}
        assert config.configuration["sut"]["url"] == "https://git.example.invalid/team/sut.git"
        assert task.inputs["mr_url"] == MR
        assert task.inputs["authorization"]["targets"] == ["https://git.example.invalid/team/sut.git", FRAMEWORK]
        assert task.inputs["sut_selector"]["value"] == "HEAD"
        original_config = task.config_id
    await repositories(context, framework="https://git.example.invalid/team/framework-v2.git", version=2)
    replay = await create(context, operation_key="create-from-project")
    assert replay.status_code == 200 and replay.json() == created.json()
    stale = await post(context, "UPDATE_TASK", 1, task_id=str(task_id), title="Changed",
        expected_project_version=1, inputs=task_inputs())
    assert stale.status_code == 409
    updated = await post(context, "UPDATE_TASK", 1, task_id=str(task_id), title="Changed",
        expected_project_version=2, inputs=task_inputs())
    assert updated.status_code == 200, updated.text
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, task_id)
        assert task.config_id != original_config
        old = await db.get(ProjectCloudConfigRevision, original_config)
        current = await db.get(ProjectCloudConfigRevision, task.config_id)
        assert old.configuration["framework"]["url"] == FRAMEWORK
        assert current.configuration["framework"]["url"].endswith("framework-v2.git")
        assert task.inputs["authorization"]["targets"][1].endswith("framework-v2.git")
    resolved = await post(context, "RESOLVE_INPUTS", updated.json()["version"], task_id=str(task_id))
    assert resolved.status_code == 200, resolved.text


async def test_missing_repositories_and_stale_project_create_no_task_snapshot(cloud_context):
    context = cloud_context
    await repositories(context, sut=None, framework=None)
    assert (await create(context)).status_code == 422
    await repositories(context, version=2)
    assert (await create(context)).status_code == 409
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(CloudTask).where(CloudTask.project_id == UUID(context["project_id"]))) == 0
        assert await db.scalar(select(func.count()).select_from(ProjectCloudConfigRevision).where(ProjectCloudConfigRevision.project_id == UUID(context["project_id"]))) == 0


async def test_resource_writes_retired_but_historical_readback_available(cloud_context):
    context = cloud_context
    response = await post(context, "CONFIGURE", configuration=configuration())
    assert response.status_code == 410 and response.json()["detail"] == "CLOUD_PROJECT_RESOURCES_RETIRED"
    await repositories(context)
    assert (await create(context)).status_code == 200
    readback = await context["client"].get(f"/api/v1/cloud/projects/{context['project_id']}/configuration", headers=context["headers"])
    assert readback.status_code == 200
    assert len(readback.json()["items"]) == 1


async def test_source_resolution_and_dispatch_require_no_environment_observation(cloud_context):
    context = cloud_context
    await repositories(context)
    created = await create(context)
    assert created.status_code == 200, created.text
    task_id = created.json()["task_id"]
    request = await post(context, "RESOLVE_INPUTS", 1, task_id=task_id)
    assert request.status_code == 200, request.text
    async with AsyncSessionLocal() as db:
        claim = await service.claim_resolution(db, "project-input-fixture", project_id=UUID(context["project_id"]))
        result = {"repositories": {role: {"url": claim["configuration"][role]["url"],
            "commit_sha": str(index) * 40, "selector": claim["task"]["inputs"][role + "_selector"]}
            for index, role in enumerate(("sut", "framework"), 1)},
            "observed_at": datetime.now(UTC).isoformat(), "source": "synthetic-no-git-executed"}
        accepted = await service.accept_resolution(db, UUID(claim["resolution"]["id"]), "project-input-fixture",
            claim["lease_token"], result, work_token=claim["work_token"])
    dispatch = await post(context, "DISPATCH", accepted["version"], task_id=task_id,
        resolution_id=request.json()["resolution_id"])
    assert dispatch.status_code == 200, dispatch.text
    async with AsyncSessionLocal() as db:
        task = await db.get(CloudTask, UUID(task_id))
        assert "environment" not in task.frozen_manifest["configuration"]
        assert "environment_observation" not in task.frozen_manifest["resolution"]
        prompt = native_prompt(service.public(task), {"id": dispatch.json()["attempt_id"]}, Path("/tmp/fixture"))
        assert MR in prompt
        assert "not a deployment version" in prompt
        assert "does not provision or deploy the SUT" in prompt
