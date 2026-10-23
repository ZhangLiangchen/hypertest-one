"""Linux namespace boundary with no general network or host credential mounts.

Workspace-local frameworks and optional host-mediated fixed SSH diagnostics.
The namespace itself has no general network or SSH credentials. Model HTTPS
and fixed environment actions use distinct host Unix brokers.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import signal
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import CloudBlocked
from .resources import inspect_resource_envelope
from .ssh_profile import SSH_SOCKET, SshProfile, validate_profile

ROOT_ADDRESS_SPACE_BYTES = 4 * 1024**3
NATIVE_CODEX_ADDRESS_SPACE_BYTES = 16 * 1024**3


def require_cloud_environment_route(environment: dict) -> None:
    """A route only narrows access; WEB_ONLY never grants an HTTPS runtime."""
    route = environment.get("cloud_access_policy")
    if route == "LOCAL_ONLY":
        raise CloudBlocked("LOCAL_MODE_REQUIRED", "This environment requires a separately authorized Local task")
    if route == "WEB_ONLY" and environment.get("connection") != "HTTPS":
        raise CloudBlocked("CLOUD_WEB_ONLY", "This environment permits only a separately admitted HTTPS capability")
    if route not in (None, "LOCAL_ONLY", "WEB_ONLY"):
        raise CloudBlocked("CLOUD_ACCESS_POLICY_INVALID", "Unknown environment routing restriction")


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_seconds: int
    max_model_requests: int
    max_tokens: int
    # RLIMIT_AS limits virtual address space, not physical RAM. The pinned
    # Codex Code Mode V8 host needs the finite 16 GiB native profile; aggregate
    # physical memory/swap/pids remain independently enforced by the cgroup.
    memory_bytes: int = ROOT_ADDRESS_SPACE_BYTES
    aggregate_memory_bytes: int = 4 * 1024 * 1024 * 1024
    aggregate_processes: int = 256
    ssh_profile: SshProfile | None = None

    def resource_metadata(self, observed: dict) -> dict:
        """Separate configured ceilings from the actual inspected cgroup limits."""
        fields = ("memory_max_bytes", "swap_max_bytes", "pids_max")
        if (not isinstance(observed, dict) or observed.get("kind") != "CGROUP_V2"
                or any(type(observed.get(key)) is not int or observed[key] < 0 for key in fields)):
            raise CloudBlocked("CGROUP_RESOURCE_LIMIT_UNAVAILABLE", "Observed resource metadata is outside the fixed cgroup profile")
        return {"address_space_rlimit_bytes": self.memory_bytes,
                "aggregate_memory_ceiling_bytes": self.aggregate_memory_bytes,
                "aggregate_processes_ceiling": self.aggregate_processes,
                "observed_cgroup": {"kind": "CGROUP_V2", **{key: observed[key] for key in fields}}}

    def validate(self, manifest: dict) -> None:
        configuration = manifest.get("configuration", {})
        environment = configuration.get("environment", manifest.get("environment", {}))
        require_cloud_environment_route(environment)
        inputs = manifest["inputs"]
        authorization = inputs["authorization"]
        if not {"git:read", "framework:execute"} <= set(authorization["permitted_actions"]):
            raise CloudBlocked("ACTION_AUTHORIZATION_REQUIRED", "Workspace execution requires explicit Git read and framework execution authorization")
        if authorization.get("network_targets") and self.ssh_profile is None:
            raise CloudBlocked("REMOTE_NETWORK_UNSUPPORTED", "This runtime supports workspace-local fixtures; remote SUT/CI/SSH is unavailable")
        allowed = {"git:read", "framework:execute"}
        if self.ssh_profile is not None:
            allowed.add("environment:read")
        unsupported = set(authorization["permitted_actions"]) - allowed
        if unsupported:
            raise CloudBlocked("ACTION_CAPABILITY_UNSUPPORTED", "Requested remote/write action is not enforced by this runtime")
        if self.ssh_profile is not None:
            if (validate_profile(environment) != self.ssh_profile
                    or "environment:read" not in authorization["permitted_actions"]
                    or authorization.get("network_targets") != [self.ssh_profile.target]
                    or self.ssh_profile.target not in authorization.get("targets", [])):
                raise CloudBlocked("SSH_AUTHORIZATION_MISMATCH", "Fixed SSH diagnostics require the exact frozen environment target and read authorization")
        elif environment.get("connection", "NONE") != "NONE":
            raise CloudBlocked("ENVIRONMENT_CAPABILITY_UNSUPPORTED", "Remote environment access needs an independently enforced adapter")
        if environment.get("require_matching_deployment"):
            raise CloudBlocked("DEPLOYMENT_UNOBSERVED", "Workspace-local runtime cannot attest remote deployment identity")
        if not 1 <= self.timeout_seconds <= inputs["budgets"]["total_seconds"]:
            raise CloudBlocked("RUNTIME_BUDGET_INVALID", "Runtime deadline exceeds its frozen task budget")
        if not 1 <= self.max_model_requests <= 10000 or not 1 <= self.max_tokens <= 49152:
            raise CloudBlocked("MODEL_LIMITS_INVALID", "Model request/token limits are outside the supported profile")


def capability_report(*, ssh_admitted: bool = False) -> dict:
    return {"isolation": "linux-bubblewrap-namespaces", "general_network": False,
            "remote_sut": False, "ssh": ssh_admitted, "ssh_fixed_diagnostics": ssh_admitted,
            "ssh_profile": "SSH_FIXED_DIAGNOSTICS_V1" if ssh_admitted else None,
            "ci": False, "git_write": False,
            "external_cli_delegation": False, "workspace_local_framework": True,
            "model_only_broker": True, "native_addon_temp_exec_required": True,
            "aggregate_resource_envelope": "FINITE_CGROUP_V2_REQUIRED"}


def require_readonly_shell() -> None:
    """The SDK must not fall back to passwd/userInfo in the empty namespace."""
    shell = Path("/bin/sh")
    try:
        resolved = shell.resolve(strict=True)
        info = resolved.stat()
        if (not any(resolved.is_relative_to(root) for root in (Path("/usr"), Path("/bin")))
                or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o6022
                or not os.access(shell, os.X_OK)):
            raise ValueError()
    except (OSError, ValueError):
        raise CloudBlocked("SHELL_UNAVAILABLE", "The readonly runtime tools must provide an executable /bin/sh") from None


class BubblewrapSandbox:
    def __init__(self, *, workspace: Path, dsh_home: Path, broker_socket: Path,
                 policy: SandboxPolicy, delegate_payload: Path | None = None,
                 delegate_sockets: dict[str, Path] | None = None,
                 ssh_socket: Path | None = None):
        self.workspace, self.dsh_home = workspace.absolute(), dsh_home.absolute()
        self.broker_socket, self.policy = broker_socket.absolute(), policy
        self.delegate_payload = delegate_payload.absolute() if delegate_payload is not None else None
        self.delegate_sockets = dict(delegate_sockets or {})
        self.ssh_socket = ssh_socket.absolute() if ssh_socket is not None else None
        self.process = None
        self.stop_observation = None

    def ssh_mounts(self) -> list[str]:
        if self.ssh_socket is None:
            if self.policy.ssh_profile is not None:
                raise CloudBlocked("SSH_SOCKET_UNAVAILABLE", "An admitted SSH profile needs its host Unix broker")
            return []
        try:
            if (self.policy.ssh_profile is None
                    or self.ssh_socket.resolve(strict=True) != self.ssh_socket
                    or not stat.S_ISSOCK(self.ssh_socket.lstat().st_mode)):
                raise ValueError
            return ["--ro-bind", str(self.ssh_socket), SSH_SOCKET]
        except (OSError, ValueError):
            raise CloudBlocked("SSH_SOCKET_UNAVAILABLE", "SSH diagnostics require a canonical Unix broker socket") from None

    def delegate_mounts(self) -> list[str]:
        """Only the host broker may supply a separately verified frozen payload.

        Distribution hashes/closure and model budgets are checked by the
        delegation adapter. This boundary rechecks path shape and socket types,
        then exposes readonly mounts without credentials or a download path.
        """
        if set(self.delegate_sockets) - {"codex", "claude-code"} or (self.delegate_sockets and self.delegate_payload is None):
            raise CloudBlocked("DELEGATE_MOUNT_INVALID", "Delegation mounts require a verified payload and allowed broker names")
        if self.delegate_payload is None:
            return []
        try:
            payload = self.delegate_payload
            if payload.resolve(strict=True) != payload or not stat.S_ISDIR(payload.lstat().st_mode):
                raise ValueError
            mounts = ["--dir", "/opt", "--ro-bind", str(payload), "/opt/hypertest-delegates"]
            for name, socket_path in sorted(self.delegate_sockets.items()):
                socket_path = socket_path.absolute()
                if socket_path.resolve(strict=True) != socket_path or not stat.S_ISSOCK(socket_path.lstat().st_mode):
                    raise ValueError
                mounts.extend(["--ro-bind", str(socket_path), f"/run/{name}.sock"])
            return mounts
        except (OSError, ValueError):
            raise CloudBlocked("DELEGATE_MOUNT_INVALID", "Delegation requires canonical readonly payload and Unix broker socket paths") from None

    def command(self) -> list[str]:
        if platform.system() != "Linux":
            raise CloudBlocked("OS_SANDBOX_UNAVAILABLE", "Cloud execution requires Linux namespaces and bubblewrap")
        binary = shutil.which("bwrap")
        if binary is None:
            raise CloudBlocked("OS_SANDBOX_UNAVAILABLE", "Install bubblewrap on a dedicated Linux Cloud worker")
        require_readonly_shell()
        inspect_resource_envelope(max_memory_bytes=self.policy.aggregate_memory_bytes,
                                  max_processes=self.policy.aggregate_processes)
        source_package = Path(__file__).resolve().parents[1]
        command = [binary, "--die-with-parent", "--new-session", "--unshare-all",
                   "--clearenv", "--ro-bind", "/usr", "/usr", "--proc", "/proc",
                   "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
                   "--dir", "/app", "--ro-bind", str(source_package), "/app/hypertest",
                   "--bind", str(self.workspace), "/workspace",
                   "--ro-bind", str(self.workspace / "sut"), "/workspace/sut",
                   "--bind", str(self.dsh_home), "/home/agent",
                   "--ro-bind", str(self.broker_socket), "/run/model.sock"]
        command.extend(self.delegate_mounts())
        command.extend(self.ssh_mounts())
        # Preserve standard absolute interpreter paths and shebangs in the empty
        # root. On merged-/usr hosts these are aliases of the same readonly tools.
        for path in ("/bin", "/sbin", "/lib", "/lib64"):
            if Path(path).exists():
                command.extend(["--ro-bind", path, path])
        prefix = Path(sys.prefix).absolute()
        if not prefix.is_relative_to("/usr"):
            # A dedicated immutable virtualenv is the only additional runtime mount.
            if prefix == Path("/") or prefix.is_relative_to(Path.home()):
                raise CloudBlocked("RUNTIME_PREFIX_UNSAFE", "Use a dedicated non-home Cloud Python environment")
            command.extend(["--ro-bind", str(prefix), str(prefix)])
        executable_path = f"{sys.prefix}/bin:/usr/local/bin:/usr/bin:/bin"
        if self.delegate_payload is not None:
            executable_path = "/opt/hypertest-delegates/bin:" + executable_path
        for key, value in {"HOME": "/home/agent", "DSH_HOME": "/home/agent/dsh", "SHELL": "/bin/sh",
                           "PATH": executable_path,
                           "LANG": "C.UTF-8", "PYTHONPATH": "/app",
                           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}.items():
            command.extend(["--setenv", key, value])
        command.extend(["--chdir", "/workspace", sys.executable, "-m", "hypertest.cloud.sdk_driver"])
        return command

    async def start(self, config: dict):
        command = self.command()
        self.process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": os.defpath}, start_new_session=True,
            preexec_fn=lambda: apply_resource_limits(self.policy))
        try:
            encoded = json.dumps(config, ensure_ascii=False).encode()
            if len(encoded) > 1024 * 1024:
                raise CloudBlocked("RUNTIME_INPUT_LIMIT", "Runtime inputs exceed the bounded process-control frame")
            self.process.stdin.write(encoded)
            await asyncio.wait_for(self.process.stdin.drain(), 5)
            self.process.stdin.close()
        except BaseException:
            await self.stop()
            raise
        return self.process

    async def stop(self):
        """Caller MUST fence writes before calling; PID namespace kills all descendants."""
        process = self.process
        if self.stop_observation is not None:
            return self.stop_observation
        if process is None:
            self.stop_observation = {"local_processes_stopped": True, "runtime_started": False}
            return self.stop_observation
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                self.stop_observation = {"local_processes_stopped": False, "runtime_started": True}
                raise CloudBlocked("RUNTIME_STOP_UNCONFIRMED", "The namespace supervisor did not terminate within its bound") from None
        self.stop_observation = {"local_processes_stopped": process.returncode is not None,
                                 "runtime_started": True, "isolation": "linux-pid-namespace"}
        return self.stop_observation


def apply_resource_limits(policy: SandboxPolicy) -> None:
    """The same limits are used by production and independent no-model diagnosis.

    RLIMIT_AS constrains virtual address space, not physical RSS. Deployment must
    also supply a finite aggregate memory/pid cgroup for the dedicated worker.
    """
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_AS, (policy.memory_bytes,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (policy.timeout_seconds + 10,) * 2)
