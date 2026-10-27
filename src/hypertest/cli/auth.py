"""CLI-initiated, Web-approved pairing with distinct durable CREATE/REDEEM keys."""
from __future__ import annotations

import hashlib
import secrets
import socket
import time
import urllib.parse
import uuid
import webbrowser

from hypertest.cli import AUTH_PREFIX
from hypertest.cli.state import CLIError, State, identifier, profile_name
from hypertest.cli.transport import HTTP, server_url
from hypertest.sync_core import digest


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_view(record: dict, view: dict | None = None) -> dict:
    view = view or record.get("view", {})
    result = {"request_id": record["request_id"], "profile": record["profile_name"],
              "status": view.get("status", "UNKNOWN"),
              "create_state": record["create_state"], "redeem_state": record["redeem_state"],
              "profile_saved": record.get("profile_saved", False)}
    for key in ("short_code", "verification_url", "expires_at", "client_instance_id", "client_name"):
        if key in view:
            result[key] = view[key]
    if view.get("approval"):
        result["approval"] = {k: view["approval"].get(k) for k in
                              ("actor_ref", "project_ids", "scopes", "expires_at")}
    result["grants"] = [{k: g.get(k) for k in ("grant_id", "project_id", "scopes", "expires_at", "status")}
                        for g in view.get("grants", [])]
    return result


def validate_view(record: dict, view: dict) -> None:
    expected = record["create_body"]
    if (view.get("request_id") != record["request_id"]
            or view.get("status") not in {"PENDING", "APPROVED", "BOUND", "DENIED", "EXPIRED"}
            or any(view.get(key) != expected[key] for key in
                   ("client_instance_id", "client_name", "server_url"))
            or view.get("credential_fingerprint") != expected["credential_hash"][:16]):
        raise CLIError("PAIRING_CONTEXT_MISMATCH", 4)
    url = urllib.parse.urlsplit(view.get("verification_url", ""))
    if f"{url.scheme}://{url.netloc}" != record["server"] or url.username or url.password or url.fragment:
        raise CLIError("PAIRING_URL_MISMATCH", 4)
    if view["status"] in {"APPROVED", "BOUND"}:
        approval = view.get("approval")
        if (not isinstance(approval, dict) or not isinstance(approval.get("actor_ref"), str)
                or not approval["actor_ref"].startswith("interactive:")
                or not isinstance(approval.get("project_ids"), list) or not approval["project_ids"]
                or not {"archive:read", "archive:write"} <= set(approval.get("scopes", []))
                or set(approval["scopes"]) - {"archive:read", "archive:write"}
                or not isinstance(approval.get("approval_digest"), str)
                or not isinstance(approval.get("expires_at"), str)):
            raise CLIError("PAIRING_APPROVAL_MISMATCH", 4)
        for project in approval["project_ids"]:
            identifier(project)
        if record.get("approval") and record["approval"] != approval:
            raise CLIError("PAIRING_APPROVAL_CHANGED", 4)
    if view["status"] == "BOUND":
        grants = view.get("grants", [])
        if (not grants or len(grants) != len(view["approval"]["project_ids"])
                or {g.get("project_id") for g in grants} != set(view["approval"]["project_ids"])
                or any(set(g.get("scopes", [])) != set(view["approval"]["scopes"])
                       or g.get("expires_at") != view["approval"]["expires_at"] for g in grants)):
            raise CLIError("PAIRING_GRANT_MISMATCH", 4)
        for grant in grants:
            identifier(grant.get("grant_id"))


def record_view(state: State, record: dict, view: dict) -> None:
    validate_view(record, view)
    record["view"] = view
    if view.get("approval"):
        record["approval"] = view["approval"]
    state.write(state.pairings, record["request_id"], record)


def save_bound(state: State, record: dict) -> None:
    view = record["view"]
    if view.get("status") != "BOUND":
        return
    approval = view["approval"]
    if any(grant.get("status") != "ACTIVE" for grant in view["grants"]):
        raise CLIError("CLI_AUTHORIZATION_INACTIVE", 3)
    state.save_profile(record["profile_name"], record["server"],
                       record["create_body"]["client_instance_id"], approval["actor_ref"],
                       [{"grant_id": grant["grant_id"], "project_ids": [grant["project_id"]],
                         "scopes": grant["scopes"], "expires_at": grant["expires_at"],
                         "credential": record["credential"]} for grant in view["grants"]])
    record["profile_saved"] = True
    state.write(state.pairings, record["request_id"], record)


