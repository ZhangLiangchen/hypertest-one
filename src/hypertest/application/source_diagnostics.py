"""Allowlisted source-preparation observations; raw Git output never leaves this module."""

from __future__ import annotations

import errno

from hypertest.application.services import ConflictError
from hypertest.runner.backends import ProcessResult

SOURCE_DIAGNOSTIC_VERSION = "hypertest.source-preparation-diagnostic/v1"
GIT_OUTPUT_LIMIT = 16 * 1024
_TRUNCATION_MARKER = b"[HyperTest collector truncated oversized output]"

SOURCE_PREPARATION_STAGES = {
    "validate_input": "validate frozen source input",
    "create_workspace": "create the managed workspace",
    "git_init": "initialize the repository",
    "configure_remote": "configure the repository origin",
    "fetch_commit": "fetch the pinned commit",
    "checkout_commit": "check out the pinned commit",
    "validate_checkout": "verify the pinned checkout",
    "publish_workspace": "publish the managed checkout",
}

# Only platform-owned text is persisted. These are diagnostic suggestions, not
# proof of a remote repository's existence, credential state, or root cause.
SOURCE_PREPARATION_CATEGORIES = {
    "authentication": (
        "Git could not authenticate using the configured access.",
        "Ask the operator to check the configured Git credentials and access, then retry this request.",
        True,
    ),
    "access_or_missing_repository": (
        "The repository was unavailable or access was denied.",
        "Check that the repository exists and the configured Git and proxy access allow it, then retry.",
        True,
    ),
    "network": (
        "Git could not reach the repository through the configured network.",
        "Check host DNS, network and configured Git proxy availability, then retry.",
        True,
    ),
    "tls": (
        "Git could not verify the remote connection's certificate.",
        "Ask the operator to check the configured certificate trust and proxy; retain verification, then retry.",
        True,
    ),
    "revision_not_found": (
        "Git could not fetch or check out the pinned commit.",
        "Check that the frozen commit is available to this repository; retry after access is restored, or create a new round for a different SHA.",
        True,
    ),
    "storage": (
        "The managed source workspace could not be read or written.",
        "Ask the operator to check workspace permissions, free space and filesystem availability, then retry.",
        True,
    ),
    "timeout": (
        "The source preparation operation exceeded its time limit.",
        "Check repository availability, the configured network and host load, then explicitly retry.",
        True,
    ),
    "git_unavailable": (
        "The Git executable was unavailable on the Worker.",
        "Ask the operator to restore Git in the Worker runtime, then retry.",
        True,
    ),
    "invalid_source": (
        "The frozen source input is unsupported for automatic preparation.",
        "Review the repository transport and full commit SHA; create a new round to change frozen inputs, or use an existing matching workspace.",
        False,
    ),
    "checkout_integrity": (
        "The managed checkout did not match the frozen repository and commit.",
        "Ask the operator to inspect the original checkout without changing frozen history; use a new round if the source inputs must change.",
        False,
    ),
    "unknown": (
        "Git source preparation failed without a recognized safe diagnostic.",
        "Ask the operator to check configured Git access, the pinned commit, network and workspace health before retrying.",
        True,
    ),
}


class SourcePreparationError(ConflictError):
    """A preparation failure with a bounded, credential-free Operational payload."""

    def __init__(self, *, stage: str, category: str, exit_code: int | None = None,
                 timed_out: bool = False, output_truncated: bool = False) -> None:
        # Validate identifiers rather than passing arbitrary exception text to
        # API/Job/Audit consumers. No command, URL, path or output is retained.
        if stage not in SOURCE_PREPARATION_STAGES:
            raise ValueError("unsupported source preparation diagnostic stage")
        if category not in SOURCE_PREPARATION_CATEGORIES:
            raise ValueError("unsupported source preparation diagnostic category")
        summary, action, retryable = SOURCE_PREPARATION_CATEGORIES[category]
        self.diagnostic = {
            "schema_version": SOURCE_DIAGNOSTIC_VERSION,
            "stage": stage,
            "category": category,
            "summary": summary,
            "action": action,
            "retryable": retryable,
            "exit_code": exit_code if type(exit_code) is int and -255 <= exit_code <= 255 else None,
            "timed_out": bool(timed_out),
            "output_truncated": bool(output_truncated),
        }
        super().__init__(f"Pinned source preparation failed while attempting to {SOURCE_PREPARATION_STAGES[stage]}. {summary} {action}")


