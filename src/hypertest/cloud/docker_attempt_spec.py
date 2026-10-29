"""Closed candidate for a fixed, per-Attempt Docker guard specification.

This module does not contact Docker or enable the Cloud Worker. The caller must
obtain limits and mount identity from the trusted Engine and account for every
relevant sibling before the candidate can be admitted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from uuid import UUID

_GUARD = "/opt/hypertest-cloud/venv/bin/python"
_MAX_MEMORY_SWAP = 4 * 1024**3
_MAX_PIDS = 256
_HEX = re.compile(r"^[a-f0-9]{64}$")
_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_RUNTIME = {"user": "997:988", "network": "none", "ipc": "private", "pid": "private",
    "cap_drop": ["ALL"], "no_new_privileges": True, "readonly_root": True, "restart": "no", "log_driver": "none",
    "workdir": "/workspace", "tmpfs": "/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777",
    "entrypoint": [_GUARD, "-I", "-m", "hypertest.cloud.container_guard"]}
_MASKED = {"/proc/acpi", "/proc/asound", "/proc/interrupts", "/proc/kcore", "/proc/keys",
    "/proc/latency_stats", "/proc/sched_debug", "/proc/scsi", "/proc/timer_list", "/proc/timer_stats",
    "/sys/devices/virtual/powercap", "/sys/firmware"}
_READONLY = {"/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger"}


def _reject():
    raise ValueError("invalid Cloud Docker attempt specification")


def _uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            _reject()
    except (ValueError, AttributeError):
        _reject()
    return value


@dataclass(frozen=True)
class ResourceLimit:
    """Docker's memory_swap is the combined memory plus swap ceiling."""
    memory: int
    memory_swap: int
    pids: int

    def validate(self):
        if (type(self.memory) is not int or type(self.memory_swap) is not int or type(self.pids) is not int
                or not 0 < self.memory <= self.memory_swap <= _MAX_MEMORY_SWAP or not 0 < self.pids <= _MAX_PIDS):
            _reject()


def check_aggregate(*, worker_id: str, existing: dict[str, ResourceLimit], attempt: ResourceLimit):
    """Check all trusted, separately observed sibling limits, including Worker.

    Completeness and identity of ``existing`` must be established by the caller;
    this calculation does not inspect Docker or attest actual memory use.
    """
    if (not isinstance(existing, dict) or worker_id not in existing or not existing
            or any(not isinstance(identity, str) or _HEX.fullmatch(identity) is None for identity in existing)):
        _reject()
    attempt.validate()
    for limit in existing.values():
        if not isinstance(limit, ResourceLimit):
            _reject()
        limit.validate()
    if (sum(limit.memory_swap for limit in existing.values()) + attempt.memory_swap > _MAX_MEMORY_SWAP
            or sum(limit.pids for limit in existing.values()) + attempt.pids > _MAX_PIDS):
        _reject()


def _mounts(volume: str, attempt_id: str) -> list[dict]:
    if not isinstance(volume, str) or _VOLUME.fullmatch(volume) is None:
        _reject()
    root = "attempt-" + _uuid(attempt_id)
    return [{"Type": "volume", "Source": volume, "Target": target, "ReadOnly": readonly,
             "VolumeOptions": {"Subpath": root + "/" + subpath}}
            for target, readonly, subpath in (("/workspace", False, "workspace"),
                ("/workspace/sut", True, "workspace/sut"), ("/home/agent", False, "dsh-home"),
                ("/run", True, "broker"))]