def query_original(http, record: dict, phase: str) -> dict:
    body = record["create_body"] if phase == "CREATE" else record["redeem_body"]
    receipt = http.call("GET", AUTH_PREFIX + "/requests/by-key", query={
        "request_id": record["request_id"], "operation": phase,
        "idempotency_key": body["idempotency_key"]})
    validate_operation(record, receipt, phase)
    # Fixed operation receipts prove acceptance; current state still governs revocation/expiry.
    return http.call("GET", AUTH_PREFIX + "/requests/" + record["request_id"])


def validate_operation(record: dict, view: dict, phase: str) -> None:
    body = record["create_body"] if phase == "CREATE" else record["redeem_body"]
    validate_view(record, view)
    if (view.get("operation") != phase or view.get("idempotency_key") != body["idempotency_key"]
            or view.get("request_digest") != digest(body)):
        raise CLIError("PAIRING_RECEIPT_MISMATCH", 4)


def reconcile(state: State, request_id: str, *, http_factory=HTTP) -> tuple[dict, int]:
    request_id = identifier(request_id)
    with state.lock("pairing:" + request_id):
        record = state.read(state.pairings, request_id)
        http = http_factory(record["server"], proof=record["verifier"])
        phase = "REDEEM" if record["redeem_state"] != "PREPARED" else "CREATE"
        if record[phase.lower() + "_state"] == "PREPARED":
            return {**safe_view(record), "code": "PAIRING_NOT_SENT"}, 4
        try:
            view = query_original(http, record, phase)
            record_view(state, record, view)
            record[phase.lower() + "_state"] = "ACKED"
            state.write(state.pairings, request_id, record)
            if view["status"] == "BOUND":
                save_bound(state, record)
        except CLIError as exc:
            return {**safe_view(record), "code": exc.code}, 4 if exc.exit_code != 5 else 5
        return safe_view(record), 0 if record.get("profile_saved") else (
            3 if view["status"] in {"DENIED", "EXPIRED"} else 4)