def safe_source_diagnostic(value: object) -> dict | None:
    """Project stored diagnostics through the v1 allowlist before any display."""
    if not isinstance(value, dict) or value.get("schema_version") != SOURCE_DIAGNOSTIC_VERSION:
        return None
    stage, category = value.get("stage"), value.get("category")
    if (not isinstance(stage, str) or stage not in SOURCE_PREPARATION_STAGES
            or not isinstance(category, str) or category not in SOURCE_PREPARATION_CATEGORIES):
        return None
    if any(type(value.get(field)) is not bool for field in (
        "retryable", "timed_out", "output_truncated",
    )):
        return None
    exit_code = value.get("exit_code")
    if exit_code is not None and (type(exit_code) is not int or not -255 <= exit_code <= 255):
        return None
    return SourcePreparationError(
        stage=stage, category=category, exit_code=exit_code,
        timed_out=value["timed_out"], output_truncated=value["output_truncated"],
    ).diagnostic


def git_failure(stage: str, result: ProcessResult) -> SourcePreparationError:
    """Classify a bounded observation, then discard all subprocess output."""
    # run_process is also bounded at collection time. The second bound keeps
    # injected/test results and future collectors from widening this boundary.
    observation = result.stderr[:GIT_OUTPUT_LIMIT].decode("utf-8", errors="replace").lower()
    if result.timed_out:
        category = "timeout"
    elif any(marker in observation for marker in (
        "authentication failed", "could not read username", "could not read password",
        "terminal prompts disabled", "invalid username or password", "permission denied (publickey)",
    )):
        category = "authentication"
    elif any(marker in observation for marker in (
        "ssl certificate problem", "server certificate verification failed", "certificate verify failed",
        "self-signed certificate", "unable to get local issuer certificate",
    )):
        category = "tls"
    elif any(marker in observation for marker in (
        "could not resolve host", "could not resolve proxy", "failed to connect", "connection refused",
        "connection reset", "network is unreachable", "connection timed out",
        "proxy connect aborted", "connect tunnel failed", "remote end hung up unexpectedly",
        "requested url returned error: 502", "requested url returned error: 503", "requested url returned error: 504",
    )) and not any(marker in observation for marker in (
        "requested url returned error: 403", "requested url returned error: 404",
    )):
        category = "network"
    elif any(marker in observation for marker in (
        "repository not found", "access denied", "requested url returned error: 403",
        "requested url returned error: 404", "does not appear to be a git repository",
    )):
        category = "access_or_missing_repository"
    elif any(marker in observation for marker in (
        "not our ref", "couldn't find remote ref", "could not find remote ref", "reference is not a tree",
        "pathspec", "not a valid object name", "bad object", "unable to read tree",
    )):
        category = "revision_not_found"
    elif any(marker in observation for marker in (
        "no space left on device", "disk quota exceeded", "read-only file system", "permission denied",
        "unable to create", "cannot create", "could not create", "could not lock",
    )):
        category = "storage"
    else:
        category = "unknown"
    return SourcePreparationError(
        stage=stage, category=category, exit_code=result.exit_code, timed_out=result.timed_out,
        output_truncated=len(result.stderr) > GIT_OUTPUT_LIMIT
        or len(result.stdout) > GIT_OUTPUT_LIMIT
        or _TRUNCATION_MARKER in result.stderr
        or _TRUNCATION_MARKER in result.stdout,
    )


def filesystem_failure(stage: str, error: OSError, *, spawning_git: bool = False) -> SourcePreparationError:
    if spawning_git and isinstance(error, FileNotFoundError):
        category = "git_unavailable"
    elif error.errno in {errno.EACCES, errno.EPERM, errno.ENOSPC, errno.EDQUOT,
                         errno.EROFS, errno.ENOENT, errno.ENOTDIR, errno.EIO, errno.ELOOP}:
        category = "storage"
    else:
        category = "unknown"
    return SourcePreparationError(stage=stage, category=category)
