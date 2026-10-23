"""Fixed official native Codex delegation profile, never a second Agent Loop."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socketserver
import stat
import threading
from pathlib import Path
from uuid import UUID

from .errors import CloudBlocked

HARNESS_SOURCE = "687f282e8625c6b8d11ff58211a90524be2e4317"
BUNDLE_VERSION = "0.2.1-rc.2"
CODEX_VERSION = "0.153.4"
PAYLOAD_PROFILE = "hypertest-official-codex-payload/v1"
OBSERVATION_PROFILE = "hypertest-native-delegation-observation/v1"
PAYLOAD_MOUNT = "/opt/hypertest-delegates"
NPM_PINS = {
    "@deepseek-ai/dsh-subagent-codex": {"version": BUNDLE_VERSION,
        "integrity": "sha512-ajbb0gFeDwNHE4cqKlFxmP77xsm6XsG2L55YDHWTSZVTjK3t6iSlmpwLY2tI08F7hkez6jgv4MqkVswC6IAQXA=="},
    "@openai/codex": {"version": CODEX_VERSION,
        "integrity": "sha512-wbHDmit7S/YvBGVX1DQmk13xtWblZ2cApeJ/pB7xDZ10Cna+DZc5ij7f0F4OxdsXN4FW1oLT48OpogUI1+8Y2w=="},
}


def validate_lock(document: dict) -> None:
    """Only a full registry lock with the exact researched official tarballs."""
    try:
        if document.get("lockfileVersion") != 3:
            raise ValueError()
        packages = document["packages"]
        for name, pin in NPM_PINS.items():
            installed = packages["node_modules/" + name]
            if installed.get("version") != pin["version"] or installed.get("integrity") != pin["integrity"]:
                raise ValueError()
        for name, package in packages.items():
            if name == "":
                continue
            if (not package.get("resolved", "").startswith("https://registry.npmjs.org/")
                    or not package.get("integrity", "").startswith("sha512-") or package.get("link")):
                raise ValueError()
    except Exception:
        raise CloudBlocked("DELEGATE_LOCK_INVALID", "Delegate preparation requires a complete reviewed registry lock with pinned official bundle integrity") from None


def request_limits(settings, *, remaining: int, allow_codex: bool) -> list[dict]:
    """Allocate one shared frozen budget; no provider gets a fresh full budget."""
    desired = [("ROOT", settings.cloud_model_max_requests, settings.cloud_model_request_cost_microunits)]
    if allow_codex:
        desired.append(("CODEX", settings.cloud_codex_max_requests, settings.cloud_codex_request_credits))
    if type(remaining) is not int or any(type(rate) is not int or rate <= 0 for _, _, rate in desired):
        raise CloudBlocked("MODEL_COST_UNCONFIGURED", "Configure a positive conservative request cost in the task's accounting unit")
    share = remaining // len(desired)
    limits = [{"scope": scope, "max_requests": min(maximum, share // rate),
               "cost_per_request_microunits": rate} for scope, maximum, rate in desired]
    if any(item["max_requests"] < 1 for item in limits):
        raise CloudBlocked("MODEL_BUDGET_EXHAUSTED", "The remaining shared budget cannot admit each configured model scope")
    leftover = remaining - sum(item["max_requests"] * item["cost_per_request_microunits"] for item in limits)
    for item, (_, maximum, rate) in zip(limits, desired, strict=True):
        additional = min(maximum - item["max_requests"], leftover // rate)
        item["max_requests"] += additional
        leftover -= additional * rate
    return limits


def verify_payload(root: Path, expected_sha256: str) -> dict:
    """Verify a preinstalled image payload against an operator-trusted digest.

    The digest must come from deployment configuration, never from the payload
    itself. Hashes establish integrity relative to that trust anchor, not an
    independent vendor signature or model acceptance.
    """
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise CloudBlocked("DELEGATE_PAYLOAD_UNTRUSTED", "Configure a reviewed immutable delegate manifest digest")
    try:
        root = root.absolute()
        if root.resolve() != root or root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o022:
            raise ValueError()
        raw = (root / "manifest.json").read_bytes()
        if len(raw) > 32 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError()
        manifest = json.loads(raw)
        if (manifest.get("profile") != PAYLOAD_PROFILE or manifest.get("source_commit") != HARNESS_SOURCE
                or manifest.get("bundle_version") != BUNDLE_VERSION
                or manifest.get("codex_version") != CODEX_VERSION):
            raise ValueError()
        files = manifest["files"]
        if not isinstance(files, dict) or not 3 <= len(files) <= 100000:
            raise ValueError()
        required = {"bin/node", "package-lock.json", "node_modules/@deepseek-ai/dsh-subagent-codex/package.json",
                    "node_modules/@deepseek-ai/dsh-subagent-codex/lib/index.js",
                    "node_modules/@openai/codex/package.json", "node_modules/@openai/codex/bin/codex.js"}
        if not required <= files.keys():
            raise ValueError()
        actual = set()
        for path in root.rglob("*"):
            info = path.lstat()
            if path.is_symlink() or info.st_mode & 0o022:
                raise ValueError()
            if stat.S_ISREG(info.st_mode) and path != root / "manifest.json":
                relative = path.relative_to(root).as_posix()
                actual.add(relative)
                if relative not in files or _file_digest(path) != files[relative]:
                    raise ValueError()
            elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError()
        if actual != files.keys() or not (root / "bin/node").stat().st_mode & 0o111:
            raise ValueError()
        validate_lock(json.loads((root / "package-lock.json").read_bytes()))
        for relative, name, version in (
            ("node_modules/@deepseek-ai/dsh-subagent-codex/package.json", "@deepseek-ai/dsh-subagent-codex", BUNDLE_VERSION),
            ("node_modules/@openai/codex/package.json", "@openai/codex", CODEX_VERSION),
        ):
            package = json.loads((root / relative).read_bytes())
            if package.get("name") != name or package.get("version") != version:
                raise ValueError()
        return {"profile": PAYLOAD_PROFILE, "manifest_sha256": expected_sha256,
                "source_commit": HARNESS_SOURCE, "bundle_version": BUNDLE_VERSION,
                "codex_version": CODEX_VERSION, "integrity_verified": True,
                "native_delegation_observed": False, "claude_code": "PLACEHOLDER"}
    except Exception:
        raise CloudBlocked("DELEGATE_PAYLOAD_INVALID", "The fixed official bundle, native CLI and Node payload must match the reviewed manifest") from None


def _file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def native_profile(*, model: str, codex_base_url: str) -> list[dict]:
    """A controlled official profile patch: no user argv, source or credentials."""
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", model):
        raise CloudBlocked("CODEX_MODEL_INVALID", "Select one fixed native Codex model")
    if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", codex_base_url):
        raise CloudBlocked("DELEGATE_RELAY_INVALID", "Delegate inference must use its isolated loopback relay")
    return [
        # Official patch `name` is an assertion, not a replacement. Disable the
        # original row and insert the subclass as the sole subprocess service.
        {"id": "subprocess", "disabled": True},
        {"insert": [
            {"id": "hypertest-native-subprocess", "name": "/app/hypertest/cloud/native_subprocess.mjs"},
            {"id": "subagent-codex", "name": PAYLOAD_MOUNT + "/node_modules/@deepseek-ai/dsh-subagent-codex/lib/index.js",
             "config": {"providerName": "codex", "model": model, "permissionMode": "never",
                        "env": {"HOME": "/home/agent/codex", "CODEX_HOME": "/home/agent/codex",
                                "HYPERTEST_CODEX_SENTINEL_KEY": "broker-managed", "NO_PROXY": "127.0.0.1,localhost"}}},
            {"id": "tool-subagent-codex", "name": "@deepseek-ai/dsh-tool-subagent",
             "config": {"provider": "codex", "toolName": "subagent_codex", "maxDepth": "provider-managed"}},
            {"id": "hypertest-delegation-observer", "name": "/app/hypertest/cloud/native_delegate.mjs"},
        ]},
    ]


def write_native_configuration(home: Path, *, model: str, codex_base_url: str) -> Path:
    patch = native_profile(model=model, codex_base_url=codex_base_url)
    native_home = home / "codex"
    native_home.mkdir(mode=0o700)
    # No auth.json is created. All native auth is a non-secret sentinel for the
    # model-only relay; the cloud OAuth remains in the host broker.
    configuration = "\n".join([
        "model = " + json.dumps(model), 'model_provider = "hypertest-cloud"',
        'approval_policy = "never"', 'sandbox_mode = "workspace-write"',
        'web_search = "disabled"', 'disable_response_storage = true',
        'check_for_update_on_startup = false', 'cli_auth_credentials_store = "file"',
        '[model_providers.hypertest-cloud]', 'name = "HyperTest Cloud model relay"',
        "base_url = " + json.dumps(codex_base_url + "/v1"),
        'env_key = "HYPERTEST_CODEX_SENTINEL_KEY"', 'wire_api = "responses"',
        'requires_openai_auth = false', 'supports_websockets = false',
        'request_max_retries = 0', 'stream_max_retries = 0',
        '[analytics]', 'enabled = false', '[features]', 'multi_agent = false', "",
    ])
    (native_home / "config.toml").write_text(configuration)
    patch_path = home / "native-delegation.patch.json"
    # JSON is also a YAML document accepted by the official patch loader.
    patch_path.write_text(json.dumps(patch))
    return patch_path


class DelegationObservations:
    """Bounded metadata projection of the fixed official lifecycle plugin.

    These are runtime-reported lifecycle facts, not independent execution
    provenance. Only the fenced Worker can submit them to the platform.
    """
    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.channel_closed = False

    def accept(self, event: dict) -> None:
        expected = {"profile", "run_id", "native_ref", "provider", "state", "stop_reason"}
        if self.channel_closed or not isinstance(event, dict) or set(event) != expected:
            raise CloudBlocked("DELEGATION_OBSERVATION_INVALID", "Delegate observation has an unsupported shape")
        try:
            UUID(event["run_id"])
            UUID(event["native_ref"])
        except (ValueError, TypeError, AttributeError):
            raise CloudBlocked("DELEGATION_OBSERVATION_INVALID", "Delegate lifecycle identity is invalid") from None
        if event["profile"] != OBSERVATION_PROFILE or event["provider"] != "codex":
            raise CloudBlocked("DELEGATION_OBSERVATION_INVALID", "Delegate provider is outside the admitted profile")
        state, reason = event["state"], event["stop_reason"]
        if ((state == "RUNNING" and reason is not None)
                or (state == "TERMINAL" and reason not in {"completed", "error", "aborted", "max-tokens", "refusal"})
                or state not in {"RUNNING", "TERMINAL"}):
            raise CloudBlocked("DELEGATION_OBSERVATION_INVALID", "Delegate state has no supported lifecycle meaning")
        previous = self.runs.get(event["run_id"])
        if previous is None:
            if state != "RUNNING" or len(self.runs) >= 128:
                raise CloudBlocked("DELEGATION_OBSERVATION_GAP", "Delegate terminal has no observed start or exceeds the attempt limit")
        elif (previous["native_ref"] != event["native_ref"] or previous["state"] == "TERMINAL" or state != "TERMINAL"):
            raise CloudBlocked("DELEGATION_OBSERVATION_CONFLICT", "Delegate lifecycle is inconsistent with its original start")
        self.runs[event["run_id"]] = dict(event)

    def terminal(self, native_ref: str) -> dict:
        matches = [item for item in self.runs.values() if item["native_ref"] == native_ref]
        if len(matches) != 1 or matches[0]["state"] != "TERMINAL":
            raise CloudBlocked("DELEGATION_NOT_TERMINAL", "Wait for the original native delegate's observed terminal")
        return matches[0]

    @property
    def all_terminal(self) -> bool:
        return all(item["state"] == "TERMINAL" for item in self.runs.values())


NATIVE_READY = {"profile": "hypertest-native-codex-profile/v1", "codex_version": CODEX_VERSION,
    "bundle_version": BUNDLE_VERSION, "provider_registered": True, "tool_registered": True,
    "subprocess_shim": True, "node_available": True, "model_started": False}


class DelegationMetadataError(ValueError):
    def __init__(self, category: str):
        self.channel_failure = category
        super().__init__("Native metadata is outside its fixed contract")


class DelegationChannel:
    """Namespace-private bounded plugin metadata, outside the SDK/session wire.

    Sequence/ACK/close detect a lost lifecycle frame; no platform credentials
    or authentication material are sent on this reported-observation channel.
    """
    def __init__(self, path: Path, *, on_delegation=None):
        self.path, self.on_delegation = path, on_delegation
        self.observations = DelegationObservations()
        self.ready, self.closed = threading.Event(), threading.Event()
        self.error = None
        self.sequence = 0
        self.lock = threading.Lock()

    def __enter__(self):
        channel = self
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(3)
                try:
                    raw = self.rfile.readline(8193)
                    if not raw:
                        raise DelegationMetadataError("EMPTY_EOF")
                    if len(raw) > 8192:
                        raise DelegationMetadataError("OVER_LIMIT")
                    if not raw.endswith(b"\n"):
                        raise DelegationMetadataError("MISSING_NEWLINE")
                    try:
                        frame = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise DelegationMetadataError("JSON") from None
                    channel.receive(frame)
                    self.wfile.write(b"ACK\n")
                    self.wfile.flush()
                except Exception as error:
                    with channel.lock:
                        if channel.error is None:
                            if isinstance(error, CloudBlocked):
                                channel.error = error
                            else:
                                channel.error = CloudBlocked("DELEGATION_METADATA_INVALID", "Native plugin metadata is incomplete or inconsistent")
                                channel.error.channel_failure = (error.channel_failure if isinstance(error, DelegationMetadataError)
                                    else "TIMEOUT" if isinstance(error, TimeoutError)
                                    else "TRANSPORT" if isinstance(error, OSError) else "OTHER")
        self.server = socketserver.UnixStreamServer(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def receive(self, frame: dict):
        with self.lock:
            if not isinstance(frame, dict) or set(frame) != {"sequence", "kind", "data"}:
                raise DelegationMetadataError("FRAME_KEYS")
            if type(frame["sequence"]) is not int or frame["sequence"] != self.sequence + 1:
                raise DelegationMetadataError("SEQUENCE")
            if self.closed.is_set():
                raise DelegationMetadataError("AFTER_CLOSED")
            if self.sequence >= 260:
                raise DelegationMetadataError("FRAME_LIMIT")
            kind, data = frame["kind"], frame["data"]
            if not isinstance(kind, str) or kind not in {"READY", "DELEGATION", "CLOSED"}:
                raise DelegationMetadataError("FRAME_KIND")
            if kind == "READY":
                if not isinstance(data, dict) or set(data) != set(NATIVE_READY):
                    raise DelegationMetadataError("READY_SHAPE")
                if data["model_started"] is not False:
                    raise DelegationMetadataError("READY_SHAPE")
                if any(data[key] != NATIVE_READY[key] for key in ("profile", "codex_version", "bundle_version")):
                    raise CloudBlocked("NATIVE_PAYLOAD_VERSION_MISMATCH", "Native composition version is outside the pinned profile")
                for key, code in (("provider_registered", "NATIVE_PROVIDER_UNAVAILABLE"),
                        ("tool_registered", "NATIVE_TOOL_UNAVAILABLE"), ("subprocess_shim", "NATIVE_SUBPROCESS_UNAVAILABLE"),
                        ("node_available", "NATIVE_NODE_UNAVAILABLE")):
                    if data[key] is not True:
                        error = CloudBlocked(code, "A required native composition capability is unavailable")
                        error.native_capabilities = {name: data[name] for name in (
                            "provider_registered", "tool_registered", "subprocess_shim", "node_available")}
                        raise error
            if kind == "READY" and not self.ready.is_set() and self.sequence == 0 and data == NATIVE_READY:
                self.ready.set()
            elif kind == "DELEGATION" and self.ready.is_set():
                self.observations.accept(data)
                if self.on_delegation is not None:
                    self.on_delegation(data)
            elif kind == "CLOSED" and self.ready.is_set() and data is None and self.observations.all_terminal:
                self.closed.set()
            else:
                category = {"READY": "READY_ORDER", "DELEGATION": "DELEGATION_ORDER", "CLOSED": "CLOSED_ORDER"}.get(kind, "FRAME_KIND")
                raise DelegationMetadataError(category)
            self.sequence = frame["sequence"]

    def ensure_ready(self):
        self.ready.wait(3)
        if self.error is not None:
            raise self.error
        if not self.ready.is_set():
            raise CloudBlocked("NATIVE_PROFILE_UNAVAILABLE", "The official provider/tool/Node composition did not report readiness")
        return dict(NATIVE_READY)

    def ensure_closed(self):
        self.closed.wait(3)
        if self.error is not None:
            raise self.error
        if not self.closed.is_set():
            raise CloudBlocked("DELEGATION_METADATA_INCOMPLETE", "Native lifecycle metadata did not close cleanly; do not infer completion")

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.path.unlink(missing_ok=True)
