"""Compose the private controlled-action broker from trusted Worker services.

There is no default live profile or credential source. The caller must supply a
validated provider preflight; the Worker entrypoint keeps this candidate closed
until signer, provider observation and business-terminal integration are ready.
"""
from __future__ import annotations

from pathlib import Path

from hypertest.application.cloud_actions import WorkerActionAuthority

from .action_broker import ActionBroker
from .action_signer import ActionCredentials, ActionSigner
from .errors import CloudBlocked


class ActionRuntime:
    def __init__(self, *, sessions, observer_factory):
        if not callable(observer_factory):
            raise CloudBlocked("CONTROLLED_ACTIONS_UNAVAILABLE", "A trusted provider preflight is required")
        self.sessions, self.observer_factory = sessions, observer_factory

    def broker(self, *, cloud_broker, profile, export_policy, signer_source: Path,
               socket_path: Path, private_root: Path, deadline: int):
        authority = WorkerActionAuthority(self.sessions, task_id=cloud_broker.task_id,
            attempt_id=cloud_broker.attempt_id, identity=cloud_broker.identity)
        signer = ActionSigner(source_root=signer_source, export_policy=export_policy,
            action_profile=profile, authority=authority)
        credentials = ActionCredentials(authority)
        observer = self.observer_factory(profile=profile)

        async def preflight(action):
            return await observer.preflight(action=action, authority=authority, signer=signer)

        return ActionBroker(socket_path, task_id=cloud_broker.task_id, profile=profile, authority=authority,
            signer=signer, credentials=credentials, private_root=private_root, deadline=deadline,
            validate_output=cloud_broker.validate_payload, preflight=preflight, observer=observer)
