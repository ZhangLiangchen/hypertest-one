"""Original receipts advance the report stream only after exact verification."""
from types import SimpleNamespace

import pytest

from hypertest.cloud.docker_sandbox import DockerSandbox
from hypertest.cloud.errors import CloudBlocked


@pytest.mark.asyncio
async def test_lost_response_only_queries_original_key_and_checks_record():
    calls = []
    receipt = {"status": "ACCEPTED", "operation": "PREPARE_CONTAINER_START", "operation_key": "original",
               "project_id": "project", "task_id": "task", "attempt_id": "attempt", "version": 8,
               "container_start_intent": {"container_id": "actual", "state": "SENT"}}

    async def query(key):
        calls.append(("query", key))
        return receipt

    async def send():
        calls.append(("send", "original"))
        raise TimeoutError

    sandbox = object.__new__(DockerSandbox)
    sandbox.broker = SimpleNamespace(project_id="project", task_id="task", attempt_id="attempt", receipt=query)
    sandbox.reporter = SimpleNamespace(version=7)
    kwargs = {"key": "original", "operation": "PREPARE_CONTAINER_START", "expected_version": 7,
              "record_name": "container_start_intent", "expected_record": {"container_id": "actual", "state": "SENT"}}
    assert await sandbox._accepted(send, **kwargs) == receipt
    assert sandbox.reporter.version == 8
    assert calls == [("send", "original"), ("query", "original")]
    sandbox.reporter.version = 7
    kwargs["expected_record"] = {"container_id": "wrong"}
    with pytest.raises(CloudBlocked):
        await sandbox._accepted(send, **kwargs)
    assert sandbox.reporter.version == 7
