"""Run the public Sum API fixture through an existing HTTPS HyperTest platform.

Only a local Connector is launched. API, PostgreSQL, Worker and trusted Docker
Runner must already be deployed. No GitLab issue integration is configured or
granted. The private state directory preserves exact operation IDs on failure;
uncertain writes are never retried and a second Run is never created implicitly.

Use --dry-run to validate local inputs without network access or mutations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

FIXTURE_ORIGIN = "https://github.com/ZhangLiangchen/hypertest-one"
FIXTURE_PRD = "examples/api_sut/PRD.md"
PROFILE = "run-persistent-harness/v1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class AcceptanceError(RuntimeError):
    """Fixed, credential-free failure categories suitable for public evidence."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcceptanceError("HTTPS_REDIRECT_REJECTED")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def full_sha(value: str) -> str:
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value):
        raise argparse.ArgumentTypeError("commit must be a complete lowercase Git SHA")
    return value


def https_api(value: str) -> str:
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise argparse.ArgumentTypeError("invalid HTTPS API endpoint") from None
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path.rstrip("/") != "/api/v1" or any(c.isspace() for c in value)
            or (port is not None and not 1 <= port <= 65535)):
        raise argparse.ArgumentTypeError("use a credential-free HTTPS endpoint ending /api/v1")
    return value.rstrip("/")


def private_file(path: Path) -> bytes:
    """Read an owned 0600 regular file without following a final symlink."""
    descriptor = os.open(path.expanduser().absolute(), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or info.st_size > 4096):
            raise AcceptanceError("OPERATOR_FILE_MUST_BE_OWNED_REGULAR_0600")
        return os.read(descriptor, 4097)
    finally:
        os.close(descriptor)


def write_private(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(value)


def save_summary(state: Path, value: dict) -> None:
    # Only this new private directory is owned by the driver. Atomic replacement
    # preserves the latest known IDs if the process is stopped during collection.
    temporary = state / "summary.pending"
    write_private(temporary, (json.dumps(value, indent=2) + "\n").encode())
    temporary.replace(state / "summary.json")


def connector_environment(root: Path) -> dict[str, str]:
    # Keep native Provider/Git authentication, including HOME and SSH_AUTH_SOCK.
    # Platform credentials are deliberately absent from the device process.
    excluded = {"DATABASE_URL", "PGPASSWORD", "PGPASSFILE", "OPERATOR_KEY", "OPERATOR_KEY_FILE"}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("HYPERTEST_") and key not in excluded}
    env["PYTHONPATH"] = str(root / "src")
    return env


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--api-url", required=True, type=https_api)
    result.add_argument("--operator-key-file", required=True, type=Path)
    result.add_argument("--commit-sha", required=True, type=full_sha,
        help="published complete SHA of the public HyperTest Sum API fixture")
    result.add_argument("--state-dir", required=True, type=Path, help="new private directory; never reused")
    result.add_argument("--ca-file", type=Path, help="private CA, with certificate and hostname verification enabled")
    result.add_argument("--python", type=Path, default=Path(sys.executable), help="current worktree virtualenv interpreter")
    result.add_argument("--codex-binary", default="codex")
    result.add_argument("--timeout-seconds", type=int, default=2400)
    result.add_argument("--dry-run", action="store_true", help="local validation only; no network, files or processes created")
    result.add_argument("--stop-connector-on-success", action="store_true",
        help="stop only this Connector after Job success and confirmed CLOSED binding")
    return result


