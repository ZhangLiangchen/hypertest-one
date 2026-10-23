"""Operator-only diagnostics for the optional official DeepSeek Harness SDK.

The default doctor reads package metadata. Only the explicitly enabled protocol
probe starts a runtime; neither command accepts or submits a model prompt.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Sequence
from typing import Any

from hypertest.deepseek_harness import SDK_VERSION, inspect_compatibility, probe_protocol
from hypertest.deepseek_harness.models import SERVER_NAME, SERVER_VERSION

PROFILE = "cloud-harness-task/v1alpha1"
NOT_PROVEN = (
    "model_execution",
    "codex_delegation",
    "claude_code_delegation",
    "project_test_execution",
    "cloud_task_lifecycle",
    "attempt_cancellation",
    "session_recovery",
    "runtime_supply_chain_origin",
)
_PUBLIC_ERROR_CODES = frozenset(
    {
        "SDK_NOT_INSTALLED",
        "RUNTIME_NOT_INSTALLED",
        "SDK_VERSION_MISMATCH",
        "RUNTIME_VERSION_MISMATCH",
        "VERSION_MISMATCH",
        "SDK_IMPORT_FAILED",
        "RUNTIME_NOT_FOUND",
        "RUNTIME_NOT_EXECUTABLE",
        "RUNTIME_UNTRUSTED",
        "RUNTIME_START_FAILED",
        "RUNTIME_EXITED",
        "PROBE_TIMEOUT",
        "PROTOCOL_TIMEOUT",
        "PROTOCOL_INITIALIZATION_FAILED",
        "PROTOCOL_VERSION_MISMATCH",
        "SESSION_CREATION_FAILED",
        "RUNTIME_CLOSE_FAILED",
        "CLEANUP_UNCONFIRMED",
        "PROCESS_SUPERVISION_UNSUPPORTED",
        "SDK_DEPENDENCY_UNAVAILABLE",
        "SUPERVISOR_START_FAILED",
        "RUNTIME_PROCESS_EXITED",
        "INVALID_CONTROL_FRAME",
        "CONTROL_FRAME_TOO_LARGE",
        "SDK_TIMEOUT",
        "SDK_TRANSPORT_FAILED",
        "SDK_OPERATION_FAILED",
        "SDK_PROTOCOL_UNSUPPORTED",
        "RUNTIME_STOP_UNCONFIRMED",
    }
)


class _UsageError(Exception):
    """Do not echo an invalid argument that may contain a private value."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError


def _version(value: str | None) -> str | None:
    """Installed distribution metadata is untrusted display data."""
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)+(?:[a-z]+\d*)?", value):
        return "UNRECOGNIZED"
    return value if len(value) <= 40 else "UNRECOGNIZED"


def _base_report(operation: str) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "operation": operation,
        "process_probe": "NOT_RUN",
        "not_proven": list(NOT_PROVEN),
        "cloud_execution": "NOT_ASSESSED",
        "diagnostic_only": True,
    }


def doctor() -> dict[str, Any]:
    """Inspect version metadata without importing the optional SDK or spawning it."""
    report = _base_report("doctor")
    try:
        compatibility = inspect_compatibility()
        sdk_version = compatibility.sdk_version
        runtime_version = compatibility.runtime_version
        report["installation"] = {
            "sdk_installed": sdk_version is not None,
            "runtime_installed": runtime_version is not None,
            "sdk_version": _version(sdk_version),
            "runtime_version": _version(runtime_version),
            "pinned_version": SDK_VERSION,
            "versions_match": sdk_version is not None and sdk_version == runtime_version,
            "compatible": compatibility.compatible is True,
        }
        if sdk_version is None:
            report.update(status="UNAVAILABLE", reason="SDK_NOT_INSTALLED")
        elif runtime_version is None:
            report.update(status="UNAVAILABLE", reason="RUNTIME_NOT_INSTALLED")
        elif compatibility.compatible is not True:
            report.update(status="INCOMPATIBLE", reason="PINNED_PAIR_REQUIRED")
        else:
            report.update(status="COMPATIBLE", reason="PACKAGE_METADATA_ONLY")
    except Exception:
        # Never print metadata/import exceptions: they may contain local paths
        # or a value supplied by an independently installed distribution.
        report.update(status="ERROR", reason="INSTALLATION_INSPECTION_FAILED")
    return report


def _probe(timeout_seconds: float) -> dict[str, Any]:
    report = doctor()
    report["operation"] = "probe"
    if report["status"] != "COMPATIBLE":
        return report
    try:
        observed = probe_protocol(timeout_seconds=timeout_seconds)
        # Do not serialize the SDK result or exception wholesale. Native session
        # IDs, server text, paths and provider output have no place in this CLI.
        report["observations"] = {
            "runtime_started": observed.runtime_started is True,
            "initialized": observed.initialized is True,
            "session_created": observed.session_created is True,
            "runtime_closed": observed.runtime_closed is True,
            "server_identity_matches_protocol": (
                observed.server_name == SERVER_NAME and observed.server_version == SERVER_VERSION
            ),
        }
        complete = all(report["observations"].values())
        report.update(
            status="PROTOCOL_OBSERVED" if complete else "PROBE_INCOMPLETE",
            process_probe="OBSERVED" if complete else "INCOMPLETE",
            reason="NO_PROMPT_SUBMITTED" if complete else "PROTOCOL_OR_CLEANUP_UNCONFIRMED",
        )
    except Exception as exc:
        code = getattr(exc, "code", None)
        report.update(
            status="ERROR",
            process_probe="FAILED",
            reason=code if isinstance(code, str) and code in _PUBLIC_ERROR_CODES else "PROBE_FAILED",
            cleanup="NOT_PROVEN",
        )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description=__doc__)
    parser.set_defaults(operation="doctor")
    commands = parser.add_subparsers(dest="operation")
    commands.add_parser("doctor", help="Read SDK/runtime metadata without starting a process")
    probe = commands.add_parser("probe", help="Explicit provider-free SDK protocol probe")
    probe.add_argument(
        "--allow-protocol-probe",
        action="store_true",
        help="Allow an isolated initialize/session/close probe; no model prompt is submitted",
    )
    probe.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print one bounded JSON diagnostic; return 0 only for the requested check."""
    try:
        args = _parser().parse_args(argv)
        operation = args.operation or "doctor"
        if operation == "probe":
            if not args.allow_protocol_probe:
                report = _base_report("probe")
                report.update(status="BLOCKED", reason="EXPLICIT_PROTOCOL_PROBE_FLAG_REQUIRED")
            elif not math.isfinite(args.timeout_seconds) or not 1 <= args.timeout_seconds <= 60:
                raise _UsageError
            else:
                report = _probe(args.timeout_seconds)
        else:
            report = doctor()
    except _UsageError:
        report = _base_report("invalid")
        report.update(status="BLOCKED", reason="INVALID_ARGUMENTS")
        print(json.dumps(report, sort_keys=True))
        return 2
    except KeyboardInterrupt:
        report = _base_report("probe")
        report.update(status="ERROR", reason="INTERRUPTED", cleanup="NOT_PROVEN")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"COMPATIBLE", "PROTOCOL_OBSERVED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
