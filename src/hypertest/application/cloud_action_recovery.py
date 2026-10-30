"""Worker-only original-key read recovery under an operator-issued receipt.

This authority exposes no identity creation, signer credential or send method.
It never accepts provider responses or an order ID from its caller.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from hypertest.application import cloud_actions
from hypertest.application import cloud_tasks as service
from hypertest.application.cloud_actions import (
    _SHA,
    WorkerActionAuthority,
    reject,
)
from hypertest.application.services import canonical_json_sha256
from hypertest.cloud.action_observer import ActionObserver, _projection
from hypertest.cloud.action_profile import validate_action_profile
from hypertest.cloud.action_signer import ActionSigner
from hypertest.cloud.http_profile import canonical_target, digest
from hypertest.config import get_settings
from hypertest.domain.cloud_actions import (
    CloudActionIdentity,
    CloudActionObservation,
    CloudActionSend,
)
from hypertest.domain.cloud_tasks import CloudOperationReceipt, CredentialVersion, ProjectCredential


class ActionRecoveryAuthority:
    """A receipt authorizes only the exact original action for five minutes."""
    def __init__(self, sessions, *, task_id: str, attempt_id: str, authorization_key: str):
        self.sessions = sessions
        self.task_id, self.attempt_id = UUID(task_id), UUID(attempt_id)
        self.authorization_key = authorization_key

    async def _checked(self, db):
        service.enabled()
        if not cloud_actions.controlled_actions_enabled():
            reject("CLOUD_ACTION_RECOVERY_UNAVAILABLE", 503)
        task = await service._task(db, self.task_id, lock=True)
        attempt = await service._attempt(db, task, self.attempt_id)
        receipt = await db.scalar(select(CloudOperationReceipt).where(
            CloudOperationReceipt.project_id == task.project_id,
            CloudOperationReceipt.task_id == task.id,
            CloudOperationReceipt.attempt_id == attempt.id,
            CloudOperationReceipt.operation == "AUTHORIZE_ACTION_OBSERVATION",
            CloudOperationReceipt.operation_key == self.authorization_key))
        if (receipt is None or not receipt.actor_ref.startswith("operator:")
                or attempt.status != "RECOVERY_REQUIRED" or not await service._owner_fenced(db, attempt)):
            reject("CLOUD_ACTION_RECOVERY_AUTHORITY_REQUIRED", 403)
        await service._ensure_container_closed(db, task.id)
        intents = [item for item in await service._container_intents(db, task.id)
                   if item.get("attempt_id") == str(attempt.id)]
        stops = [item for item in await service._container_observations(db, task.id)
                 if item.get("attempt_id") == str(attempt.id) and item.get("state") == "STOPPED"]
        if len(intents) != 1 or len(stops) != 1 or stops[0].get("create_operation_key") != intents[0].get("operation_key"):
            reject("CLOUD_ACTION_RECOVERY_STOP_UNOBSERVED")
        grant = receipt.response.get("action_observation_authorization")
        try:
            if not isinstance(grant, dict) or set(grant) != {"identity_id", "original_operation_key", "action_key", "expires_at"}:
                raise ValueError
            now = await service.clock(db)
            deadline = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
            if deadline.tzinfo is None or deadline <= now or deadline > receipt.created_at + service.timedelta(minutes=5, seconds=5):
                raise ValueError
            row = await db.get(CloudActionIdentity, UUID(grant["identity_id"]), populate_existing=True)
            if (row is None or row.task_id != task.id or row.attempt_id != attempt.id
                    or row.project_id != task.project_id or row.operation_key != grant["original_operation_key"]
                    or row.action_key != grant["action_key"]):
                raise ValueError
            send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            profile = validate_action_profile(task.inputs["controlled_actions"])
            frozen = task.frozen_manifest
            if (send is None or digest(frozen) != task.input_digest or frozen["inputs"]["controlled_actions"] != profile
                    or frozen["config_id"] != str(task.config_id)):
                raise ValueError
            actions = [item for item in profile["actions"] if item["action_key"] == row.action_key]
            if len(actions) != 1 or canonical_json_sha256(actions[0]) != row.plan_sha256 or profile["target"] != row.target:
                raise ValueError
            action = actions[0]
            conf = await service._configuration(db, task.project_id, task.config_id)
            env, auth = conf.configuration["environment"], task.inputs["authorization"]
            if (frozen["configuration"] != conf.configuration or env.get("connection") != "HTTPS"
                    or env.get("cloud_access_policy") == "LOCAL_ONLY"
                    or canonical_target(env.get("host"), env.get("port")) != row.target
                    or "environment:read" not in auth["permitted_actions"]
                    or auth["network_targets"] != [row.target] or row.target not in auth["targets"]
                    or action["framework_commit"] != frozen["resolution"]["repositories"]["framework"]["commit_sha"]):
                raise ValueError
            version = await db.get(CredentialVersion, UUID(action["credential_version_ids"]["observer_oauth"]))
            credential = await db.scalar(select(ProjectCredential).where(ProjectCredential.id == version.credential_id)
                .with_for_update(read=True).execution_options(populate_existing=True)) if version else None
            if (version is None or credential is None or version.project_id != task.project_id
                    or credential.project_id != task.project_id or credential.status != "ACTIVE"
                    or credential.kind != "APPLICATION_PRIVATE_KEY" or credential.purpose != "controlled-action-observer-oauth"
                    or (version.expires_at is not None and version.expires_at <= now)
                    or row.target not in credential.allowed_targets or "environment:read" not in credential.allowed_actions):
                raise ValueError
            return task, attempt, row, send, action, profile, version, credential, now
        except (ValueError, TypeError, KeyError):
            reject("CLOUD_ACTION_RECOVERY_AUTHORITY_INVALID", 403)

    async def get_by_key(self, operation_key):
        async with self.sessions() as db:
            _, _, row, _, _, _, _, _, _ = await self._checked(db)
            if row.operation_key != operation_key:
                reject("CLOUD_ACTION_NOT_FOUND_QUERY_ONLY", 404)
            return await WorkerActionAuthority._record(self, db, row)

    async def admit_observation(self, *, identity_id):
        async with self.sessions() as db:
            _, _, row, _, _, _, _, _, _ = await self._checked(db)
            if str(row.id) != identity_id:
                reject("CLOUD_ACTION_NOT_FOUND_QUERY_ONLY", 404)

    async def materialize_credential(self, *, identity_id, role):
        if role != "observer_oauth":
            reject("CLOUD_ACTION_CREDENTIAL_ROLE_INVALID", 403)
        async with self.sessions() as db:
            task, _, row, _, _, _, version, credential, _ = await self._checked(db)
            if str(row.id) != identity_id:
                reject("CLOUD_ACTION_NOT_FOUND_QUERY_ONLY", 404)
            context = {"project_id": str(task.project_id), "credential_id": str(credential.id),
                       "version": version.version, "purpose": credential.purpose}
            return service._cipher().decrypt(version.encrypted_secret, context=context)

    async def observe_original(self, *, observer, signer):
        if type(observer) is not ActionObserver or type(signer) is not ActionSigner:
            reject("CLOUD_ACTION_TRUSTED_OBSERVER_REQUIRED", 403)
        async with self.sessions() as db:
            task, attempt, row, send, action, profile, _, _, _ = await self._checked(db)
            source = Path(get_settings().cloud_runtime_root) / ("attempt-" + str(attempt.id)) / "private-signer-source"
            if (observer.profile != profile or signer.profile != profile
                    or signer.export_policy != task.inputs["agent_source_export"] or signer.source_root != source):
                reject("CLOUD_ACTION_TRUSTED_OBSERVER_REQUIRED", 403)
            previous = await db.scalar(select(CloudActionObservation).where(
                CloudActionObservation.send_id == send.id, CloudActionObservation.state == "BUSINESS_TERMINAL"))
            if previous:
                return {"projection": previous.observation["projection"], "business_terminal": True, "recorded": True}
            identity_id, operation_key, client_ref = str(row.id), row.operation_key, row.client_ref
        async def validate_output(value):
            async with self.sessions() as db:
                task, *_ = await self._checked(db)
                await service._reject_secrets(db, task.project_id, value)
        observed = await observer.observe(action=action, authority=self, signer=signer,
            identity_id=identity_id, operation_key=operation_key, validate_output=validate_output)
        try:
            if not isinstance(observed, dict) or set(observed) != {"projection", "order_response_sha256", "details_response_sha256", "observed_at"}:
                raise ValueError
            projection = observed["projection"]
            _projection(projection, profile=action["observer"]["observed_profile"], client_ref=client_ref,
                        order_id=projection["order_id"], terminal_transaction_type=action["observer"]["terminal_transaction_type"])
            if (not all(isinstance(observed[key], str) and _SHA.fullmatch(observed[key])
                        for key in ("order_response_sha256", "details_response_sha256"))
                    or type(observed["observed_at"]) is not int):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            reject("CLOUD_ACTION_TERMINAL_OBSERVATION_INVALID", 422)
        if not projection["business_terminal"]:
            return {"projection": projection, "business_terminal": False, "recorded": False}
        async with self.sessions() as db:
            task, _, row, send, latest, _, _, _, now = await self._checked(db)
            if (str(row.id) != identity_id or row.operation_key != operation_key or latest != action
                    or observed["observed_at"] < int(send.created_at.timestamp()) - 1
                    or observed["observed_at"] > int(now.timestamp()) + 5):
                reject("CLOUD_ACTION_RECOVERY_AUTHORITY_INVALID")
            existing = await db.scalar(select(CloudActionObservation).where(
                CloudActionObservation.send_id == send.id, CloudActionObservation.state == "BUSINESS_TERMINAL"))
            if existing:
                if existing.observation["projection"] != projection:
                    reject("CLOUD_ACTION_BUSINESS_TERMINAL_CONFLICT")
                return {"projection": existing.observation["projection"], "business_terminal": True, "recorded": True}
            payload = {"state": "BUSINESS_TERMINAL", **observed}
            await service._reject_secrets(db, task.project_id, payload)
            db.add(CloudActionObservation(project_id=row.project_id, task_id=row.task_id, attempt_id=row.attempt_id,
                send_id=send.id, state="BUSINESS_TERMINAL", observation_sha256=canonical_json_sha256(payload), observation=payload))
            await db.flush()
            await db.commit()
            return {"projection": projection, "business_terminal": True, "recorded": True}
