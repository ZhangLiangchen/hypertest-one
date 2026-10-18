from __future__ import annotations

import asyncio
import io
import json
import os
import re
import signal
import sys
import tarfile
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from hypertest.config import get_settings

# Operational ownership only, never a canonical testing fact.
runner_job_id: ContextVar[str | None] = ContextVar("hypertest_runner_job_id", default=None)
JOB_LABEL = "org.hypertest.job_id"


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    timed_out: bool = False
    service_metadata: dict | None = None
    service_log: bytes | None = None
    error_code: str | None = None


async def run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
    output_limit: int = 8 * 1024 * 1024,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    async def collect(stream) -> bytes:
        limit, content, truncated = output_limit, bytearray(), False
        while chunk := await stream.read(65536):
            remaining = max(0, limit - len(content))
            content.extend(chunk[:remaining])
            truncated = truncated or len(chunk) > remaining
        if truncated:
            content.extend(b"\n[HyperTest collector truncated oversized output]\n")
        return bytes(content)

    stdout_task = asyncio.create_task(collect(process.stdout))
    stderr_task = asyncio.create_task(collect(process.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=timeout)
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task)
        raise
    except TimeoutError:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
    # Kill a surviving child that still holds a pipe after its parent exited.
    try:
        stdout, stderr = await asyncio.wait_for(
            asyncio.gather(asyncio.shield(stdout_task), asyncio.shield(stderr_task)),
            timeout=5,
        )
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    return ProcessResult(stdout, stderr, process.returncode, timed_out)


def pytest_arguments(nodeids: list[str], junit_path: str) -> list[str]:
    # These arguments are platform-owned; clients cannot inject flags or shell text.
    return [
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        "-o",
        "junit_family=xunit2",
        f"--junitxml={junit_path}",
        *nodeids,
    ]


class LocalRunner:
    """Explicitly enabled development adapter. This adapter is not a sandbox."""

    name = "local"

    async def fingerprint(self) -> dict:
        if not get_settings().runner_allow_local:
            raise RuntimeError("local runner requires HYPERTEST_RUNNER_ALLOW_LOCAL=true")
        return {
            "backend": self.name,
            "python": sys.version,
            "executable": sys.executable,
            "isolation": "development-process-only",
        }

    async def execute(
        self, source: Path, output: Path, nodeids: list[str], timeout: int, identity: dict
    ) -> ProcessResult:
        await self.fingerprint()
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(output),
            "TMPDIR": str(output),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": os.pathsep.join([str(source), str(source / "src")]),
        }
        return await run_process(
            [sys.executable, *pytest_arguments(nodeids, str(output / "junit.xml"))],
            cwd=source,
            timeout=timeout,
            env=env,
        )


