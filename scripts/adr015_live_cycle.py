"""Isolated real Codex/WSS/HTTPS cycle with a remote Docker daemon.

Requires a migrated disposable database. Never changes production services or
network rules. Third-party GitLab/private-Git acceptance is recorded separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4


def load_gitlab_config(path: Path) -> dict:
    """Load the exact approved destination from an operator-owned local file."""
    try:
        path = path.expanduser().absolute()
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or path.stat().st_size > 100_000):
            raise ValueError
        config = json.loads(path.read_text())
        if set(config) != {"base_url", "project_id", "assignee", "assignee_id", "integration_id"}:
            raise ValueError
        if any(type(config[key]) is not int or config[key] < 1 for key in ("project_id", "assignee_id")):
            raise ValueError
        if any(not isinstance(config[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", config[key])
               for key in ("assignee", "integration_id")):
            raise ValueError
        if not isinstance(config["base_url"], str):
            raise ValueError
        target = urlsplit(config["base_url"])
        if (target.scheme != "https" or not target.hostname or target.username or target.password
                or target.query or target.fragment or target.path not in {"", "/"}
                or any(character.isspace() for character in config["base_url"])):
            raise ValueError
        _ = target.port
        config["base_url"] = config["base_url"].rstrip("/")
        return config
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError("GitLab acceptance requires a private 0600 JSON file with an exact HTTPS target and assignee") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--docker-host", default="ssh://hypertest-one")
    parser.add_argument("--port", type=int, default=18415)
    parser.add_argument("--broken", action="store_true")
    parser.add_argument("--private-origin")
    parser.add_argument("--private-sha")
    parser.add_argument("--gitlab-test-issue", action="store_true",
        help="Create one Issue through the live Agent using the explicitly approved local configuration")
    parser.add_argument("--gitlab-config", type=Path,
        help="Private 0600 JSON file with the approved GitLab base_url/project_id/assignee/assignee_id/integration_id")
    parser.add_argument("--keep-services", action="store_true")
    args = parser.parse_args()
    if args.gitlab_test_issue != (args.gitlab_config is not None):
        parser.error("--gitlab-test-issue and --gitlab-config must be supplied together")
    if args.gitlab_test_issue and not args.broken:
        parser.error("Issue acceptance requires the deliberately broken fixture (--broken)")
    try:
        gitlab_config = load_gitlab_config(args.gitlab_config) if args.gitlab_config else None
    except ValueError as exc:
        parser.error(str(exc))
    root = Path(__file__).resolve().parents[1]
    state = args.state_dir.resolve()
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(state, 0o700)
    cert, key = state / "tls.crt", state / "tls.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(key, 0o600)
    # Docker's SSH helper uses this strictly key-only wrapper. No forwarding.
    bin_dir = state / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text('#!/bin/sh\nexec /usr/bin/ssh -o BatchMode=yes -o PreferredAuthentications=publickey "$@"\n')
    ssh.chmod(0o700)
    operator_key = secrets.token_urlsafe(48)
    issue_policy = state / "gitlab-policy.json"
    issue_policy.write_text(json.dumps({"version": "hypertest.gitlab-policy/v1", "projects": {}}))
    issue_policy.chmod(0o600)
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "DOCKER_HOST": args.docker_host,
        "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
        "HYPERTEST_DATABASE_URL": args.database_url, "HYPERTEST_EXECUTION_MODE": "queued",
        "HYPERTEST_HARNESS_MODE": "bridge", "HYPERTEST_CONNECTOR_OPERATOR_KEY": operator_key,
        "HYPERTEST_GITLAB_POLICY_FILE": str(issue_policy),
        "HYPERTEST_WORKSPACE_ROOT": str(state), "HYPERTEST_ARTIFACT_ROOT": str(state / "artifacts"),
        "HYPERTEST_HARNESS_MAX_SECONDS": "1800", "HYPERTEST_WORKER_LEASE_SECONDS": "60"}
    api = f"https://localhost:{args.port}/api/v1"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
    def request(path, body=None):
        req = urllib.request.Request(api + path, method="GET" if body is None else "POST",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Hypertest-Operator-Key": operator_key})
        try:
            with opener.open(req, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read(2000).decode()}") from None
    processes = []
    def launch(name, command, child_env=env):
        log = (state / f"{name}.log").open("wb")
        process = subprocess.Popen(command, cwd=root, env=child_env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        log.close()
        processes.append(process)
        return process
    summary = {"acceptance_status": "RUNNING",
        "topology": "isolated TLS API/Worker, independent local Connector, remote Docker over strict SSH",
        "private_git": "NOT_RUN_NO_AUTHORIZED_PRIVATE_REPOSITORY", "gitlab": "NOT_RUN_NO_AUTHORIZED_TEST_PROJECT",
        "tls_certificate_sha256": hashlib.sha256(cert.read_bytes()).hexdigest()}
    try:
        launch("api", [sys.executable, "-m", "uvicorn", "hypertest.main:app", "--host", "127.0.0.1", "--port", str(args.port),
                       "--ssl-keyfile", str(key), "--ssl-certfile", str(cert)])
        launch("worker", [sys.executable, "-m", "hypertest.worker"])
        for _ in range(60):
            try:
                request("/health")
                break
            except (OSError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError("isolated API did not become ready")
        project = request("/projects", {"key": "ADR15_" + uuid4().hex[:10].upper(), "name": "ADR-015 real local Harness acceptance",
            "repository_url": "https://github.com/ZhangLiangchen/hypertest-one", "default_branch": "main"})
        paired = request("/harness-nodes/pair", {"node_key": "live-" + uuid4().hex, "display_name": "ADR-015 local Codex"})
        node = paired["node"]
        token_path = state / "device.token"
        token_path.write_text(paired["device_token"])
        token_path.chmod(0o600)
        origin = project["repository_url"]
        for capability in ("harness", "source_acquisition"):
            request(f"/harness-nodes/{node['id']}/capabilities", {"project_id": project["id"], "capability": capability,
                "policy_version": "live-v1", "constraints": {"allowed_origins": [origin]} if capability == "source_acquisition" else {}})
        config = {"api_url": api, "node_id": node["id"], "node_key": node["node_key"], "state_dir": str(state / "node"),
            "device_token_file": str(token_path), "ca_file": str(cert), "source": {"allowed_origins": [origin]}}
        if args.private_origin:
            if not args.private_sha:
                raise ValueError("private source requires its explicit fixed SHA")
            config["source"]["allowed_origins"].append(args.private_origin)
        if args.gitlab_test_issue:
            # Authorization is explicit and supplied locally; never publish a
            # real private project or account in this reusable driver.
            integration_id = gitlab_config["integration_id"]
            target = {"base_url": gitlab_config["base_url"], "gitlab_project_id": gitlab_config["project_id"],
                      "assignee_ids": [gitlab_config["assignee_id"]], "credential_kind": "glab"}
            config["issues"] = {"integrations": {integration_id: target}}
            request(f"/harness-nodes/{node['id']}/capabilities", {"project_id": project["id"], "capability": "issue_executor",
                "policy_version": "live-v1", "constraints": {key: value for key, value in {**target, "integration_id": integration_id}.items() if key != "credential_kind"}})
            issue_policy.write_text(json.dumps({"version": "hypertest.gitlab-policy/v1", "projects": {project["id"]: {
                "base_url": target["base_url"], "project_id": gitlab_config["project_id"],
                "assignees": {gitlab_config["assignee"]: gitlab_config["assignee_id"]}, "allow_create": True,
                "executor_mode": "LOCAL_CONNECTOR", "executor_node_id": node["id"], "integration_id": integration_id}}}))
        config_path = state / "connector.json"
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)
        # No database/operator credentials are inherited by the actual device process.
        connector_env = {key: value for key, value in os.environ.items() if not key.startswith("HYPERTEST_")}
        connector_env["PYTHONPATH"] = str(root / "src")
        launch("connector", [sys.executable, "-m", "hypertest.connector", "--config", str(config_path)], connector_env)
        for _ in range(60):
            if next(item for item in request("/harness-nodes") if item["id"] == node["id"])["presence"] == "ONLINE":
                break
            time.sleep(1)
        else:
            raise RuntimeError("real Connector did not connect")
        if args.private_origin:
            private_project = request("/projects", {"key": "ADR15_PRIVATE_" + uuid4().hex[:8].upper(),
                "name": "Private source acceptance", "repository_url": args.private_origin})
            request(f"/harness-nodes/{node['id']}/capabilities", {"project_id": private_project["id"], "capability": "source_acquisition",
                "policy_version": "live-v1", "constraints": {"allowed_origins": [args.private_origin]}})
            private_transfer = request(f"/projects/{private_project['id']}/source-transfers", {"node_id": node["id"], "request_id": str(uuid4()),
                "idempotency_key": "private-source:" + uuid4().hex, "origin": args.private_origin, "commit_sha": args.private_sha, "policy_version": "live-v1"})
            private_transfer = request(f"/source-transfers/{private_transfer['id']}/dispatch", {})
            if private_transfer["status"] != "ACCEPTED":
                raise RuntimeError("private Git source not independently accepted")
            summary["private_git"] = {"status": "ACCEPTED", "origin": args.private_origin,
                "commit_sha": args.private_sha, "transfer_id": private_transfer["id"], "bundle_sha256": private_transfer["bundle_sha256"]}
            print("Private Git fetched with local credentials; HTTPS receiver independently accepted source.", flush=True)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        print("Real WSS device online; acquiring pinned Git source.", flush=True)
        transfer = request(f"/projects/{project['id']}/source-transfers", {"node_id": node["id"], "request_id": str(uuid4()),
            "idempotency_key": "live-source:" + uuid4().hex, "origin": origin, "commit_sha": commit, "policy_version": "live-v1"})
        transfer = request(f"/source-transfers/{transfer['id']}/dispatch", {})
        assert transfer["status"] == "ACCEPTED", transfer
        print("Source accepted after independent HTTPS/Git object verification.", flush=True)
        prd = (root / "examples/api_sut/PRD.md").read_text()
        if args.gitlab_test_issue:
            prd += ("\n\nAuthorized integration acceptance: after the first accepted Finding, request exactly one GitLab issue using request_gitlab_issue, assignee "
                + gitlab_config["assignee"]
                + ". Title must start [HyperTest ADR-015 acceptance]. Explain in its description that this is a harness integration acceptance test against a deliberately broken Sum API fixture, not a business defect in the destination project. Include the actual Finding and evidence references. Do not create a second issue. Query the operation until confirmed before reporting.\n")
        run = request(f"/projects/{project['id']}/runs/bootstrap", {"repository_url": origin, "commit_sha": commit,
            "prd_text": prd, "configuration_text": "{}",
            "environment": {"profile_id": "python-api-v2", "service": {"app": "examples.api_sut.broken_app:app" if args.broken else "examples.api_sut.app:app",
                "health_path": "/health", "startup_timeout_seconds": 20}},
            "harness_mode": "LOCAL_CONNECTOR", "harness_node_id": node["id"], "source_bundle_transfer_id": transfer["id"],
            "idempotency_key": "live-run:" + uuid4().hex})
        job = request(f"/test-runs/{run['id']}/jobs", {"operation": "ADVANCE_RUN", "idempotency_key": "live-job:" + uuid4().hex,
            "payload": {"execution_profile": "run-persistent-harness/v1", "prepare_workspace": True,
                "backend": "docker", "max_steps": 32, "timeout_seconds": 300}})
        summary.update(project_id=project["id"], node_id=node["id"], source_transfer_id=transfer["id"],
                       commit_sha=commit, bundle_sha256=transfer["bundle_sha256"], run_id=run["id"], job_id=job["id"])
        (state / "summary.json").write_text(json.dumps(summary, indent=2))
        print(f"Real cycle queued: run={run['id']} job={job['id']}", flush=True)
        for iteration in range(900):
            job = request(f"/jobs/{job['id']}")
            if iteration % 15 == 0:
                print(f"Job {job['status']}", flush=True)
            if job["status"] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(2)
        harness = request(f"/test-runs/{run['id']}/harness")
        executions = request(f"/test-runs/{run['id']}/executions")
        summary.update(job_status=job["status"], job_result=job.get("result"), job_error=job.get("error"), harness=harness)
        summary["executions"] = executions
        if args.gitlab_test_issue:
            summary["gitlab"] = harness["issues"]
        (state / "summary.json").write_text(json.dumps(summary, indent=2))
        if job["status"] != "SUCCEEDED" or not harness["reports"]:
            raise RuntimeError(f"real cycle incomplete: {job['status']}; inspect {state}")
        if not executions or any(item["status"] != "COMPLETED" for item in executions):
            raise RuntimeError("cycle reported but formal execution did not complete; preserve failure and repair infrastructure")
        expected = "RELEASE_BLOCKED" if args.broken else "RELEASE_READY"
        if harness["reports"][-1]["verdict_decision"] != expected:
            raise RuntimeError("formal quality decision does not match the fixture")
        if args.gitlab_test_issue and (len(harness["issues"]) != 1 or harness["issues"][0]["status"] != "SUCCEEDED"):
            raise RuntimeError("authorized test Issue has not been independently confirmed")
        summary["acceptance_status"] = "PASSED"
        print("Real local Codex → remote Docker → Evidence/Gate → accepted report succeeded.", flush=True)
    except BaseException as exc:
        summary["acceptance_status"] = "FAILED"
        # Do not copy arbitrary transport/provider exception text into evidence.
        summary["acceptance_error_type"] = type(exc).__name__
        raise
    finally:
        (state / "summary.json").write_text(json.dumps(summary, indent=2))
        if args.keep_services:
            # Operational restart data stays private alongside the disposable state.
            (state / "operator.key").write_text(operator_key)
            (state / "operator.key").chmod(0o600)
            (state / "pids.json").write_text(json.dumps([process.pid for process in processes]))
        else:
            for process in reversed(processes):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in processes:
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