class API:
    def __init__(self, url: str, key: str, ca_file: Path | None):
        self.url, self.key = url, key
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context))

    def request(self, path: str, body: dict | None = None, *, raw=False, timeout=180):
        req = urllib.request.Request(self.url + path, method="GET" if body is None else "POST",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Hypertest-Operator-Key": self.key})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
            if len(content) > MAX_RESPONSE_BYTES:
                raise AcceptanceError("API_RESPONSE_TOO_LARGE")
            return content if raw else json.loads(content)
        except urllib.error.HTTPError as exc:
            # Error bodies, URLs and chained urllib exceptions may contain task
            # text or ingress details. Keep only status and operation certainty.
            raise AcceptanceError(f"HTTP_{exc.code}_" + ("READ_FAILED" if body is None else "WRITE_REJECTED")) from None
        except (OSError, urllib.error.URLError, TimeoutError):
            raise AcceptanceError("READ_UNAVAILABLE" if body is None else "WRITE_OUTCOME_UNKNOWN") from None
        except (ValueError, UnicodeError):
            raise AcceptanceError("INVALID_API_RESPONSE") from None


def pinned_prd(root: Path, commit: str) -> bytes:
    try:
        content = subprocess.check_output(["git", "show", f"{commit}:{FIXTURE_PRD}"], cwd=root,
                                          stderr=subprocess.DEVNULL, timeout=20)
        # Verify the selected fixture includes the positive application as well.
        subprocess.run(["git", "cat-file", "-e", f"{commit}:examples/api_sut/app.py"], cwd=root,
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        content.decode("utf-8")
        if not 1 <= len(content) <= 1024 * 1024:
            raise AcceptanceError("PINNED_FIXTURE_PRD_UNAVAILABLE")
        return content
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise AcceptanceError("PINNED_FIXTURE_PRD_UNAVAILABLE") from None


def stop_connector(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    # Only our independently created process group, after a CLOSED binding.
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        raise AcceptanceError("CONNECTOR_SHUTDOWN_UNCONFIRMED") from None


def collect(api: API, summary: dict) -> None:
    run_id = summary["run_id"]
    harness = api.request(f"/test-runs/{run_id}/harness")
    executions = api.request(f"/test-runs/{run_id}/executions")
    evidence = api.request(f"/test-runs/{run_id}/evidence")
    verdicts = api.request(f"/test-runs/{run_id}/verdicts")
    binding = harness.get("binding") or {}
    selection = harness.get("selection") or {}
    reports = harness.get("reports") or []
    summary.update(binding={key: binding.get(key) for key in ("id", "status", "binding_epoch", "primary_agent_session_id")},
        selection={key: selection.get(key) for key in ("mode", "node_id")},
        executions=[{key: item.get(key) for key in ("id", "key", "status", "outcome", "runner_backend", "source_commit", "execution_spec_sha256")}
                    for item in executions],
        evidence=[{key: item.get(key) for key in ("id", "key", "execution_id", "trust_level", "status", "sha256")}
                  for item in evidence],
        reports=[{key: item.get(key) for key in ("id", "content_sha256", "verdict_key", "verdict_decision")} for item in reports],
        verdicts=[{key: item.get(key) for key in ("id", "key", "scope", "status", "decision", "evidence_manifest_sha256")}
                  for item in verdicts],
        issue_operation_count=len(harness.get("issues") or []))
    if summary["job_status"] != "SUCCEEDED" or binding.get("status") != "CLOSED":
        raise AcceptanceError("RUN_REQUIRES_EXPLICIT_OPERATOR_FOLLOWUP")
    if selection.get("mode") != "LOCAL_CONNECTOR" or selection.get("node_id") != summary["node_id"]:
        raise AcceptanceError("LOCAL_PLACEMENT_MISMATCH")
    if not executions or any(item["runner_backend"] != "docker" or item["status"] != "COMPLETED"
            or item["outcome"] != "PASS" or item["source_commit"] != summary["commit_sha"] for item in executions):
        raise AcceptanceError("TRUSTED_RUNNER_DID_NOT_PASS_PINNED_FIXTURE")
    execution_ids = {item["id"] for item in executions}
    if not evidence or not any(item["status"] == "VERIFIED" and item["trust_level"] == "RUNNER"
                              and item["execution_id"] in execution_ids for item in evidence):
        raise AcceptanceError("VERIFIED_RUNNER_EVIDENCE_MISSING")
    if summary["issue_operation_count"]:
        raise AcceptanceError("UNEXPECTED_ISSUE_OPERATION")
    if not reports or reports[0].get("verdict_decision") != "RELEASE_READY":
        raise AcceptanceError("POSITIVE_FIXTURE_FINAL_REPORT_NOT_READY")
    if not any(item["key"] == reports[0]["verdict_key"] and item["scope"] == "TEST_RUN"
               and item["status"] == "FINAL" and item["decision"] == "RELEASE_READY" for item in verdicts):
        raise AcceptanceError("REPORT_FINAL_VERDICT_NOT_INDEPENDENTLY_CONFIRMED")
    for report in reports:
        content = api.request(f"/reports/{report['id']}/content", raw=True)
        if sha256(content) != report["content_sha256"]:
            raise AcceptanceError("REPORT_CONTENT_HASH_MISMATCH")
    summary["report_content_verified"] = True


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    state = args.state_dir.expanduser().absolute()
    process = None
    summary = {"acceptance_status": "PREPARING", "started_at": datetime.now(UTC).isoformat(),
        "topology": "existing HTTPS platform and trusted server Runner; independent local Connector and native Codex",
        "api_endpoint_sha256": sha256(args.api_url.encode()), "fixture_origin": FIXTURE_ORIGIN,
        "commit_sha": args.commit_sha, "issue_integration": "NOT_CONFIGURED_NO_NEW_ISSUE_AUTHORIZED"}
    try:
        if not 60 <= args.timeout_seconds <= 7200:
            raise AcceptanceError("TIMEOUT_MUST_BE_BETWEEN_60_AND_7200_SECONDS")
        key = private_file(args.operator_key_file).decode("ascii").strip()
        if not key or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key):
            raise AcceptanceError("OPERATOR_KEY_INVALID")
        if state.exists() or state.resolve() != state:
            raise AcceptanceError("STATE_DIRECTORY_MUST_BE_NEW_AND_CANONICAL")
        if not args.python.is_file() or not os.access(args.python, os.X_OK) or not shutil.which(args.codex_binary):
            raise AcceptanceError("LOCAL_PYTHON_OR_CODEX_UNAVAILABLE")
        ca_file = args.ca_file.expanduser().resolve() if args.ca_file else None
        # Constructing the context verifies the CA file without making a request.
        api = API(args.api_url, key, ca_file)
        prd = pinned_prd(root, args.commit_sha)
        summary["prd_sha256"] = sha256(prd)
        if ca_file:
            summary["trust_ca_sha256"] = sha256(ca_file.read_bytes())
        if args.dry_run:
            summary["acceptance_status"] = "LOCAL_VALIDATION_PASSED_NO_NETWORK"
            print(json.dumps(summary, indent=2))
            return 0
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(state, 0o700)
        save_summary(state, summary)
        api.request("/health")
        # No POST is automatically retried. Persist each idempotency key before
        # its first use, so operators can reconcile exact identities if needed.
        summary["operation_keys"] = {name: "online-" + name + ":" + uuid4().hex
                                     for name in ("source", "run", "job")}
        summary["source_request_id"] = str(uuid4())
        save_summary(state, summary)
        project = api.request("/projects", {"key": "ADR15_ONLINE_" + uuid4().hex[:10].upper(),
            "name": "ADR-015 production local Harness acceptance", "repository_url": FIXTURE_ORIGIN, "default_branch": "main"})
        summary["project_id"] = project["id"]
        save_summary(state, summary)
        paired = api.request("/harness-nodes/pair", {"node_key": "online-" + uuid4().hex,
            "display_name": "ADR-015 local Codex", "expires_in_days": 30})
        node = paired["node"]
        summary["node_id"], summary["device_grant_id"] = node["id"], paired["grant_id"]
        token_path = state / "device.token"
        write_private(token_path, paired.pop("device_token").encode())
        save_summary(state, summary)
        for capability in ("harness", "source_acquisition"):
            api.request(f"/harness-nodes/{node['id']}/capabilities", {"project_id": project["id"],
                "capability": capability, "policy_version": "online-v1",
                "constraints": {"allowed_origins": [FIXTURE_ORIGIN]} if capability == "source_acquisition" else {}})
        config = {"api_url": args.api_url, "node_id": node["id"], "node_key": node["node_key"],
            "state_dir": str(state / "node"), "device_token_file": str(token_path), "codex_binary": args.codex_binary,
            "source": {"allowed_origins": [FIXTURE_ORIGIN]}}
        if ca_file:
            config["ca_file"] = str(ca_file)
        config_path = state / "connector.json"
        write_private(config_path, json.dumps(config).encode())
        log_path = state / "connector.log"
        write_private(log_path, b"")
        with log_path.open("ab") as output:
            process = subprocess.Popen([str(args.python), "-m", "hypertest.connector", "--config", str(config_path)],
                cwd=root, env=connector_environment(root), stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        summary["connector_pid"] = process.pid
        save_summary(state, summary)
        for _ in range(60):
            if process.poll() is not None:
                raise AcceptanceError("LOCAL_CONNECTOR_EXITED")
            nodes = api.request("/harness-nodes")
            current = next((item for item in nodes if item["id"] == node["id"]), {})
            if current.get("presence") == "ONLINE":
                break
            time.sleep(1)
        else:
            raise AcceptanceError("LOCAL_CONNECTOR_NOT_ONLINE")
        print("Verified HTTPS and WSS; local Codex Connector online.", flush=True)
        transfer = api.request(f"/projects/{project['id']}/source-transfers", {"node_id": node["id"],
            "request_id": summary["source_request_id"], "idempotency_key": summary["operation_keys"]["source"],
            "origin": FIXTURE_ORIGIN, "commit_sha": args.commit_sha, "policy_version": "online-v1"})
        summary["source_transfer_id"] = transfer["id"]
        save_summary(state, summary)
        api.request(f"/source-transfers/{transfer['id']}/dispatch", {})
        transfer = api.request(f"/source-transfers/{transfer['id']}")
        summary["source_status"], summary["bundle_sha256"] = transfer["status"], transfer.get("bundle_sha256")
        save_summary(state, summary)
        if transfer["status"] != "ACCEPTED":
            raise AcceptanceError("SOURCE_NOT_INDEPENDENTLY_ACCEPTED")
        print("Pinned source independently accepted by the deployed HTTPS receiver.", flush=True)
        run = api.request(f"/projects/{project['id']}/runs/bootstrap", {"repository_url": FIXTURE_ORIGIN,
            "commit_sha": args.commit_sha, "prd_text": prd.decode(), "configuration_text": "{}",
            "environment": {"profile_id": "python-api-v2", "service": {"app": "examples.api_sut.app:app",
                "health_path": "/health", "startup_timeout_seconds": 20}}, "harness_mode": "LOCAL_CONNECTOR",
            "harness_node_id": node["id"], "source_bundle_transfer_id": transfer["id"],
            "idempotency_key": summary["operation_keys"]["run"]})
        summary["run_id"] = run["id"]
        save_summary(state, summary)
        job = api.request(f"/test-runs/{run['id']}/jobs", {"operation": "ADVANCE_RUN",
            "idempotency_key": summary["operation_keys"]["job"], "payload": {"execution_profile": PROFILE,
                "prepare_workspace": True, "backend": "docker", "max_steps": 32, "timeout_seconds": 300}})
        summary.update(job_id=job["id"], job_status=job["status"], acceptance_status="RUNNING")
        save_summary(state, summary)
        print(f"Production acceptance queued: run={run['id']} job={job['id']}", flush=True)
        deadline, last_status, read_failures = time.monotonic() + args.timeout_seconds, None, 0
        while time.monotonic() < deadline:
            try:
                job = api.request(f"/jobs/{summary['job_id']}", timeout=30)
                read_failures = 0
            except AcceptanceError as exc:
                if str(exc) != "READ_UNAVAILABLE" or read_failures >= 12:
                    raise
                read_failures += 1
                time.sleep(5)
                continue  # Only an idempotent GET may be retried.
            summary["job_status"] = job["status"]
            if last_status != job["status"]:
                print("Job " + job["status"], flush=True)
                last_status = job["status"]
                save_summary(state, summary)
            if job["status"] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(5)
        else:
            raise AcceptanceError("ACCEPTANCE_TIMEOUT_KEEP_ORIGINAL_RUN")
        collect(api, summary)
        summary["acceptance_status"] = "PASSED"
        if args.stop_connector_on_success:
            stop_connector(process)
            summary["connector_status"] = "STOPPED_AFTER_CLOSED_BINDING"
        else:
            summary["connector_status"] = "LEFT_RUNNING_WITH_PRIVATE_STATE"
        print("Real local Codex → production Docker Runner → verified Evidence → RELEASE_READY report passed.", flush=True)
        return 0
    except BaseException as exc:
        summary["acceptance_status"] = "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED"
        summary["error_category"] = str(exc) if isinstance(exc, AcceptanceError) else type(exc).__name__
        # Preserve the exact node, source and Run for explicit recovery. Never
        # cancel/retry work or stop a possibly active Provider in this handler.
        summary["connector_status"] = "PRESERVED_FOR_OPERATOR_FOLLOWUP" if process and process.poll() is None else "NOT_RUNNING"
        print("Acceptance stopped: " + summary["error_category"] + "; preserve original IDs/state for explicit follow-up.", file=sys.stderr)
        return 1
    finally:
        if state.is_dir() and "operation_keys" in summary:
            summary["finished_at"] = datetime.now(UTC).isoformat()
            save_summary(state, summary)


if __name__ == "__main__":
    raise SystemExit(main())
