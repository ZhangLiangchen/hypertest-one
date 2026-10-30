"""Private two-stage Cloud write ledger; never performs network I/O.

Explicit opt-in does not bypass the trusted signer, transport or independent
provider terminal verifier. HTTP alone cannot release a hold.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from hypertest.application.services import canonical_json_sha256
from hypertest.cloud.action_profile import validate_action_profile
from hypertest.cloud.errors import CloudBlocked
from hypertest.cloud.http_profile import canonical_target
from hypertest.common.ids import uuid7
from hypertest.config import get_settings
from hypertest.connector.security import token_hash
from hypertest.domain.cloud_actions import (
    CloudActionIdentity,
    CloudActionObservation,
    CloudActionSend,
)
from hypertest.domain.cloud_tasks import (
    CloudWorkGrant,
    CredentialVersion,
    ProjectCredential,
)


def controlled_actions_enabled():
    return get_settings().cloud_controlled_actions_enabled
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_ACTION_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def reject(code: str, status: int = 409):
    raise HTTPException(status, code)


async def ensure_actions_closed(db, *, task_id, attempt_id=None):
    # Only the trusted, original-ID-bound provider observation can close an
    # action. HTTP success, an Agent assertion or missing response cannot.
    query = select(CloudActionIdentity.id).where(CloudActionIdentity.task_id == task_id)
    if attempt_id is not None:
        query = query.where(CloudActionIdentity.attempt_id == attempt_id)
    for identity_id in await db.scalars(query):
        send_id = await db.scalar(select(CloudActionSend.id).where(CloudActionSend.identity_id == identity_id))
        if send_id is None or await db.scalar(select(CloudActionObservation.id).where(
                CloudActionObservation.send_id == send_id, CloudActionObservation.state == "BUSINESS_TERMINAL")) is None:
            reject("CLOUD_ACTION_BUSINESS_UNRECONCILED")


async def live_actions(db, attempt_id):
    """Return bounded nonsecret metadata, never a business verdict."""
    identities = list(await db.scalars(select(CloudActionIdentity).where(
        CloudActionIdentity.attempt_id == attempt_id).order_by(CloudActionIdentity.id)))
    result = []
    for row in identities:
        send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
        observations = list(await db.scalars(select(CloudActionObservation).where(
            CloudActionObservation.send_id == send.id).order_by(CloudActionObservation.id))) if send else []
        terminal = any(item.state == "BUSINESS_TERMINAL" for item in observations)
        result.append({"identity_id": str(row.id), "action_key": row.action_key, "operation_key": row.operation_key,
            "client_ref": row.client_ref, "unique_ref": row.unique_ref, "plan_sha256": row.plan_sha256,
            "state": "BUSINESS_TERMINAL" if terminal else ("SENT_UNRECONCILED" if send else "IDENTIFIED_UNRECONCILED"),
            "body_sha256": send.body_sha256 if send else None,
            "observations": [{"state": item.state, "observation": item.observation} for item in observations]})
    return result


class WorkerActionAuthority:
    def __init__(self, sessions, *, task_id: str, attempt_id: str, identity):
        self.sessions = sessions
        self.task_id, self.attempt_id = UUID(task_id), UUID(attempt_id)
        self.identity = identity

    async def _locked(self, db):
        from . import cloud_tasks as service
        task = await service._task(db, self.task_id, lock=True)
        attempt = await service._attempt(db, task, self.attempt_id)
        return task, attempt

    async def _original(self, db, identity_id):
        row = await db.get(CloudActionIdentity, UUID(str(identity_id)), populate_existing=True)
        if row is None or row.task_id != self.task_id or row.attempt_id != self.attempt_id:
            reject("CLOUD_ACTION_NOT_FOUND_QUERY_ONLY", 404)
        grant = await db.get(CloudWorkGrant, row.work_grant_id, populate_existing=True)
        if (self.identity is None or grant is None or grant.token_hash != token_hash(self.identity.work_token)
                or grant.project_id != row.project_id or grant.attempt_id != row.attempt_id
                or grant.worker_id != row.worker_id or grant.worker_id != self.identity.worker_id
                or grant.lease_generation != row.generation or row.generation != self.identity.generation):
            reject("CLOUD_ACTION_ORIGINAL_OWNER_REQUIRED", 403)
        return row

    async def _authorized(self, db, task, attempt, action_key):
        from . import cloud_tasks as service
        if not controlled_actions_enabled():
            reject("CLOUD_ACTION_LEDGER_UNAVAILABLE", 503)
        service.enabled()
        await service.worker_authority(db, task, attempt, self.identity)
        if attempt.status != "RUNNING":
            reject("CLOUD_ACTION_REQUIRES_RUNNING_ATTEMPT")
        try:
            profile = task.inputs["controlled_actions"]
            frozen = task.frozen_manifest
            if (validate_action_profile(profile) != profile
                    or frozen["inputs"]["controlled_actions"] != profile
                    or frozen["config_id"] != str(task.config_id)):
                raise ValueError
            actions = profile["actions"]
            if not isinstance(actions, list) or not 1 <= len(actions) <= 32:
                raise ValueError
            selected = [value for value in actions if isinstance(value, dict) and value.get("action_key") == action_key]
            if len(selected) != 1:
                raise ValueError
            action = selected[0]
            required = {"action_key", "method", "path", "parameters", "expected_body", "identity_fields", "credential_version_ids", "framework_commit", "adapter_path", "adapter_import_root", "adapter_sha256", "adapter_protocol", "signature_policy", "observer"}
            if (set(action) != required or action["method"] != "POST" or not isinstance(action["parameters"], dict)
                    or not isinstance(action["expected_body"], dict) or not isinstance(action["identity_fields"], dict)
                    or set(action["identity_fields"]) != {"client_ref", "unique_ref", "signature"}
                    or any(not isinstance(value, str) or not value for value in action["identity_fields"].values())
                    or len(set(action["identity_fields"].values())) != 3
                    or set(action["identity_fields"].values()) & set(action["expected_body"])
                    or not isinstance(action["path"], str) or not action["path"].startswith("/")
                    or action["framework_commit"] != frozen["resolution"]["repositories"]["framework"]["commit_sha"]
                    or not isinstance(action["adapter_sha256"], str) or not _SHA.fullmatch(action["adapter_sha256"])
                    or not isinstance(profile["target"], str) or len(profile["target"]) > 512):
                raise ValueError
            authorization = task.inputs["authorization"]
            target = profile["target"]
            config = await service._configuration(db, task.project_id, task.config_id)
            environment = config.configuration["environment"]
            if (frozen["configuration"] != config.configuration or environment.get("connection") != "HTTPS"
                    or environment.get("cloud_access_policy") == "LOCAL_ONLY"
                    or canonical_target(environment.get("host"), environment.get("port")) != target):
                reject("CLOUD_ACTION_ENVIRONMENT_MISMATCH", 403)
            if (not {"environment:read", "environment:write"} <= set(authorization["permitted_actions"])
                    or target not in authorization["targets"]
                    or authorization["network_targets"] != [target]):
                reject("CLOUD_ACTION_EXACT_AUTHORIZATION_REQUIRED", 403)
            now = await service.clock(db)
            auth_end = datetime.fromisoformat(authorization["expires_at"].replace("Z", "+00:00"))
            hold = attempt.runtime_metadata["budget_reservation"]
            seconds = hold["reserved_seconds"]
            if (auth_end.tzinfo is None or auth_end <= now or hold["state"] != "HELD"
                    or type(seconds) is not int or seconds < 1 or attempt.started_at is None
                    or hold["lease_generation"] != self.identity.generation):
                raise ValueError
            deadline = min(auth_end, attempt.started_at + timedelta(seconds=seconds))
            if deadline <= now:
                raise ValueError
            credentials = action["credential_version_ids"]
            if not isinstance(credentials, dict) or set(credentials) != {"api_key", "signing_key", "observer_oauth"}:
                raise ValueError
            ids = [UUID(value) for value in credentials.values()]
            if len(set(ids)) != len(ids):
                raise ValueError
            for role, credential_id in zip(credentials, ids, strict=True):
                version = await db.get(CredentialVersion, credential_id)
                credential = await db.scalar(select(ProjectCredential).where(ProjectCredential.id == version.credential_id)
                    .with_for_update(read=True).execution_options(populate_existing=True)) if version else None
                required_action = "environment:read" if role == "observer_oauth" else "environment:write"
                purpose = {"api_key": "controlled-action-api-key", "signing_key": "controlled-action-signing-key",
                           "observer_oauth": "controlled-action-observer-oauth"}[role]
                if (version is None or credential is None or version.project_id != task.project_id
                        or credential.project_id != task.project_id or credential.status != "ACTIVE"
                        or credential.kind != "APPLICATION_PRIVATE_KEY" or credential.purpose != purpose
                        or (version.expires_at is not None and version.expires_at <= now)
                        or target not in credential.allowed_targets or required_action not in credential.allowed_actions):
                    reject("CLOUD_ACTION_CREDENTIAL_SCOPE_REQUIRED", 403)
        except HTTPException:
            raise
        except (CloudBlocked, KeyError, ValueError, TypeError, AttributeError, OverflowError):
            reject("CLOUD_ACTION_FROZEN_PLAN_INVALID", 422)
        return action, target, deadline, now

    async def prepare_identity(self, *, action_key: str, operation_key: str, client_ref: str, unique_ref: str):
        from . import cloud_tasks as service
        if (not isinstance(action_key, str) or not _ACTION_KEY.fullmatch(action_key)
                or any(not isinstance(v, str) or not _KEY.fullmatch(v) for v in (operation_key, client_ref, unique_ref))):
            reject("CLOUD_ACTION_IDENTITY_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            action, target, deadline, now = await self._authorized(db, task, attempt, action_key)
            for reference in sorted({client_ref, unique_ref}):
                await service._lock(db, f"cloud-action-reference:{task.project_id}:{reference}")
            prior = await db.scalar(select(CloudActionIdentity).where(CloudActionIdentity.task_id == task.id,
                CloudActionIdentity.action_key == action_key))
            if prior is not None:
                if (prior.attempt_id != attempt.id or prior.operation_key != operation_key
                        or prior.client_ref != client_ref or prior.unique_ref != unique_ref):
                    reject("CLOUD_ACTION_ORIGINAL_IDENTITY_CONFLICT")
                await self._original(db, prior.id)
                return await self._record(db, prior)
            if await db.scalar(select(CloudActionIdentity.id).where(CloudActionIdentity.attempt_id == attempt.id,
                    CloudActionIdentity.operation_key == operation_key)):
                reject("CLOUD_ACTION_ORIGINAL_IDENTITY_CONFLICT")
            if await db.scalar(select(CloudActionIdentity.id).where(CloudActionIdentity.project_id == task.project_id,
                    or_(CloudActionIdentity.client_ref == client_ref, CloudActionIdentity.unique_ref == unique_ref))):
                reject("CLOUD_ACTION_CLIENT_REFERENCE_CONFLICT")
            await service._reject_secrets(db, task.project_id, [action_key, operation_key, client_ref, unique_ref, action])
            from .cloud_ssh import ensure_remote_closed
            await ensure_remote_closed(db, task_id=task.id)
            count = await db.scalar(select(func.count()).select_from(CloudActionIdentity).where(CloudActionIdentity.task_id == task.id))
            if count >= task.inputs["controlled_actions"]["max_operations"]:
                reject("CLOUD_ACTION_LIMIT_EXHAUSTED")
            grant = await db.scalar(select(CloudWorkGrant).where(CloudWorkGrant.token_hash == token_hash(self.identity.work_token)))
            row = CloudActionIdentity(id=uuid7(), created_at=now, project_id=task.project_id, task_id=task.id,
                attempt_id=attempt.id, config_id=task.config_id, work_grant_id=grant.id, worker_id=self.identity.worker_id,
                generation=self.identity.generation, operation_key=operation_key, action_key=action_key,
                client_ref=client_ref, unique_ref=unique_ref, target=target, plan_sha256=canonical_json_sha256(action),
                hard_deadline=deadline)
            db.add(row)
            await db.flush()
            record = await self._record(db, row, allow_prepare=True)
            await db.commit()
            return record

    async def _record(self, db, row, *, allow_prepare=False, allow_send=False):
        send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
        observations = list(await db.scalars(select(CloudActionObservation).where(CloudActionObservation.send_id == send.id)
            .order_by(CloudActionObservation.id))) if send else []
        return {"identity_id": str(row.id), "action_key": row.action_key, "operation_key": row.operation_key,
            "client_ref": row.client_ref, "unique_ref": row.unique_ref, "plan_sha256": row.plan_sha256,
            "state": "SENT" if send else "IDENTIFIED", "send_id": str(send.id) if send else None,
            "body_sha256": send.body_sha256 if send else None, "allow_prepare": allow_prepare, "allow_send": allow_send,
            "observations": [{"state": item.state, "observation": item.observation} for item in observations]}

    async def get_by_key(self, operation_key: str):
        if not isinstance(operation_key, str) or not _KEY.fullmatch(operation_key):
            reject("CLOUD_ACTION_IDENTITY_INVALID", 422)
        async with self.sessions() as db:
            row = await db.scalar(select(CloudActionIdentity).where(CloudActionIdentity.attempt_id == self.attempt_id,
                CloudActionIdentity.operation_key == operation_key))
            if row is None:
                reject("CLOUD_ACTION_NOT_FOUND_QUERY_ONLY", 404)
            return await self._record(db, await self._original(db, row.id))

    async def prepare_send(self, *, identity_id: str, body_sha256: str):
        if not isinstance(body_sha256, str) or not _SHA.fullmatch(body_sha256):
            reject("CLOUD_ACTION_BODY_DIGEST_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            action, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            if (canonical_json_sha256(action) != row.plan_sha256 or target != row.target
                    or now >= row.hard_deadline or deadline < row.hard_deadline):
                reject("CLOUD_ACTION_FROZEN_PLAN_CHANGED")
            prior = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            if prior is not None:
                if prior.body_sha256 != body_sha256:
                    reject("CLOUD_ACTION_ORIGINAL_SEND_CONFLICT")
                return await self._record(db, row)
            db.add(CloudActionSend(id=uuid7(), created_at=now, project_id=row.project_id, task_id=row.task_id,
                attempt_id=row.attempt_id, identity_id=row.id, body_sha256=body_sha256, state="SENT"))
            await db.flush()
            record = await self._record(db, row, allow_send=True)
            await db.commit()
            return record

    async def admit_send(self, *, identity_id: str, body_sha256: str):
        """Recheck authority immediately before transport, without issuing send rights."""
        if not isinstance(body_sha256, str) or not _SHA.fullmatch(body_sha256):
            reject("CLOUD_ACTION_BODY_DIGEST_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            action, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            if (send is None or send.body_sha256 != body_sha256 or canonical_json_sha256(action) != row.plan_sha256
                    or target != row.target or deadline < row.hard_deadline or now >= row.hard_deadline):
                reject("CLOUD_ACTION_SEND_AUTHORITY_INVALID")

    async def materialize_credential(self, *, identity_id: str, role: str) -> bytes:
        """Decrypt one scoped version only in the trusted Worker process."""
        from . import cloud_tasks as service
        if role not in {"api_key", "signing_key", "observer_oauth"}:
            reject("CLOUD_ACTION_CREDENTIAL_ROLE_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            action, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            if (canonical_json_sha256(action) != row.plan_sha256 or target != row.target
                    or deadline < row.hard_deadline or now >= row.hard_deadline):
                reject("CLOUD_ACTION_FROZEN_PLAN_CHANGED")
            sent = await db.scalar(select(CloudActionSend.id).where(CloudActionSend.identity_id == row.id))
            if role in {"api_key", "signing_key"} and sent is not None:
                reject("CLOUD_ACTION_SIGNER_AFTER_SEND_REFUSED")
            version = await db.get(CredentialVersion, UUID(action["credential_version_ids"][role]))
            credential = await db.get(ProjectCredential, version.credential_id)
            context = {"project_id": str(task.project_id), "credential_id": str(credential.id),
                       "version": version.version, "purpose": credential.purpose}
            return service._cipher().decrypt(version.encrypted_secret, context=context)

    async def admit_preflight(self, *, action_key: str):
        """Recheck current grant and all frozen credentials before each GET/OAuth."""
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            await self._authorized(db, task, attempt, action_key)

    async def materialize_preflight_credential(self, *, action_key: str) -> bytes:
        """Read only this fixed action's observer credential; create no operation."""
        from . import cloud_tasks as service
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            action, _, _, _ = await self._authorized(db, task, attempt, action_key)
            version = await db.get(CredentialVersion, UUID(action["credential_version_ids"]["observer_oauth"]))
            credential = await db.get(ProjectCredential, version.credential_id)
            context = {"project_id": str(task.project_id), "credential_id": str(credential.id),
                       "version": version.version, "purpose": credential.purpose}
            return service._cipher().decrypt(version.encrypted_secret, context=context)

    async def admit_observation(self, *, identity_id: str):
        """Recheck current original owner, frozen plan and SENT before every read."""
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            action, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            sent = await db.scalar(select(CloudActionSend.id).where(CloudActionSend.identity_id == row.id))
            if (sent is None or canonical_json_sha256(action) != row.plan_sha256 or target != row.target
                    or deadline < row.hard_deadline or now >= row.hard_deadline):
                reject("CLOUD_ACTION_OBSERVATION_AUTHORITY_INVALID")

    async def remote_closed(self):
        async with self.sessions() as db:
            try:
                await ensure_actions_closed(db, task_id=self.task_id)
            except HTTPException:
                return False
            return True

    async def record_observation(self, *, identity_id: str, observation: dict):
        from . import cloud_tasks as service
        fields = {"state", "http_status", "body_sha256", "byte_count", "reason", "observed_at"}
        if (not isinstance(observation, dict) or set(observation) != fields
                or observation.get("state") not in {"HTTP_OBSERVED", "UNKNOWN"}
                or not isinstance(observation.get("body_sha256"), str) or not _SHA.fullmatch(observation["body_sha256"])
                or type(observation.get("byte_count")) is not int or not 0 <= observation["byte_count"] <= 262144
                or type(observation.get("observed_at")) is not int or observation["observed_at"] < 1):
            reject("CLOUD_ACTION_OBSERVATION_INVALID", 422)
        state, status, reason = observation["state"], observation["http_status"], observation["reason"]
        if ((state == "HTTP_OBSERVED" and (type(status) is not int or not 100 <= status <= 599 or reason != "RESPONSE_OBSERVED"))
                or (state == "UNKNOWN" and (status is not None or observation["byte_count"] != 0
                    or observation["body_sha256"] != _EMPTY_SHA
                    or reason not in {"TRANSPORT_UNKNOWN", "AUTHORITY_LOST", "OUTPUT_REJECTED"}))):
            reject("CLOUD_ACTION_OBSERVATION_INVALID", 422)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            if state == "HTTP_OBSERVED":
                await self._authorized(db, task, attempt, row.action_key)
            send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            if send is None:
                reject("CLOUD_ACTION_NOT_SENT")
            now = await service.clock(db)
            if observation["observed_at"] > int(now.timestamp()) + 5 or observation["observed_at"] < int(send.created_at.timestamp()) - 1:
                reject("CLOUD_ACTION_OBSERVATION_INVALID", 422)
            digest = canonical_json_sha256(observation)
            previous = await db.scalar(select(CloudActionObservation).where(CloudActionObservation.send_id == send.id,
                CloudActionObservation.state == "HTTP_OBSERVED"))
            if previous and state == "HTTP_OBSERVED" and previous.observation_sha256 != digest:
                reject("CLOUD_ACTION_HTTP_OBSERVATION_CONFLICT")
            if not await db.scalar(select(CloudActionObservation.id).where(CloudActionObservation.send_id == send.id,
                    CloudActionObservation.observation_sha256 == digest)):
                db.add(CloudActionObservation(project_id=row.project_id, task_id=row.task_id, attempt_id=row.attempt_id,
                    send_id=send.id, state=state, observation_sha256=digest, observation=observation))
                await db.flush()
            record = await self._record(db, row)
            await db.commit()
            return record

    async def observe_business_terminal(self, identity_id: str, operation_key: str, *, observer, signer, validate_output):
        """Call the Worker-only observer; Agent-supplied observations cannot enter.

        A provider terminal is not an independently verified chain receipt or a
        reported PASS. Ambiguous reads do not alter the original SENT record.
        """
        from hypertest.cloud.action_observer import ActionObserver, _projection
        from hypertest.cloud.action_signer import ActionSigner

        from . import cloud_tasks as service

        if type(observer) is not ActionObserver or type(signer) is not ActionSigner or not callable(validate_output):
            reject("CLOUD_ACTION_TRUSTED_OBSERVER_REQUIRED", 403)
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            action, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            if (row.operation_key != operation_key or send is None or canonical_json_sha256(action) != row.plan_sha256
                    or target != row.target or deadline < row.hard_deadline or now >= row.hard_deadline
                    or observer.profile != task.inputs["controlled_actions"]):
                reject("CLOUD_ACTION_OBSERVATION_AUTHORITY_INVALID")
            previous = await db.scalar(select(CloudActionObservation).where(
                CloudActionObservation.send_id == send.id, CloudActionObservation.state == "BUSINESS_TERMINAL"))
            if previous:
                return {"projection": previous.observation["projection"], "business_terminal": True,
                        "recorded": True}
        # No DB transaction is held open during OAuth and provider GETs.
        observed = await observer.observe(action=action, authority=self, signer=signer,
            identity_id=identity_id, operation_key=operation_key, validate_output=validate_output)
        try:
            if not isinstance(observed, dict) or set(observed) != {"projection", "order_response_sha256", "details_response_sha256", "observed_at"}:
                raise ValueError
            projection = observed["projection"]
            _projection(projection, profile=action["observer"]["observed_profile"], client_ref=row.client_ref,
                        order_id=projection["order_id"], terminal_transaction_type=action["observer"]["terminal_transaction_type"])
            if (not all(isinstance(observed[key], str) and _SHA.fullmatch(observed[key])
                        for key in ("order_response_sha256", "details_response_sha256"))
                    or type(observed["observed_at"]) is not int):
                raise ValueError
        except (KeyError, ValueError, TypeError):
            reject("CLOUD_ACTION_TERMINAL_OBSERVATION_INVALID", 422)
        if projection["business_terminal"] is not True:
            return {"projection": projection, "business_terminal": False, "recorded": False}
        async with self.sessions() as db:
            task, attempt = await self._locked(db)
            row = await self._original(db, identity_id)
            latest, target, deadline, now = await self._authorized(db, task, attempt, row.action_key)
            send = await db.scalar(select(CloudActionSend).where(CloudActionSend.identity_id == row.id))
            if (row.operation_key != operation_key or send is None or canonical_json_sha256(latest) != row.plan_sha256
                    or target != row.target or deadline < row.hard_deadline or now >= row.hard_deadline
                    or observed["observed_at"] < int(send.created_at.timestamp()) - 1
                    or observed["observed_at"] > int(now.timestamp()) + 5):
                reject("CLOUD_ACTION_OBSERVATION_AUTHORITY_INVALID")
            existing = await db.scalar(select(CloudActionObservation).where(
                CloudActionObservation.send_id == send.id, CloudActionObservation.state == "BUSINESS_TERMINAL"))
            if existing:
                if existing.observation["projection"] != projection:
                    reject("CLOUD_ACTION_BUSINESS_TERMINAL_CONFLICT")
                return {"projection": existing.observation["projection"], "business_terminal": True, "recorded": True}
            payload = {"state": "BUSINESS_TERMINAL", "projection": projection,
                "order_response_sha256": observed["order_response_sha256"],
                "details_response_sha256": observed["details_response_sha256"], "observed_at": observed["observed_at"]}
            await service._reject_secrets(db, task.project_id, payload)
            db.add(CloudActionObservation(project_id=row.project_id, task_id=row.task_id, attempt_id=row.attempt_id,
                send_id=send.id, state="BUSINESS_TERMINAL", observation_sha256=canonical_json_sha256(payload), observation=payload))
            await db.flush()
            await db.commit()
            return {"projection": projection, "business_terminal": True, "recorded": True}

    async def record_business_terminal(self, **_kwargs):
        # Direct/project/Agent claims are never terminal evidence.
        reject("CLOUD_ACTION_TERMINAL_VERIFIER_UNAVAILABLE", 503)