def bind(state: State, *, server: str | None, name: str = "default", project_id: str | None = None,
         request_id: str | None = None, resume: bool = False, wait_seconds: int = 600,
         open_browser: bool = True, notify=None, http_factory=HTTP, sleep=time.sleep,
         monotonic=time.monotonic) -> tuple[dict, int]:
    if not 0 <= wait_seconds <= 600:
        raise CLIError("PAIRING_WAIT_OUT_OF_RANGE")
    if resume:
        if not request_id:
            raise CLIError("PAIRING_REQUEST_ID_REQUIRED")
        request_id = identifier(request_id)
    else:
        if request_id:
            raise CLIError("PAIRING_RESUME_REQUIRED")
        request_id = str(uuid.uuid4())
    with state.lock("pairing:" + request_id):
        if resume:
            record = state.read(state.pairings, request_id)
            if server and server_url(server) != record["server"]:
                raise CLIError("PAIRING_SERVER_MISMATCH")
            if project_id and project_id != record["create_body"].get("project_id"):
                raise CLIError("PAIRING_PROJECT_MISMATCH")
        else:
            if not server:
                raise CLIError("PAIRING_SERVER_REQUIRED")
            server, name = server_url(server), profile_name(name)
            path = state.profiles / (name + ".json")
            existing = state.read(state.profiles, name) if path.exists() else None
            if existing and existing["server"] != server:
                raise CLIError("PROFILE_IDENTITY_CONFLICT", 5)
            credential, verifier = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
            client_id = existing["client_id"] if existing else str(uuid.uuid4())
            body = {"request_id": request_id, "idempotency_key": str(uuid.uuid4()),
                    "client_instance_id": client_id, "client_name": socket.gethostname()[:80] or "HyperTest CLI",
                    "server_url": server, "credential_hash": sha256(credential),
                    "verifier_challenge": sha256(verifier), "project_id": None}
            if project_id:
                body["project_id"] = identifier(project_id)
            record = {"request_id": request_id, "profile_name": name, "server": server,
                      "credential": credential, "verifier": verifier, "create_body": body,
                      "create_state": "PREPARED", "redeem_state": "PREPARED", "profile_saved": False}
            state.write(state.pairings, request_id, record)
        http = http_factory(record["server"], proof=record["verifier"])
        fresh = record["create_state"] == "PREPARED"
        if fresh:
            record["create_state"] = "SENT"
            state.write(state.pairings, request_id, record)
        try:
            view = (http.call("POST", AUTH_PREFIX + "/requests", body=record["create_body"])
                    if fresh else query_original(http, record, "CREATE"))
            if fresh:
                validate_operation(record, view, "CREATE")
            record_view(state, record, view)
            record["create_state"] = "ACKED"
            state.write(state.pairings, request_id, record)
        except CLIError as exc:
            record["create_state"] = "REJECTED" if fresh and 400 <= exc.status < 500 and exc.status != 408 else "UNKNOWN"
            state.write(state.pairings, request_id, record)
            return {**safe_view(record), "code": exc.code}, 3 if record["create_state"] == "REJECTED" else 4
        if record["redeem_state"] in {"SENT", "UNKNOWN", "ACKED"}:
            # A previous redeem may already have committed: only its original receipt can settle it.
            try:
                view = query_original(http, record, "REDEEM")
                record_view(state, record, view)
                record["redeem_state"] = "ACKED"
                save_bound(state, record)
            except CLIError as exc:
                return {**safe_view(record), "code": exc.code}, 5 if exc.exit_code == 5 else 4
            return safe_view(record), 0 if record.get("profile_saved") else 4
        if notify:
            notify({"request_id": request_id, "short_code": view.get("short_code"),
                    "verification_url": view.get("verification_url")})
        if open_browser and view["status"] == "PENDING":
            webbrowser.open(view["verification_url"])
        deadline = monotonic() + wait_seconds
        while view["status"] == "PENDING" and monotonic() < deadline:
            sleep(min(2, max(0, deadline - monotonic())))
            try:
                view = http.call("GET", AUTH_PREFIX + "/requests/" + request_id)
                record_view(state, record, view)
            except CLIError as exc:
                return {**safe_view(record), "code": exc.code}, 4
        if view["status"] == "BOUND":
            save_bound(state, record)
            return safe_view(record), 0
        if view["status"] != "APPROVED":
            return safe_view(record), 3 if view["status"] in {"DENIED", "EXPIRED"} else 4
        if record["redeem_state"] == "REJECTED":
            return {**safe_view(record), "code": "PAIRING_REDEEM_REJECTED"}, 3
        record["redeem_body"] = {"idempotency_key": str(uuid.uuid4()),
                                  "approval_digest": view["approval"]["approval_digest"]}
        record["redeem_state"] = "SENT"
        state.write(state.pairings, request_id, record)
        try:
            accepted = http.call("POST", AUTH_PREFIX + "/requests/" + request_id + "/redeem",
                                 body=record["redeem_body"])
            validate_operation(record, accepted, "REDEEM")
            record_view(state, record, accepted)
            record["redeem_state"] = "ACKED"
            state.write(state.pairings, request_id, record)
            # Verify the independently retrievable original operation, not just the POST response.
            recovered = query_original(http, record, "REDEEM")
            record_view(state, record, recovered)
            save_bound(state, record)
        except CLIError as exc:
            if record["redeem_state"] != "ACKED":
                record["redeem_state"] = "REJECTED" if 400 <= exc.status < 500 and exc.status != 408 else "UNKNOWN"
                state.write(state.pairings, request_id, record)
            code = 5 if exc.exit_code == 5 else (3 if record["redeem_state"] == "REJECTED" else 4)
            return {**safe_view(record), "code": exc.code}, code
        return safe_view(record), 0 if record.get("profile_saved") else 4


def logout(state: State, name: str) -> tuple[dict, int]:
    name = profile_name(name)
    with state.lock("profiles"):
        profile = state.read(state.profiles, name)
        profile["active"] = False
        state.write(state.profiles, name, profile)
    pending = []
    with state.ledger() as ledger:
        for key, current in ledger.journal.db.execute("SELECT key,state FROM intents"):
            if current not in {"READBACK_COMPLETE", "REJECTED"}:
                pending.append(key)
    return {"status": "LOGGED_OUT", "profile": name, "server_revoked": False,
            "pending_request_ids": pending}, 0
