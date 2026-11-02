#!/usr/bin/env python3
"""Install a staged native Worker LaunchAgent; never alters an existing agent."""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

LABEL = "com.hypertest.cloud-native-worker"
FLAGS = ("--api-url", "--worker-id", "--worker-credential-file", "--dsh-home", "--state-dir", "--ca-file")


def validate(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"Label", "ProgramArguments", "EnvironmentVariables", "WorkingDirectory", "RunAtLoad", "KeepAlive", "ProcessType"}:
        raise ValueError("Unexpected LaunchAgent fields")
    argv, env = value["ProgramArguments"], value["EnvironmentVariables"]
    if (value["Label"] != LABEL or value["RunAtLoad"] is not True or value["KeepAlive"] is not False
            or value["ProcessType"] != "Background" or not isinstance(argv, list) or len(argv) != 15
            or argv[1:3] != ["-m", "hypertest.cloud.native_worker"]
            or tuple(argv[3::2]) != FLAGS or any(not isinstance(x, str) or not x for x in argv)
            or argv[4] != "https://localhost:18444"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", argv[6])):
        raise ValueError("Unexpected Worker command")
    if (any(not Path(argv[i]).is_absolute() for i in (0, 8, 10, 12, 14))
            or not isinstance(env, dict) or not {"HOME", "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"} <= set(env)
            or set(env) - {"HOME", "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "SSH_AUTH_SOCK"}
            or env["PYTHONDONTWRITEBYTECODE"] != "1"
            or not all(isinstance(v, str) and v for v in env.values())
            or not isinstance(value["WorkingDirectory"], str)
            or not Path(value["WorkingDirectory"]).is_absolute()
            or env["PYTHONPATH"] != str(Path(value["WorkingDirectory"]) / "src")):
        raise ValueError("Unexpected Worker environment")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-plist", required=True, type=Path)
    parser.add_argument("--start", action="store_true", help="Bootstrap the agent after API and BFF deployment")
    args = parser.parse_args()
    try:
        if sys.platform != "darwin":
            raise ValueError("This installer requires macOS")
        if not args.staged_plist.is_absolute() or args.staged_plist.is_symlink():
            raise ValueError("Staged plist must be an absolute, regular file")
        with args.staged_plist.open("rb") as stream:
            value = plistlib.load(stream)
        validate(value)
        launch_agents = Path.home() / "Library/LaunchAgents"
        if not launch_agents.is_dir() or launch_agents.is_symlink():
            raise ValueError("LaunchAgents directory is unavailable")
        target = launch_agents / (LABEL + ".plist")
        domain = "gui/" + str(os.getuid())
        if target.exists() or target.is_symlink():
            raise ValueError("LaunchAgent already exists; no existing service was changed")
        if subprocess.run(["/bin/launchctl", "print", domain + "/" + LABEL],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ValueError("LaunchAgent is already loaded; no existing service was changed")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            plistlib.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if args.start:
            result = subprocess.run(["/bin/launchctl", "bootstrap", domain, str(target)], check=False)
            if result.returncode:
                raise ValueError("LaunchAgent installed but bootstrap failed; inspect before retrying")
        print("LaunchAgent installed" + (" and bootstrapped." if args.start else "; not started."))
        return 0
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        print(f"Installation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
