"""Explicit, no-prompt probe of the exact official SDK/runtime pair."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from .compatibility import inspect_compatibility
from .errors import AdapterError, CapabilityError, DependencyError
from .models import SERVER_NAME, SERVER_VERSION, ProtocolProbeReport
from .supervisor import ProcessSupervisor


def probe_protocol(*, timeout_seconds: float = 20.0) -> ProtocolProbeReport:
    """Launch an isolated runtime only when explicitly called by an operator.

    This performs initialize + working-directory/get + shutdown. It has no
    prompt, resume, custom executable, profile patch or credential input.
    Metadata inspection, ordinary imports and Local sync never call it.
    """
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 600
    ):
        raise AdapterError("INVALID_RUNTIME_TIMEOUT")
    if os.name != "posix":
        raise CapabilityError("PROCESS_SUPERVISION_UNSUPPORTED")
    compatibility = inspect_compatibility()
    if not compatibility.compatible:
        raise DependencyError("SDK_DEPENDENCY_UNAVAILABLE")
    with tempfile.TemporaryDirectory(prefix="hypertest-deepseek-probe-") as directory:
        root = Path(directory)
        for name in ("workspace", "dsh-home", "private-home", "tmp"):
            (root / name).mkdir(mode=0o700)
        supervisor = ProcessSupervisor(root)
        failure: AdapterError | None = None
        try:
            supervisor.start()
            result = supervisor.request("start", {
                "workspace": str(root / "workspace"),
                "dsh_home": str(root / "dsh-home"),
                "session_id": f"hypertest-probe-{uuid4().hex}",
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "timeout_seconds": timeout_seconds,
            }, timeout_seconds)
            if (
                result.get("server_name") != SERVER_NAME
                or result.get("server_version") != SERVER_VERSION
                or result.get("session_created") is not True
            ):
                raise AdapterError("SDK_PROTOCOL_UNSUPPORTED")
            supervisor.request("close", {}, min(timeout_seconds, 2.0))
        except AdapterError as error:
            failure = error
        finally:
            stopped = supervisor.stop()
        if not stopped.root_reaped or not stopped.process_group_absent:
            raise AdapterError("RUNTIME_STOP_UNCONFIRMED")
        if failure is not None:
            raise failure from None
        return ProtocolProbeReport(True, True, True, True, SERVER_NAME, SERVER_VERSION)