class DockerRunner:
    name = "docker"

    def __init__(self, environment: dict | None = None):
        self.environment = deepcopy(environment)

    async def fingerprint(self) -> dict:
        if self.environment is not None:
            from hypertest.runner.environments import LABEL_PREFIX, validate_environment_binding

            details = await validate_environment_binding(self.environment)
            return {
                "backend": self.name, "image_id": details["Id"],
                "os": details["Os"], "architecture": details["Architecture"],
                "environment_definition": deepcopy(self.environment),
                "base_image_digest": details["Config"]["Labels"][LABEL_PREFIX + "base_image_digest"],
                "network": "none", "read_only": True,
            }
        image = get_settings().runner_image
        result = await run_process(
            ["docker", "image", "inspect", image, "--format", "{{json .}}"],
            cwd=Path("/tmp"),
            timeout=30,
        )
        if result.exit_code != 0:
            raise RuntimeError("trusted runner image is unavailable; build the runner Dockerfile")
        details = json.loads(result.stdout)
        return {
            "backend": self.name,
            "image_id": details["Id"],
            "image": image,
            "os": details["Os"],
            "architecture": details["Architecture"],
            "network": "none",
            "read_only": True,
        }

    async def execute(
        self, source: Path, output: Path, nodeids: list[str], timeout: int, identity: dict
    ) -> ProcessResult:
        service = None
        if self.environment is not None:
            observed = await self.fingerprint()
            if identity != observed:
                raise ValueError("controlled runner identity changed before execution")
            service = self.environment["request"].get("service")
            if service is not None:
                from hypertest.runner.service_launcher import validate_app

                try:
                    validate_app(source, service["app"])
                except ValueError:
                    return ProcessResult(b"", b"", None, error_code="SERVICE_SOURCE_INVALID")
        token = uuid4().hex
        name, staging = f"hypertest-runner-{token}", f"hypertest-stage-{token}"
        source_volume, output_volume = f"hypertest-source-{token}", f"hypertest-results-{token}"

        async def docker(*args: str, required: bool = True) -> ProcessResult:
            result = await run_process(["docker", *args], cwd=source, timeout=30)
            if required and result.exit_code != 0:
                raise RuntimeError(f"runner container operation failed ({args[0]})")
            return result

        async def collect_file(filename: str, limit: int) -> bytes | None:
            archive = await run_process(
                ["docker", "cp", name + ":/results/" + filename, "-"],
                cwd=source, timeout=30, output_limit=limit + 65536,
            )
            if archive.exit_code != 0 or archive.timed_out:
                return None
            if len(archive.stdout) > limit + 65536:
                raise ValueError("Runner artifact transport exceeds collection limit")
            with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
                members = bundle.getmembers()
                if (len(members) != 1 or not members[0].isfile()
                    or members[0].name != filename or members[0].size > limit):
                    raise ValueError("Runner artifact transport contains an unsafe report")
                content = bundle.extractfile(members[0])
                assert content is not None
                return content.read()

        label_args = ["--label", "org.hypertest.managed=true"]
        job_id = runner_job_id.get()
        if job_id is not None:
            # UUID parsing ensures filters and labels are platform-owned values.
            label_args += ["--label", f"{JOB_LABEL}={UUID(job_id)}"]
        try:
            # Precreate labelled volumes; implicitly created Docker volumes lose
            # ownership metadata and cannot safely be recovered after a crash.
            await docker("volume", "create", *label_args, source_volume)
            await docker("volume", "create", *label_args, output_volume)
            # A restrictive host umask must not make copied source unreadable to UID 65534.
            source.chmod(0o755)
            for path in source.rglob("*"):
                executable = bool(path.stat().st_mode & 0o111)
                path.chmod(0o755 if path.is_dir() or executable else 0o644)
            # docker cp transports content through the API and works with a remote daemon.
            # Populate a dedicated source volume before mounting it read-only for execution.
            await docker(
                "create",
                "--pull=never",
                *label_args,
                "--name",
                staging,
                "--network",
                "none",
                "--volume",
                f"{source_volume}:/repo",
                identity["image_id"],
                "true",
            )
            await docker("cp", str(source) + "/.", staging + ":/repo")
            await docker("rm", "-f", staging)
            command = [
                "create",
                "--pull=never",
                *label_args,
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "128",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--log-driver",
                "local",
                "--log-opt",
                "max-size=1m",
                "--log-opt",
                "max-file=2",
                "--user",
                "65534:65534",
                "--mount",
                f"type=volume,source={source_volume},target=/repo,readonly",
                "--mount",
                f"type=volume,source={output_volume},target=/results",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=128m",
                "--workdir",
                "/repo",
                "--env",
                "HOME=/tmp",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--env",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "--env",
                "PYTHONPATH=/repo:/repo/src",
                identity["image_id"], "python",
            ]
            if self.environment is not None:
                # The Docker client can inject configured proxies. Approved
                # workloads inherit neither those credentials nor host routing.
                command += ["-I", "/opt/hypertest/service_launcher.py"]
                image_index = command.index(identity["image_id"])
                command[image_index:image_index] = [item for name in (
                    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                ) for item in ("--env", name + "=")] + ["--env", "NO_PROXY=127.0.0.1,localhost"]
            if service is None and self.environment is None:
                command += pytest_arguments(nodeids, "/results/junit.xml")
            elif service is None:
                command += ["--pytest", *pytest_arguments(nodeids, "/results/junit.xml")[2:]]
            else:
                command += [json.dumps({
                    "service": service, "nodeids": nodeids,
                }, sort_keys=True)]
            await docker(*command)
            process = await run_process(
                ["docker", "start", "--attach", name], cwd=source, timeout=timeout
            )
            if process.timed_out:
                await docker("kill", name, required=False)
            state = await docker("inspect", "--format", "{{json .State}}", name)
            details = json.loads(state.stdout)
            # Only fixed, bounded reports cross the daemon API, never a result directory.
            junit = await collect_file("junit.xml", 16 * 1024 * 1024)
            if junit is not None:
                (output / "junit.xml").write_bytes(junit)
            metadata = service_log = error_code = None
            if service is not None:
                try:
                    from hypertest.runner.service_launcher import validate_metadata

                    raw = await collect_file("service-metadata.json", 65536)
                    service_log = await collect_file("service.log", 256 * 1024)
                    if raw is None or service_log is None:
                        error_code = "SERVICE_EVIDENCE_MISSING"
                    else:
                        metadata = json.loads(raw)
                        validate_metadata(metadata, service, details["ExitCode"])
                        error_code = metadata["error_code"]
                except (ValueError, TypeError, KeyError):
                    metadata = service_log = None
                    error_code = "SERVICE_EVIDENCE_INVALID"
                if details.get("OOMKilled"):
                    error_code = "SERVICE_RESOURCE_LIMIT"
            return ProcessResult(
                process.stdout, process.stderr, details["ExitCode"], process.timed_out,
                metadata, service_log, error_code,
            )
        finally:
            await docker("rm", "-f", "-v", name, staging, required=False)
            await docker("volume", "rm", source_volume, output_volume, required=False)