def build_spec(*, project_id: str, task_id: str, attempt_id: str, generation: int,
               container_name: str, image_id: str, image_revision: str, image_environment: dict[str, str], volume_name: str, mounts: list[dict],
               key_sha256: str, clock_sha256: str, deadline_epoch: int, attempt_limit: ResourceLimit,
               worker_id: str, existing_limits: dict[str, ResourceLimit]) -> dict:
    """Construct a bounded create request; no caller-supplied command or paths."""
    for item in (project_id, task_id, attempt_id):
        _uuid(item)
    if (type(generation) is not int or not 1 <= generation < 10**18 or not isinstance(container_name, str)
            or container_name != "hypertest-attempt-" + UUID(attempt_id).hex + "-" + container_name[-32:]
            or not re.fullmatch(r"hypertest-attempt-[a-f0-9]{32}-[a-f0-9]{32}", container_name)
            or not isinstance(image_id, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", image_id) is None
            or not isinstance(image_revision, str) or re.fullmatch(r"[a-f0-9]{40}", image_revision) is None
            or not isinstance(key_sha256, str) or _HEX.fullmatch(key_sha256) is None
            or not isinstance(clock_sha256, str) or _HEX.fullmatch(clock_sha256) is None
            or type(deadline_epoch) is not int or not 0 < deadline_epoch < 10**12
            or mounts != _mounts(volume_name, attempt_id)):
        _reject()
    check_aggregate(worker_id=worker_id, existing=existing_limits, attempt=attempt_limit)
    scope = {"project_id": project_id, "task_id": task_id, "attempt_id": attempt_id,
             "generation": generation, "key_sha256": key_sha256, "clock_sha256": clock_sha256, "deadline_epoch": deadline_epoch}
    spec = {"profile": "cloud-docker-attempt-spec/v1", "container_name": container_name,
        "image_id": image_id, "image_revision": image_revision, "image_environment": image_environment, "scope": scope, "mounts": mounts,
        "runtime": copy.deepcopy(_RUNTIME),
        "resources": {"memory": attempt_limit.memory, "memory_swap": attempt_limit.memory_swap, "pids": attempt_limit.pids},
        "envelope": {"worker_id": worker_id, "existing": {identity: {"memory": limit.memory,
            "memory_swap": limit.memory_swap, "pids": limit.pids} for identity, limit in existing_limits.items()}}}
    spec["spec_sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _validate_spec(spec)
    return spec


def _validate_spec(spec: dict) -> None:
    from hypertest.cloud.container_guard import _GUARD_ENV

    if not isinstance(spec, dict) or set(spec) != {"profile", "container_name", "image_id", "image_revision", "image_environment", "scope", "mounts", "runtime", "resources", "envelope", "spec_sha256"}:
        _reject()
    check = dict(spec)
    digest = check.pop("spec_sha256", None)
    if not isinstance(digest, str) or _HEX.fullmatch(digest) is None or hashlib.sha256(
            json.dumps(check, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != digest:
        _reject()
    scope, resources, mounts = spec["scope"], spec["resources"], spec["mounts"]
    image_env = spec["image_environment"]
    if (spec["profile"] != "cloud-docker-attempt-spec/v1" or spec["runtime"] != _RUNTIME
            or not isinstance(image_env, dict) or set(image_env) - _GUARD_ENV
            or any(key.startswith("HYPERTEST_CLOUD_") or not isinstance(value, str) or len(value) > 2048 or "\x00" in value
                   for key, value in image_env.items()) or not isinstance(scope, dict)
            or set(scope) != {"project_id", "task_id", "attempt_id", "generation", "key_sha256", "clock_sha256", "deadline_epoch"}
            or not isinstance(resources, dict) or set(resources) != {"memory", "memory_swap", "pids"}
            or not isinstance(mounts, list) or not mounts or not isinstance(mounts[0], dict)):
        _reject()
    for field in ("project_id", "task_id", "attempt_id"):
        _uuid(scope[field])
    name = spec["container_name"]
    if (not isinstance(name, str) or re.fullmatch(r"hypertest-attempt-[a-f0-9]{32}-[a-f0-9]{32}", name) is None
            or name.split("-")[2] != UUID(scope["attempt_id"]).hex
            or not isinstance(spec["image_id"], str) or re.fullmatch(r"sha256:[a-f0-9]{64}", spec["image_id"]) is None
            or not isinstance(spec["image_revision"], str) or re.fullmatch(r"[a-f0-9]{40}", spec["image_revision"]) is None
            or type(scope["generation"]) is not int or not 1 <= scope["generation"] < 10**18
            or not isinstance(scope["key_sha256"], str) or _HEX.fullmatch(scope["key_sha256"]) is None
            or not isinstance(scope["clock_sha256"], str) or _HEX.fullmatch(scope["clock_sha256"]) is None
            or type(scope["deadline_epoch"]) is not int or not 0 < scope["deadline_epoch"] < 10**12
            or mounts != _mounts(mounts[0].get("Source"), scope["attempt_id"])):
        _reject()
    try:
        envelope = spec["envelope"]
        if not isinstance(envelope, dict) or set(envelope) != {"worker_id", "existing"} or not isinstance(envelope["existing"], dict):
            _reject()
        check_aggregate(worker_id=envelope["worker_id"], existing={identity: ResourceLimit(**limit)
            for identity, limit in envelope["existing"].items()}, attempt=ResourceLimit(**resources))
    except (TypeError, KeyError):
        _reject()


def _guard_environment(spec: dict) -> dict:
    _validate_spec(spec)
    digest = spec["spec_sha256"]
    scope = spec["scope"]
    env = {"HYPERTEST_CLOUD_CONTAINER_DEADLINE": str(scope["deadline_epoch"]),
           "HYPERTEST_CLOUD_GUARD_PROFILE": "WATCHDOG_V1", "HYPERTEST_CLOUD_GUARD_SPEC_SHA256": digest}
    for key in ("project_id", "task_id", "attempt_id", "generation", "key_sha256", "clock_sha256"):
        env["HYPERTEST_CLOUD_GUARD_" + key.upper()] = str(scope[key])
    return env


def create_body(spec: dict) -> dict:
    """Fixed Docker Engine create body; the name is separately fixed by spec."""
    guard_env = _guard_environment(spec)
    scope, resources = spec["scope"], spec["resources"]
    labels = {"hypertest.cloud." + key: str(scope[key]) for key in ("project_id", "task_id", "attempt_id", "generation")}
    labels["hypertest.cloud.worker_id"] = spec["envelope"]["worker_id"]
    return {"Image": spec["image_id"], "User": "997:988", "Entrypoint": [_GUARD],
        "Cmd": ["-I", "-m", "hypertest.cloud.container_guard"], "WorkingDir": "/workspace",
        "Env": [key + "=" + value for key, value in sorted((spec["image_environment"] | guard_env).items())],
        "Labels": labels, "AttachStdin": True, "OpenStdin": True, "StdinOnce": True, "Tty": False,
        "HostConfig": {"NetworkMode": "none", "IpcMode": "private", "CgroupnsMode": "private", "ReadonlyRootfs": True,
            "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"], "Memory": resources["memory"],
            "MemorySwap": resources["memory_swap"], "PidsLimit": resources["pids"], "AutoRemove": False,
            "RestartPolicy": {"Name": "no"}, "LogConfig": {"Type": "none", "Config": {}},
            "Tmpfs": {"/tmp": "rw,exec,nosuid,nodev,size=64m,mode=1777"}, "Mounts": copy.deepcopy(spec["mounts"])}}


def create_argv(spec: dict) -> list[str]:
    """Render Docker CLI arguments without granting any Docker transport access."""
    env = _guard_environment(spec)
    scope, resources = spec["scope"], spec["resources"]
    argv = ["create", "-i", "--name", spec["container_name"], "--user", "997:988", "--network", "none",
            "--ipc", "private", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
            "--memory", str(resources["memory"]), "--memory-swap", str(resources["memory_swap"]),
            "--pids-limit", str(resources["pids"]), "--restart", "no", "--log-driver", "none",
            "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777", "--workdir", "/workspace"]
    for key, value in sorted(env.items()):
        argv.extend(["--env", key + "=" + value])
    for key in ("project_id", "task_id", "attempt_id", "generation"):
        argv.extend(["--label", "hypertest.cloud." + key + "=" + str(scope[key])])
    argv.extend(["--label", "hypertest.cloud.worker_id=" + spec["envelope"]["worker_id"]])
    for mount in spec["mounts"]:
        argument = "type=volume,src=" + mount["Source"] + ",dst=" + mount["Target"] + ",volume-subpath=" + mount["VolumeOptions"]["Subpath"]
        if mount["ReadOnly"]:
            argument += ",readonly"
        argv.extend(["--mount", argument])
    return argv + ["--entrypoint", _GUARD, spec["image_id"], "-I", "-m", "hypertest.cloud.container_guard"]


def verify_envelope(spec: dict, observed: dict[str, ResourceLimit]) -> None:
    """Compare fixed limits to fresh trusted Engine observations for every listed member."""
    _validate_spec(spec)
    expected = {identity: ResourceLimit(**limit) for identity, limit in spec["envelope"]["existing"].items()}
    if observed != expected:
        _reject()


def verify_inspect(spec: dict, *, container_id: str, observed: dict) -> dict:
    """Check exact Engine identity/security; return bounded state, never raw config."""
    from hypertest.cloud.container_guard import _GUARD_ENV

    _validate_spec(spec)
    if not isinstance(container_id, str) or _HEX.fullmatch(container_id) is None or not isinstance(observed, dict):
        _reject()
    try:
        config, host, state, scope = observed["Config"], observed["HostConfig"], observed["State"], spec["scope"]
        env_pairs = [item.split("=", 1) for item in config["Env"]]
        if any(len(item) != 2 for item in env_pairs) or len(dict(env_pairs)) != len(env_pairs):
            _reject()
        env = dict(env_pairs)
        required_env = {"HYPERTEST_CLOUD_CONTAINER_DEADLINE": str(scope["deadline_epoch"]),
            "HYPERTEST_CLOUD_GUARD_PROFILE": "WATCHDOG_V1", "HYPERTEST_CLOUD_GUARD_SPEC_SHA256": spec["spec_sha256"]}
        required_env.update({"HYPERTEST_CLOUD_GUARD_" + key.upper(): str(scope[key])
            for key in ("project_id", "task_id", "attempt_id", "generation", "key_sha256", "clock_sha256")})
        labels = {"hypertest.cloud." + key: str(scope[key]) for key in ("project_id", "task_id", "attempt_id", "generation")}
        labels["hypertest.cloud.worker_id"] = spec["envelope"]["worker_id"]
        labels["org.opencontainers.image.revision"] = spec["image_revision"]
        mounts = [{"Type": item["Type"], "Source": item["Source"], "Target": item["Target"],
                   "ReadOnly": item.get("ReadOnly", False), "VolumeOptions": item["VolumeOptions"]}
                  for item in host["Mounts"]]
        if (observed["Id"] != container_id or observed["Name"] != "/" + spec["container_name"]
                or observed["Image"] != spec["image_id"] or config["User"] != "997:988"
                or config["Entrypoint"] != [_GUARD] or config["Cmd"] != ["-I", "-m", "hypertest.cloud.container_guard"]
                or config["WorkingDir"] != "/workspace" or config["Labels"] != labels
                or env != (spec["image_environment"] | required_env) or set(env) - _GUARD_ENV
                or not config["AttachStdin"] or not config["OpenStdin"] or not config["StdinOnce"] or config["Tty"]
                or config.get("Volumes") or config.get("Healthcheck")
                or host["Privileged"] or not host["ReadonlyRootfs"] or host["NetworkMode"] != "none"
                or host["PidMode"] not in ("", "private") or host["IpcMode"] != "private"
                or host.get("UTSMode") or host.get("UsernsMode")
                or host["CgroupnsMode"] != "private" or host["CapDrop"] != ["ALL"]
                or host["SecurityOpt"] != ["no-new-privileges"] or host["CapAdd"]
                or host["Memory"] != spec["resources"]["memory"] or host["MemorySwap"] != spec["resources"]["memory_swap"]
                or host["PidsLimit"] != spec["resources"]["pids"] or mounts != spec["mounts"]
                or host["Tmpfs"] != {"/tmp": "rw,exec,nosuid,nodev,size=64m,mode=1777"}
                or host["RestartPolicy"]["Name"] != "no" or host["AutoRemove"] or host["LogConfig"]["Type"] != "none"
                or host.get("Binds") or host.get("VolumesFrom") or host.get("Devices") or host.get("DeviceRequests") or host.get("DeviceCgroupRules")
                or host.get("GroupAdd") or host.get("PortBindings") or host["PublishAllPorts"] or host.get("Sysctls")
                or host.get("Init") or set(host["MaskedPaths"]) != _MASKED or set(host["ReadonlyPaths"]) != _READONLY):
            _reject()
        if (not isinstance(state["Status"], str) or type(state["Running"]) is not bool
                or type(state["Pid"]) is not int or type(state["ExitCode"]) is not int):
            _reject()
        return {"container_id": container_id, "status": state["Status"], "running": state["Running"],
                "pid": state["Pid"], "exit_code": state["ExitCode"], "source": "DOCKER_ENGINE_INSPECT",
                "cgroup_independently_observed": False}
    except (TypeError, KeyError, AttributeError, ValueError):
        _reject()
