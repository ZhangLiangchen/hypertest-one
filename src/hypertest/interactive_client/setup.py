"""Explicit operator setup, separate from the Agent's public MCP tools.

One-time secrets cannot be recovered from the current registration APIs. Every
POST is fenced by a durable UNKNOWN intent before sending; an interrupted setup
therefore requires administrator reconciliation, never automatic reissuance.
"""
from __future__ import annotations

import fcntl
import getpass
import hashlib
import json
import os
import ssl
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from hypertest.interactive_client import MAX_MESSAGE, PROFILE
from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.security import private_create, private_read

READ_SCOPES = ["task:submit", "run:read", "evidence:read", "report:read"]
ADAPTER = "codex-desktop-stdio/v1"
SCHEMA = "hypertest.interactive-setup/v1"


def _directory(path: Path) -> Path:
    """Canonicalize the home once, but reject symlinks within private paths."""
    path = path.expanduser().absolute()
    # /var and /tmp are system aliases on macOS. Resolve their existing parent
    # before creating anything, then require every private component to be real.
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise ClientError("PRIVATE_DIRECTORY_REQUIRED")
        resolved = path.resolve(strict=True)
    else:
        # New installation parents are private too. Existing conventional roots
        # such as ~/.config need not themselves be 0700.
        if not path.parent.exists():
            _directory(path.parent)
        parent = path.parent.resolve(strict=True)
        resolved = parent / path.name
        resolved.mkdir(mode=0o700)
    info = resolved.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ClientError("PRIVATE_DIRECTORY_REQUIRED")
    return resolved


def _json_read(path: Path) -> dict:
    try:
        value = json.loads(private_read(path))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (ValueError, UnicodeError) as exc:
        raise ClientError("INVALID_SETUP_STATE") from exc


def _check_state(state: dict, request: dict | None = None) -> None:
    try:
        identity = state["client_instance_id"]
        if (state["schema_version"] != SCHEMA or _uuid(identity) != identity
                or state["node_key"] != "mcp-" + UUID(identity).hex
                or state["actor_ref"] != state["node_key"]
                or not isinstance(state["steps"], dict)
                or not set(state["steps"]) <= {"pair", "harness", "registration"}
                or not isinstance(state["request"], dict)):
            raise ValueError
        if request is not None and state["request"] != request:
            raise ClientError("SETUP_IDENTITY_CONFLICT")
        for step, value in state["steps"].items():
            if not isinstance(value, dict):
                raise ValueError
            if value.get("status") != "COMPLETED":
                raise ClientError("SETUP_UNKNOWN_" + step.upper() + "_ADMIN_RECONCILIATION_REQUIRED")
            result = value["result"]
            expected = {"node_id", "grant_id"} if step == "pair" else (
                {"capability_id"} if step == "harness" else {"grant_id", "actor_identity_id"})
            if set(result) != expected:
                raise ValueError
            for identifier in result.values():
                _uuid(identifier)
        if ("harness" in state["steps"] or "registration" in state["steps"]) and "pair" not in state["steps"]:
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ClientError("INVALID_SETUP_STATE") from exc