async def cleanup_docker_job_resources(job_id: UUID) -> dict:
    """Remove only resources explicitly labelled with this immutable job UUID.

    Run outside database transactions/row locks. This is best-effort resource
    cleanup, not execution evidence or a promise of exactly-once external work.
    """
    label = f"label={JOB_LABEL}={UUID(str(job_id))}"
    result = {"backend": "docker", "available": True, "complete": False,
              "containers_removed": 0, "volumes_removed": 0}
    try:
        containers = await run_process(["docker", "ps", "-aq", "--filter", label],
                                       cwd=Path("/tmp"), timeout=15, output_limit=65536)
        volumes = await run_process(["docker", "volume", "ls", "-q", "--filter", label],
                                    cwd=Path("/tmp"), timeout=15, output_limit=65536)
        if containers.exit_code != 0 or volumes.exit_code != 0 or containers.timed_out or volumes.timed_out:
            return {**result, "available": False}
        container_ids = containers.stdout.decode("ascii").split()
        volume_names = volumes.stdout.decode("ascii").split()
        if (any(not re.fullmatch(r"[a-f0-9]{12,64}", value) for value in container_ids)
            or any(not re.fullmatch(r"hypertest-(?:source|results)-[a-f0-9]{32}", value) for value in volume_names)):
            return result
        if container_ids:
            removed = await run_process(["docker", "rm", "-f", "-v", *container_ids],
                                        cwd=Path("/tmp"), timeout=30)
            if removed.exit_code != 0 or removed.timed_out:
                return result
            result["containers_removed"] = len(container_ids)
        if volume_names:
            removed = await run_process(["docker", "volume", "rm", *volume_names],
                                        cwd=Path("/tmp"), timeout=30)
            if removed.exit_code != 0 or removed.timed_out:
                return result
            result["volumes_removed"] = len(volume_names)
        result["complete"] = True
        return result
    except (OSError, UnicodeError):
        return {**result, "available": False}
