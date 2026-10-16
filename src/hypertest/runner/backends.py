from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from hypertest.config import get_settings


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes
    exit_code: int | None
    timed_out: bool = False


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

    async def fingerprint(self) -> dict:
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
        token = uuid4().hex
        name, staging = f"hypertest-runner-{token}", f"hypertest-stage-{token}"
        source_volume, output_volume = f"hypertest-source-{token}", f"hypertest-results-{token}"

        async def docker(*args: str, required: bool = True) -> ProcessResult:
            result = await run_process(["docker", *args], cwd=source, timeout=30)
            if required and result.exit_code != 0:
                raise RuntimeError(f"runner container operation failed ({args[0]})")
            return result

        try:
            # A restrictive host umask must not make copied source unreadable to UID 65534.
            source.chmod(0o755)
            for path in source.rglob("*"):
                executable = bool(path.stat().st_mode & 0o111)
                path.chmod(0o755 if path.is_dir() or executable else 0o644)
            # docker cp transports content through the API and works with a remote daemon.
            # Populate a dedicated source volume before mounting it read-only for execution.
            await docker(
                "create",
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
                identity["image_id"],
                "python",
                *pytest_arguments(nodeids, "/results/junit.xml"),
            ]
            await docker(*command)
            process = await run_process(
                ["docker", "start", "--attach", name], cwd=source, timeout=timeout
            )
            if process.timed_out:
                await docker("kill", name, required=False)
            state = await docker("inspect", "--format", "{{json .State}}", name)
            details = json.loads(state.stdout)
            # Copy one bounded report through the API, never arbitrary result-directory files.
            archive = await run_process(
                ["docker", "cp", name + ":/results/junit.xml", "-"],
                cwd=source,
                timeout=30,
                output_limit=17 * 1024 * 1024,
            )
            if archive.exit_code == 0:
                if len(archive.stdout) > 17 * 1024 * 1024:
                    raise ValueError("JUnit transport exceeds collection limit")
                with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
                    members = bundle.getmembers()
                    if (
                        len(members) != 1
                        or not members[0].isfile()
                        or members[0].size > 16 * 1024 * 1024
                    ):
                        raise ValueError("JUnit transport contains an unsafe report")
                    content = bundle.extractfile(members[0])
                    assert content is not None
                    (output / "junit.xml").write_bytes(content.read())
            return ProcessResult(
                process.stdout, process.stderr, details["ExitCode"], process.timed_out
            )
        finally:
            await docker("rm", "-f", "-v", name, staging, required=False)
            await docker("volume", "rm", source_volume, output_volume, required=False)