def _save(path: Path, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()
    if path.exists() or path.is_symlink():
        private_read(path)
    temporary = path.with_name("." + path.name + "." + uuid4().hex)
    try:
        private_create(temporary, raw)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lock(directory: Path):
    descriptor = os.open(directory / "setup.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ClientError("PRIVATE_FILE_REQUIRED")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ClientError("SETUP_ALREADY_RUNNING") from exc
        yield
    finally:
        os.close(descriptor)


def _api_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or any(c.isspace() for c in value) or parsed.path.rstrip("/") != "/api/v1"
                or parsed.port == 0):
            raise ValueError
    except ValueError as exc:
        raise ClientError("HTTPS_API_BASE_REQUIRED") from exc
    return value.rstrip("/")


def _secret(path: Path | None) -> str:
    if path is not None:
        raw = private_read(path, max_bytes=4096).decode().strip()
    else:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ClientError("OPERATOR_KEY_FILE_OR_PRIVATE_TTY_REQUIRED")
        raw = getpass.getpass("HyperTest device management key (hidden): ").strip()
    if not raw or len(raw) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
        raise ClientError("INVALID_OPERATOR_KEY_FILE")
    return raw


def _http(api_url: str, ca_file: Path | None, *, transport=None) -> httpx.Client:
    try:
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    except (OSError, ssl.SSLError) as exc:
        raise ClientError("TRUSTED_CA_FILE_REQUIRED") from exc
    return httpx.Client(base_url=api_url + "/", verify=context, timeout=30,
                        follow_redirects=False, trust_env=False, transport=transport)


def _request(client: httpx.Client, method: str, path: str, *, headers=None, payload=None,
             params=None):
    try:
        with client.stream(method, path, headers=headers, json=payload, params=params) as response:
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_MESSAGE:
                    raise ClientError("SETUP_RESPONSE_TOO_LARGE")
            if not 200 <= response.status_code < 300:
                # Response text may echo secrets, proxy internals or source data.
                raise ClientError("SETUP_AUTHORIZATION_OR_REQUEST_REJECTED")
            return json.loads(raw)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise ClientError("SETUP_PLATFORM_UNAVAILABLE") from exc
    except (ValueError, UnicodeError) as exc:
        raise ClientError("INVALID_SETUP_RESPONSE") from exc


def _uuid(value) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ClientError("INVALID_SETUP_RESPONSE") from exc


def _token(value) -> bytes:
    if (not isinstance(value, str) or not 16 <= len(value) <= 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise ClientError("INVALID_SETUP_RESPONSE")
    return value.encode()


def _preflight(client: httpx.Client, project_id: str, headers: dict) -> list:
    profile = _request(client, "GET", "interactive/capabilities")
    if not isinstance(profile, dict) or profile.get("profile") != PROFILE:
        raise ClientError("INTERACTIVE_PROFILE_UNSUPPORTED")
    project = _request(client, "GET", "projects/" + project_id)
    if not isinstance(project, dict) or project.get("id") != project_id:
        raise ClientError("SETUP_PROJECT_NOT_FOUND")
    nodes = _request(client, "GET", "harness-nodes", headers=headers)
    if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
        raise ClientError("INVALID_SETUP_RESPONSE")
    return nodes


def _completed(state: dict) -> bool:
    names = ["pair", "registration"] + (["harness"] if state["request"]["host"] == "codex-desktop" else [])
    return all(state["steps"].get(name, {}).get("status") == "COMPLETED" for name in names)


def _post(state: dict, state_path: Path, name: str, client: httpx.Client, route: str,
          headers: dict, payload: dict, accept):
    previous = state["steps"].get(name)
    if previous:
        if previous.get("status") != "COMPLETED":
            raise ClientError("SETUP_UNKNOWN_" + name.upper() + "_ADMIN_RECONCILIATION_REQUIRED")
        return previous["result"]
    # UNKNOWN is durable before any bytes leave this process. No exception path
    # replaces it with a retryable state; these APIs issue one-time credentials.
    state["steps"][name] = {"status": "UNKNOWN", "request": payload}
    _save(state_path, state)
    try:
        result = accept(_request(client, "POST", route, headers=headers, payload=payload))
        state["steps"][name].update(status="COMPLETED", result=result)
        _save(state_path, state)
    except (ClientError, OSError, ValueError, TypeError, KeyError) as exc:
        raise ClientError("SETUP_UNKNOWN_" + name.upper() + "_ADMIN_RECONCILIATION_REQUIRED") from exc
    return result


def setup(*, api_url: str, project_id: str, directory: Path,
          operator_key_file: Path | None = None, ca_file: Path | None = None,
          name: str = "My computer", host: str = "generic", transport=None) -> dict:
    """Pair one new installation; repeating it preserves its exact identities."""
    if os.name != "posix":
        raise ClientError("POSIX_HOST_REQUIRED")
    api_url = _api_url(api_url)
    project_id = _uuid(project_id)
    if host not in {"generic", "codex-desktop"} or not name.strip() or len(name) > 128:
        raise ClientError("INVALID_SETUP_OPTIONS")
    directory = _directory(directory)
    ca_file = ca_file.expanduser().resolve(strict=True) if ca_file else None
    short_root = _directory(Path.home().resolve() / ".hypertest")
    short_id = hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    runtime = _directory(short_root / short_id)
    if len(os.fsencode(runtime / "interactive.sock")) >= 104:
        raise ClientError("SHORT_PRIVATE_STATE_DIRECTORY_REQUIRED")
    request = {"api_url": api_url, "project_id": project_id, "name": name,
               "host": host, "ca_file": str(ca_file) if ca_file else None}
    with _lock(directory):
        state_path = directory / "setup.json"
        if state_path.exists() or state_path.is_symlink():
            state = _json_read(state_path)
            _check_state(state, request)
            # An unknown step never causes another request, even after restart.
        else:
            # Never overwrite unrelated/preexisting credentials or client config.
            if any((directory / filename).exists() or (directory / filename).is_symlink()
                   for filename in ("client.json", "device.token", "integration.token")):
                raise ClientError("SETUP_DIRECTORY_ALREADY_CONFIGURED")
            installation = uuid4()
            state = {"schema_version": SCHEMA, "request": request,
                     "client_instance_id": str(installation),
                     "node_key": "mcp-" + installation.hex,
                     "actor_ref": "mcp-" + installation.hex,
                     "steps": {}}
            _save(state_path, state)
        operator = _secret(operator_key_file)
        headers = {"X-Hypertest-Operator-Key": operator}
        with _http(api_url, ca_file, transport=transport) as client:
            nodes = _preflight(client, project_id, headers)
            paired = state["steps"].get("pair", {}).get("result")
            if paired:
                matching = [n for n in nodes if n.get("id") == paired["node_id"]
                            and n.get("node_key") == state["node_key"]
                            and n.get("registration_status") == "ACTIVE"]
                if len(matching) != 1:
                    raise ClientError("SETUP_DEVICE_REVOKED_OR_MISMATCHED")
                private_read(directory / "device.token", max_bytes=4096)
            elif any(n.get("node_key") == state["node_key"] for n in nodes):
                raise ClientError("SETUP_EXISTING_NODE_ADMIN_RECONCILIATION_REQUIRED")

            def accept_pair(value):
                node = value["node"]
                if node["node_key"] != state["node_key"] or node["registration_status"] != "ACTIVE":
                    raise ClientError("INVALID_SETUP_RESPONSE")
                result = {"node_id": _uuid(node["id"]), "grant_id": _uuid(value["grant_id"])}
                private_create(directory / "device.token", _token(value["device_token"]))
                return result

            paired = _post(state, state_path, "pair", client, "harness-nodes/pair", headers,
                           {"node_key": state["node_key"], "display_name": name,
                            "expires_in_days": 30}, accept_pair)
            if host == "codex-desktop":
                capability = {"project_id": project_id, "capability": "harness",
                              "constraints": {"interactive_host_adapters": [ADAPTER]},
                              "policy_version": "interactive-setup-v1"}
                route = "harness-nodes/" + paired["node_id"] + "/capabilities"
                if state["steps"].get("harness"):
                    found = _request(client, "GET", route, headers=headers)
                    previous = state["steps"]["harness"]["result"]["capability_id"]
                    if not isinstance(found, list) or not any(
                            isinstance(c, dict) and c.get("id") == previous
                            and c.get("status") == "ACTIVE"
                            and all(c.get(k) == v for k, v in capability.items()) for c in found):
                        raise ClientError("SETUP_HARNESS_REVOKED_OR_MISMATCHED")

                def accept_harness(value):
                    if value["status"] != "ACTIVE":
                        raise ClientError("INVALID_SETUP_RESPONSE")
                    return {"capability_id": _uuid(value["id"])}

                _post(state, state_path, "harness", client, route, headers, capability, accept_harness)
            scopes = READ_SCOPES + (["run:execute"] if host == "codex-desktop" else [])

            def accept_registration(value):
                if (value["project_id"] != project_id
                        or value["client_instance_id"] != state["client_instance_id"]
                        or sorted(value["scopes"]) != sorted(scopes)):
                    raise ClientError("INVALID_SETUP_RESPONSE")
                result = {"grant_id": _uuid(value["grant_id"]),
                          "actor_identity_id": _uuid(value["actor_identity_id"])}
                private_create(directory / "integration.token", _token(value["integration_token"]))
                return result

            _post(state, state_path, "registration", client, "interactive/registrations", headers,
                  {"actor_ref": state["actor_ref"], "client_instance_id": state["client_instance_id"],
                   "project_id": project_id, "scopes": scopes, "expires_in_days": 30},
                  accept_registration)
            if not _completed(state):
                raise ClientError("SETUP_INCOMPLETE")
        # No operator credential is stored in either setup state or runtime config.
        del operator, headers
        config_path = directory / "client.json"
        config = {"api_url": api_url, "state_dir": str(runtime),
                  "integration_token_file": str(directory / "integration.token"),
                  "device_token_file": str(directory / "device.token"), "node_id": paired["node_id"],
                  "host_adapter": {"kind": "codex-desktop-stdio" if host == "codex-desktop" else "unsupported"},
                  "workspaces": {}}
        if ca_file:
            config["ca_file"] = str(ca_file)
        if config_path.exists() or config_path.is_symlink():
            existing = ClientConfig.load(config_path)
            # Preserve later controlled workspace registrations and daemon state.
            actual = existing.model_dump(mode="json")
            if any(actual.get(k) != v for k, v in config.items() if k != "workspaces"):
                raise ClientError("SETUP_CLIENT_CONFIGURATION_CONFLICT")
        else:
            _save(config_path, config)
        checked = doctor(config_path, transport=transport)
        return {"status": "CONFIGURED", "config_path": str(config_path),
                "node_id": paired["node_id"], "client_instance_id": state["client_instance_id"],
                "registration_id": state["steps"]["registration"]["result"]["grant_id"],
                "project_id": project_id, "host_mode": host, "doctor": checked,
                "next_step": "Register the path-only stdio configuration in your Agent, then reload its MCP tools.",
                "local_execution": "Requires separate accepted source, controlled workspace and explicit live host binding.",
                "source_acquisition_granted": False, "issue_executor_granted": False}


def doctor(config_path: Path, *, transport=None) -> dict:
    """Read-only installation/profile check; never binds a session or starts a daemon."""
    config_path = config_path.expanduser()
    if config_path.is_symlink():
        raise ClientError("PRIVATE_FILE_REQUIRED")
    config_path = config_path.resolve(strict=True)
    config = ClientConfig.load(config_path)
    _api_url(config.api_url)
    _directory(config.state_dir)
    integration = private_read(config.integration_token_file, max_bytes=4096).decode().strip()
    state_path = config_path.parent / "setup.json"
    state = _json_read(state_path) if state_path.exists() else None
    if state:
        _check_state(state)
        if (state["request"]["api_url"] != config.api_url
                or state["steps"].get("pair", {}).get("result", {}).get("node_id") != config.node_id):
            raise ClientError("SETUP_CLIENT_CONFIGURATION_CONFLICT")
    with _http(config.api_url, config.ca_file, transport=transport) as client:
        profile = _request(client, "GET", "interactive/capabilities")
        if not isinstance(profile, dict) or profile.get("profile") != PROFILE:
            raise ClientError("INTERACTIVE_PROFILE_UNSUPPORTED")
        authorization_checked = False
        if state:
            _request(client, "GET", "interactive/submissions/by-key",
                     headers={"Authorization": "Bearer " + integration,
                              "X-Hypertest-Interactive-Profile": PROFILE},
                     params={"project_id": state["request"]["project_id"],
                             "submission_key": "setup-check:" + state["client_instance_id"]})
            authorization_checked = True
    selected = config.host_adapter.get("kind") == "codex-desktop-stdio"
    return {"status": "READY", "profile": PROFILE, "private_files": "CHECKED",
            "integration_authorization": "CHECKED" if authorization_checked else "NOT_PROBED",
            "device_authorization": "PRIVATE_FILE_CHECKED_NOT_LIVE_PROBED",
            "submission_and_reads": authorization_checked, "cloud_execution": authorization_checked,
            "local_execution": "CONTROLLED_HOST_BINDING_REQUIRED" if selected else "HOST_UNSUPPORTED",
            "execution_bound": False}
