"""Trusted v2 API entry point: one ASGI service and self-contained pytest targets.

This file deliberately uses only the standard library and never installs code.
The host pins its digest in the image and collects only the two named outputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765"
LOG_LIMIT = 256 * 1024
SCHEMA = "hypertest.service-execution/v1"
PYTEST_BOOTSTRAP = "import sys,pytest;sys.path[:0]=['/repo','/repo/src'];raise SystemExit(pytest.main(sys.argv[1:]))"
UVICORN_BOOTSTRAP = "import sys,uvicorn;sys.path[:0]=['/repo','/repo/src'];uvicorn.main()"
ERROR_CODES = {"SERVICE_START_FAILED", "SERVICE_NOT_READY", "SERVICE_EXITED",
               "SERVICE_CLEANUP_FAILED", "SERVICE_LAUNCHER_ERROR"}


def validate_metadata(metadata: dict, service: dict, exit_code: int) -> None:
    """Strictly validate the fixed collection channel; never accept arbitrary JSON."""
    keys = {"schema_version", "app", "base_url", "startup_timeout_seconds", "health",
            "service_started_at", "ready_at", "finished_at", "service_early_exit",
            "service_exit_code", "pytest_exit_code", "cleanup_complete", "log_truncated", "error_code"}
    if (not isinstance(metadata, dict) or set(metadata) != keys
        or metadata["schema_version"] != SCHEMA or metadata["app"] != service["app"]
        or metadata["base_url"] != BASE_URL
        or metadata["startup_timeout_seconds"] != service["startup_timeout_seconds"]):
        raise ValueError("service proof identity mismatch")
    for key in ("service_early_exit", "cleanup_complete", "log_truncated"):
        if type(metadata[key]) is not bool:
            raise ValueError("invalid service proof flag")
    for key in ("service_exit_code", "pytest_exit_code"):
        if metadata[key] is not None and (type(metadata[key]) is not int or not -255 <= metadata[key] <= 255):
            raise ValueError("invalid service proof exit code")
    times = {}
    for key in ("service_started_at", "ready_at", "finished_at"):
        value = metadata[key]
        if value is None and key == "ready_at":
            continue
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError("invalid service proof time")
        times[key] = datetime.fromisoformat(value)
        if times[key].tzinfo is None:
            raise ValueError("service proof time must have a timezone")
    if times["service_started_at"] > times["finished_at"]:
        raise ValueError("invalid service proof time order")
    health = metadata["health"]
    if health is not None:
        if (not isinstance(health, dict) or set(health) != {"method", "path", "status", "body_sha256"}
            or health["method"] != "GET" or health["path"] != service["health_path"]
            or type(health["status"]) is not int or health["status"] != 200
            or not isinstance(health["body_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", health["body_sha256"])):
            raise ValueError("invalid service readiness fact")
    error_code = metadata["error_code"]
    if error_code is not None and (not isinstance(error_code, str) or error_code not in ERROR_CODES):
        raise ValueError("invalid service error code")
    if error_code is None:
        if (health is None or metadata["ready_at"] is None or metadata["service_early_exit"]
            or not metadata["cleanup_complete"] or metadata["service_exit_code"] is None
            or metadata["pytest_exit_code"] != exit_code):
            raise ValueError("incomplete service execution proof")
        if not times["service_started_at"] <= times["ready_at"] <= times["finished_at"]:
            raise ValueError("invalid readiness time order")


def now() -> str:
    return datetime.now(UTC).isoformat()


def validate_app(source: Path, app: str) -> Path:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*", app):
        raise ValueError("invalid ASGI app")
    module = app.split(":")[0].split(".")
    if module[0] == "tests":
        raise ValueError("the ASGI app must come from tracked application source")
    source = source.resolve()
    # Both conventional repository-root and src layouts are supported.
    for base in (source, source / "src"):
        for path in (base.joinpath(*module).with_suffix(".py"), base.joinpath(*module, "__init__.py")):
            if (path.is_file() and path.resolve().is_relative_to(source)
                and not any(source.joinpath(*path.relative_to(source).parts[:count]).is_symlink()
                            for count in range(1, len(path.relative_to(source).parts) + 1))):
                return path
    raise ValueError("ASGI app does not identify safe tracked Python source")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(path: str, timeout: float) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(BASE_URL + path, timeout=timeout) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                return None
            return {"method": "GET", "path": path, "status": 200,
                    "body_sha256": hashlib.sha256(body).hexdigest()}
    except (OSError, urllib.error.URLError):
        return None


async def stop(process: asyncio.subprocess.Process | None) -> bool:
    if process is None:
        return True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 2)
    except TimeoutError:
        pass
    # A parent may exit while descendants keep running or hold a log pipe.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), 2)
        return True
    except TimeoutError:
        return False


async def execute(payload: dict, source: Path = Path("/repo"), output: Path = Path("/results")) -> int:
    service = payload["service"]
    validate_app(source, service["app"])
    path = service["health_path"]
    if (not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_./~-]*", path)
        or ".." in path or "//" in path or len(path) > 256):
        raise ValueError("invalid health path")
    startup = service["startup_timeout_seconds"]
    if type(startup) is not int or not 1 <= startup <= 120:
        raise ValueError("invalid startup timeout")
    nodeids = payload["nodeids"]
    if (not isinstance(nodeids, list) or not nodeids or any(
        not isinstance(node, str) or not re.fullmatch(
            r"tests/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.py::(?:[A-Za-z_]\w*::)*test_\w+", node
        ) or ".." in node.split("::")[0].split("/") for node in nodeids
    )):
        raise ValueError("invalid canonical pytest targets")
    metadata = {
        "schema_version": SCHEMA, "app": service["app"], "base_url": BASE_URL,
        "startup_timeout_seconds": startup, "health": None,
        "service_started_at": now(), "ready_at": None, "finished_at": None,
        "service_early_exit": False, "service_exit_code": None,
        "pytest_exit_code": None, "cleanup_complete": False,
        "log_truncated": False, "error_code": None,
    }
    process = test = None
    readers: list[asyncio.Task] = []
    logs = bytearray()

    async def collect(stream) -> None:
        while chunk := await stream.read(65536):
            remaining = max(0, LOG_LIMIT - len(logs))
            logs.extend(chunk[:remaining])
            metadata["log_truncated"] |= len(chunk) > remaining

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", UVICORN_BOOTSTRAP, service["app"], "--host", "127.0.0.1",
            "--port", "8765", "--workers", "1", "--no-access-log",
            cwd=source, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        readers = [asyncio.create_task(collect(process.stdout)), asyncio.create_task(collect(process.stderr))]
        deadline = time.monotonic() + startup
        while time.monotonic() < deadline:
            if process.returncode is not None:
                metadata["service_early_exit"] = True
                metadata["error_code"] = "SERVICE_START_FAILED"
                break
            fact = await asyncio.to_thread(probe, path, min(0.5, max(0.01, deadline - time.monotonic())))
            if fact is not None:
                metadata["health"], metadata["ready_at"] = fact, now()
                break
            await asyncio.sleep(min(0.1, max(0, deadline - time.monotonic())))
        if metadata["health"] is None and metadata["error_code"] is None:
            metadata["error_code"] = "SERVICE_NOT_READY"
        if metadata["error_code"] is None:
            environment = dict(os.environ, HYPERTEST_BASE_URL=BASE_URL)
            test = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-c", PYTEST_BOOTSTRAP, "-q", "-p", "no:cacheprovider",
                "-c", "/dev/null", "--noconftest", "--rootdir=/repo",
                "-o", "addopts=", "-o", "junit_family=xunit2",
                f"--junitxml={output / 'junit.xml'}", *nodeids,
                cwd=source, env=environment, start_new_session=True,
            )
            test_wait, service_wait = asyncio.create_task(test.wait()), asyncio.create_task(process.wait())
            await asyncio.wait([test_wait, service_wait], return_when=asyncio.FIRST_COMPLETED)
            if process.returncode is not None:
                metadata["service_early_exit"], metadata["error_code"] = True, "SERVICE_EXITED"
                await stop(test)
            metadata["pytest_exit_code"] = await test_wait
            service_wait.cancel()
            await asyncio.gather(service_wait, return_exceptions=True)
    except (OSError, ValueError):
        metadata["error_code"] = "SERVICE_LAUNCHER_ERROR"
    finally:
        test_clean = await stop(test)
        service_clean = await stop(process)
        metadata["cleanup_complete"] = test_clean and service_clean
        if not metadata["cleanup_complete"]:
            metadata["error_code"] = "SERVICE_CLEANUP_FAILED"
        metadata["service_exit_code"] = process.returncode if process is not None else None
        metadata["finished_at"] = now()
        if readers:
            await asyncio.wait_for(asyncio.gather(*readers), 3)
        # Only these platform-owned, bounded outputs are collected by the host.
        (output / "service.log").write_bytes(bytes(logs))
        (output / "service-metadata.json").write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
    return 3 if metadata["error_code"] else (metadata["pytest_exit_code"] or 0)


if __name__ == "__main__":
    try:
        if sys.argv[1] == "--pytest":
            # Import the image's pytest before allowing application import roots.
            # The host owns the arguments; a repository pytest.py cannot replace it.
            import pytest

            sys.path[:0] = ["/repo", "/repo/src"]
            raise SystemExit(pytest.main(sys.argv[2:]))
        raise SystemExit(asyncio.run(execute(json.loads(sys.argv[1]))))
    except (ValueError, KeyError, TypeError, IndexError):
        # No raw application diagnostics are promoted into the control channel.
        raise SystemExit(3) from None
