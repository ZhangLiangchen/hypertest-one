#!/usr/bin/env python3
"""Stage a macOS Cloud Worker LaunchAgent and narrowly scoped BFF config.

This command never installs, starts, or restarts a service and never reads a
credential. Deploy the staged files only alongside the matching API release.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

LABEL = "com.hypertest.cloud-native-worker"
ANCHOR = "        location ~ ^/api/v1/(local-archive|cli-authorizations)/ {"
LEGACY_ROUTES = "claim|renew|assert|fence|resolution/accept|resolution/assert|submit|validate-payload|receipt|page|artifact"
CURRENT_ROUTES = ("auth-observation|claim|claim/state|claim/reconcile|renew|assert|fence|resolution/accept|resolution/assert|"
                  "submit|validate-payload|receipt|page|artifact|live-question/open|live-question/lookup|"
                  "live-question/poll|live-question/finish")
ROUTES = (CURRENT_ROUTES + "|native-session-inspection/state|native-session-inspection/claim|"
          "native-session-inspection/claim-state|native-session-inspection/claim-reconcile|"
          "native-session-inspection/assert|native-session-inspection/finish")
LOCATION = f'''        # Host Cloud Worker: dedicated bearer only, no Operator key.
        location ~ ^/api/v1/cloud/worker/({ROUTES})$ {{
            limit_except POST {{ deny all; }}
            client_max_body_size 12m;
            set $hypertest_api api:8000;
            proxy_pass http://$hypertest_api$request_uri;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Hypertest-Operator-Key "";
            proxy_set_header Forwarded "";
            proxy_read_timeout 60s;
        }}
'''


def bff_config(original: str) -> str:
    if original.count(ANCHOR) != 1:
        raise ValueError("Unexpected BFF config")
    if LOCATION in original and original.count("location ~ ^/api/v1/cloud/worker/") == 1:
        return original
    if "location ~ ^/api/v1/cloud/worker/" in original:
        for routes in (CURRENT_ROUTES, LEGACY_ROUTES, LEGACY_ROUTES + "|live-question/(open|lookup|poll|finish)",
                       "auth-observation|" + LEGACY_ROUTES + "|live-question/(open|lookup|poll|finish)"):
            previous = LOCATION.replace(ROUTES, routes)
            if previous in original and original.count("location ~ ^/api/v1/cloud/worker/") == 1:
                return original.replace(previous, LOCATION, 1)
        raise ValueError("Unexpected existing Worker route")
    return original.replace(ANCHOR, LOCATION + ANCHOR, 1)


def agent_plist(*, python: Path, source: Path, api_url: str, worker_id: str,
                credential: Path, dsh_home: Path, state: Path, ca: Path, path: str,
                home: str, ssh_auth_sock: str | None) -> dict:
    parsed = urlsplit(api_url)
    if (parsed.scheme != "https" or parsed.hostname != "localhost" or parsed.port != 18444
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError("API URL must be https://localhost:18444")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", worker_id):
        raise ValueError("Invalid Worker ID")
    environment = {"HOME": home, "PATH": path, "PYTHONPATH": str(source / "src"),
                   "PYTHONDONTWRITEBYTECODE": "1"}
    if ssh_auth_sock:
        environment["SSH_AUTH_SOCK"] = ssh_auth_sock
    return {"Label": LABEL, "ProgramArguments": [str(python), "-m", "hypertest.cloud.native_worker",
        "--api-url", api_url, "--worker-id", worker_id, "--worker-credential-file", str(credential),
        "--dsh-home", str(dsh_home), "--state-dir", str(state), "--ca-file", str(ca)],
        "EnvironmentVariables": environment, "WorkingDirectory": str(source),
        # Transport failures recover in-process by original key. Runtime faults
        # still stop for inspection; launchd must not replay uncertain work.
        "RunAtLoad": True, "KeepAlive": False, "ProcessType": "Background"}


def existing(path: Path, *, directory: bool = False, private: bool = False) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Paths must be absolute and not symlinks")
    path = path.resolve(strict=True)
    info = path.stat()
    if (directory and not stat.S_ISDIR(info.st_mode)) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError("Path type does not match")
    if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("Worker private paths must be owned by this user and inaccessible to others")
    if private and directory and stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("Worker state directory must have mode 0700")
    if private and not directory and (stat.S_IMODE(info.st_mode) not in {0o400, 0o600} or info.st_nlink != 1):
        raise ValueError("Worker credential must have mode 0400 or 0600 and one link")
    return path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "source", "credential", "dsh-home", "state", "ca", "bff-config", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--worker-id", required=True)
    p.add_argument("--commit", required=True, help="Full Git SHA of the pushed, clean checkout")
    p.add_argument("--api-url", default="https://localhost:18444")
    args = p.parse_args()
    try:
        if sys.platform != "darwin":
            raise ValueError("This staging command requires macOS")
        # venv interpreters commonly are symlinks; preserve the venv path so
        # Python finds its pyvenv.cfg rather than invoking the base interpreter.
        python = args.python
        if not python.is_absolute() or not python.is_file():
            raise ValueError("Python interpreter must be an absolute executable path")
        source = existing(args.source, directory=True)
        credential = existing(args.credential, private=True)
        dsh_home = existing(args.dsh_home, directory=True)
        state = existing(args.state, directory=True, private=True)
        ca = existing(args.ca)
        bff = existing(args.bff_config)
        if not os.access(python, os.X_OK) or not (source / "src/hypertest/cloud/native_worker.py").is_file():
            raise ValueError("Python or native Worker entrypoint unavailable")
        commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
        clean = subprocess.run(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"],
                               check=True, capture_output=True, text=True).stdout
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit) or commit != args.commit or clean:
            raise ValueError("Source must be a clean checkout at the requested full commit")
        remote = subprocess.run(["git", "-C", str(source), "branch", "-r", "--contains", commit],
                                check=True, capture_output=True, text=True).stdout
        if not remote.strip():
            raise ValueError("Commit has no local remote-tracking reference")
        # Import and version inspection does not start a runtime, model, or SUT.
        check_env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(Path.home()),
                     "PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        checked = subprocess.run([str(python), "-B", "-c", "from hypertest.cloud.sdk import inspect_sdk; inspect_sdk()"],
                                 cwd=source, env=check_env, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=20)
        if checked.returncode:
            raise ValueError("The pinned Cloud SDK/runtime cannot be imported on this host")
        spec = agent_plist(python=python, source=source, api_url=args.api_url, worker_id=args.worker_id,
            credential=credential, dsh_home=dsh_home, state=state, ca=ca, path=os.environ.get("PATH", os.defpath),
            home=str(Path.home()), ssh_auth_sock=os.environ.get("SSH_AUTH_SOCK"))
        config = bff_config(bff.read_text())
        if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
            raise ValueError("Output must be a new absolute directory")
        args.output.mkdir(mode=0o700)
        (args.output / "worker.plist").write_bytes(plistlib.dumps(spec))
        (args.output / "nginx.conf").write_text(config)
        print(f"Prepared {args.output}; no services were changed or started.")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Staging failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
