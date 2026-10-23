"""Attempt-local proposal feedback, never a platform operation or receipt."""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter, ValidationError
from pydantic_core import ErrorType

from hypertest.api.cloud_schemas import CloudMutation
from hypertest.interactive_client.security import private_create, private_directory, private_read

from .artifacts import write_workspace_rejection
from .errors import CloudBlocked

MAX_LOCAL_REJECTIONS = 16
_ERROR_TYPES = frozenset(get_args(ErrorType))
_OPERATIONS = frozenset({"SUBMIT_ASSETS", "UPLOAD_ARTIFACT", "SUBMIT_RUN", "SUBMIT_DELEGATION",
    "COMPLETE_ATTEMPT", "REQUEST_INPUT"})


@lru_cache(maxsize=1)
def _static_fields() -> frozenset[str]:
    fields = set(_OPERATIONS)

    def visit(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                fields.update(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(TypeAdapter(CloudMutation).json_schema())
    return frozenset(fields)


def validation_metadata(error: ValidationError) -> list[dict]:
    """Drop messages, inputs, contexts and arbitrary extra-field/dict keys."""
    fields = _static_fields()
    result = []
    for item in error.errors(include_url=False, include_context=False, include_input=False)[:8]:
        kind = item.get("type")
        location = []
        for part in item.get("loc", ())[:8]:
            if type(part) is int and 0 <= part <= 10000:
                location.append(part)
            else:
                location.append(part if isinstance(part, str) and part in fields else "OTHER")
        result.append({"type": kind if kind in _ERROR_TYPES else "OTHER", "loc": location})
    return result


def key_digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class HandoffRejected(CloudBlocked):
    def __init__(self, observation: dict):
        self.observation = observation
        super().__init__("HANDOFF_PAYLOAD_INVALID", "Publish a corrected contribution with a new handoff key")


class LocalRejections:
    def __init__(self, directory: Path, workspace: Path):
        self.directory = private_directory(directory)
        self.workspace = workspace

    def get(self, key: str) -> dict | None:
        path = self.directory / (key_digest(key) + ".json")
        if not path.exists() and not path.is_symlink():
            return None
        document = json.loads(private_read(path, max_bytes=16384))
        if (not isinstance(document, dict) or document.get("key_sha256") != key_digest(key)
                or document.get("status") != "LOCAL_REJECTED"):
            raise CloudBlocked("LOCAL_REJECTION_CORRUPT", "Local proposal feedback cannot be reconciled")
        return document

    def record(self, key: str, source_digest: str, errors: list[dict]) -> dict:
        if not isinstance(source_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", source_digest):
            raise CloudBlocked("LOCAL_REJECTION_INVALID", "Local feedback requires the original handoff digest")
        previous = self.get(key)
        if previous is not None:
            return previous
        if len(list(self.directory.iterdir())) >= MAX_LOCAL_REJECTIONS:
            raise CloudBlocked("LOCAL_REJECTION_LIMIT", "Attempt exhausted its bounded local proposal corrections")
        document = {"profile": "hypertest-cloud-local-rejection/v1alpha1", "status": "LOCAL_REJECTED",
            "key_sha256": key_digest(key), "handoff_sha256": source_digest,
            "reason": "HANDOFF_PAYLOAD_INVALID", "errors": errors,
            "required_action": "PUBLISH_NEW_HANDOFF_KEY", "platform_operation_submitted": False}
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        private_create(self.directory / (key_digest(key) + ".json"), encoded)
        descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        write_workspace_rejection(self.workspace, key_digest(key), document)
        return document
