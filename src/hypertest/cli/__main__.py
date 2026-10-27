"""Public hypertest entrypoint. All network work is explicit and short-lived."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hypertest.cli import CLI_VERSION, PREFIX, auth, skills
from hypertest.cli import archive as archive_client
from hypertest.cli.state import CLIError, State, identifier
from hypertest.cli.transport import HTTP
from hypertest.interactive_client.errors import ClientError
from hypertest.sync_core import SyncError


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hypertest", description="Explicit HyperTest One artifact archive")
    root.add_argument("--version", action="version", version=f"hypertest {CLI_VERSION}")
    root.add_argument("--json", action="store_true", help="Print a stable non-secret JSON result")
    commands = root.add_subparsers(dest="command", required=True)

    def common(command):
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    authorization = commands.add_parser("auth")
    actions = authorization.add_subparsers(dest="action", required=True)
    bind = actions.add_parser("bind")
    bind.add_argument("--server")
    bind.add_argument("--profile", default="default")
    bind.add_argument("--project-id")
    bind.add_argument("--request-id")
    bind.add_argument("--resume", action="store_true")
    bind.add_argument("--wait-seconds", type=int, default=600)
    bind.add_argument("--no-browser", action="store_true")
    common(bind)
    for name in ("status", "reconcile"):
        action = actions.add_parser(name)
        action.add_argument("--request-id")
        action.add_argument("--profile")
        common(action)
    logout = actions.add_parser("logout")
    logout.add_argument("--profile", required=True)
    common(logout)
    profile = commands.add_parser("profile")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    show = profile_actions.add_parser("show")
    show.add_argument("--profile")
    common(show)
    add = profile_actions.add_parser("add", help="Add a profile through explicit Web pairing")
    add.add_argument("--server", required=True)
    add.add_argument("--profile", required=True)
    add.add_argument("--project-id")
    add.add_argument("--wait-seconds", type=int, default=600)
    add.add_argument("--no-browser", action="store_true")
    common(add)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--profile")
    doctor.add_argument("--project-id")
    common(doctor)
    upload = commands.add_parser("archive")
    upload.add_argument("--profile")
    upload.add_argument("--project-id", required=True)
    upload.add_argument("--task-id", required=True)
    upload.add_argument("--subtask-id")
    upload.add_argument("--manifest", type=Path, required=True)
    upload.add_argument("--request-id")
    upload.add_argument("--dry-run", action="store_true")
    common(upload)
    for name in ("status", "reconcile"):
        action = commands.add_parser(name)
        action.add_argument("--request-id", required=True)
        if name == "status":
            action.add_argument("--remote", action="store_true")
        common(action)
    skill = commands.add_parser("skill")
    installation = skill.add_subparsers(dest="action", required=True).add_parser("install")
    installation.add_argument("--global", dest="globally", action="store_true")
    installation.add_argument("--host", choices=["codex"])
    installation.add_argument("--directory", type=Path)
    common(installation)
    legacy = commands.add_parser("legacy", help="Retire owned old integration or read its original receipts")
    legacy_actions = legacy.add_subparsers(dest="action", required=True)
    retire = legacy_actions.add_parser("retire", aliases=["cleanup"])
    retire.add_argument("--directory", type=Path, required=True)
    retire.add_argument("--host", choices=["codex", "claude-code", "deepseek-harness", "deepseek"], required=True)
    common(retire)
    recovery = legacy_actions.add_parser("reconcile")
    recovery.add_argument("--config", type=Path, required=True)
    recovery.add_argument("--request-id", required=True, help="Original key, or namespace/key if ambiguous")
    common(recovery)
    return root


def notify_pairing(value: dict) -> None:
    print("Open " + str(value["verification_url"]), file=sys.stderr)
    print("Match code: " + str(value["short_code"]) + " | Request: " + value["request_id"], file=sys.stderr)


def dispatch(args, state: State) -> tuple[dict, int]:
    if args.command == "archive":
        return archive_client.archive(state, profile_name=args.profile, project_id=args.project_id,
                                      task_id=args.task_id, subtask_id=args.subtask_id, manifest=args.manifest,
                                      request_id=args.request_id, dry_run=args.dry_run)
    if args.command in {"status", "reconcile"}:
        return archive_client.status(state, args.request_id,
                                     remote=args.command == "reconcile" or args.remote)
    if args.command == "auth":
        if args.action == "bind":
            return auth.bind(state, server=args.server, name=args.profile, project_id=args.project_id,
                             request_id=args.request_id, resume=args.resume, wait_seconds=args.wait_seconds,
                             open_browser=not args.no_browser, notify=notify_pairing)
        if args.action == "logout":
            return auth.logout(state, args.profile)
        if args.action == "reconcile":
            if not args.request_id:
                raise CLIError("PAIRING_REQUEST_ID_REQUIRED")
            return auth.reconcile(state, args.request_id)
        if args.request_id:
            record = state.read(state.pairings, identifier(args.request_id))
            return auth.safe_view(record), 0
        return {"status": "CONFIGURED", "profiles": state.safe_profiles(args.profile)}, 0
    if args.command == "profile":
        if args.action == "show":
            return {"profiles": state.safe_profiles(args.profile)}, 0
        return auth.bind(state, server=args.server, name=args.profile, project_id=args.project_id,
                         wait_seconds=args.wait_seconds, open_browser=not args.no_browser, notify=notify_pairing)
    if args.command == "doctor":
        profile = state.profile(args.profile, project_id=identifier(args.project_id) if args.project_id else None)
        project = args.project_id or profile["grant"]["project_ids"][0]
        result = HTTP(profile["server"], token=profile["grant"]["credential"]).call(
            "GET", PREFIX + "/capabilities", query={"project_id": project})
        return {"status": "READY", "version": CLI_VERSION, "profile": profile["name"],
                "server": profile["server"], "capabilities": result}, 0
    if args.command == "legacy":
        from hypertest.cli import legacy
        if args.action in {"retire", "cleanup"}:
            return legacy.retire(str(args.directory), args.host)
        return legacy.reconcile(str(args.config), args.request_id)
    if args.command == "skill":
        return skills.install(state, directory=args.directory, globally=args.globally, host=args.host)
    raise CLIError("UNKNOWN_COMMAND")


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        result, code = dispatch(args, State())
    except CLIError as exc:
        code = exc.exit_code
        result = {"status": "ERROR", "code": exc.code, "readback_complete": False}
    except (ClientError, SyncError) as exc:
        code, result = 5, {"status": "ERROR", "code": exc.code, "readback_complete": False}
    except (OSError, ValueError, KeyError, TypeError):
        # Never format exception strings: filenames, server bodies and credentials can be present.
        code, result = 5, {"status": "ERROR", "code": "LOCAL_CONFIGURATION_INVALID", "readback_complete": False}
    except KeyboardInterrupt:
        code, result = 4, {"status": "UNKNOWN", "code": "INTERRUPTED_CHECK_ORIGINAL_REQUEST", "readback_complete": False}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
