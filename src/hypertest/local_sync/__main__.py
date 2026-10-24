"""HyperTest Local configuration and best-effort hook entry points."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalClient
from hypertest.local_sync.hosts import HOST_PROVIDERS
from hypertest.local_sync.installer import (
    doctor,
    install,
    recover_install,
    rollback,
    uninstall,
    upgrade_owned,
)


async def hook(config_path: Path):
    from hypertest.local_sync.hooks import persist_trigger, sanitize_event, selected_trigger
    config = ClientConfig.load(config_path, validate_credentials=False)
    raw = sys.stdin.buffer.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ClientError("LOCAL_EVENT_TOO_LARGE")
    event = sanitize_event(json.loads(raw))
    trigger = selected_trigger(config, event)
    if trigger is None:
        return {"status": "IGNORED"}
    if config.local_sync.get("artifact_source") and trigger.event == "SessionStart":
        from hypertest.local_sync.sources import session_context
        return {"status": "BOUND", "_hook_context": session_context(config, event)}
    pending = persist_trigger(config, trigger)
    # This is the same daemon and OS ownership lock as MCP autostart; no model
    # or independent uploader is launched when MCP is absent or still loading.
    from hypertest.interactive_client.__main__ import ensure_daemon
    await ensure_daemon(config, config_path)
    client = LocalClient(config.socket_path, config.local_token_file)
    return await client.exchange("local-hook", {"event": event, "event_id": pending.stem})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "upgrade"):
        child = commands.add_parser(name)
        child.add_argument("--directory", required=True, type=Path)
        child.add_argument("--harness", required=True, choices=tuple(HOST_PROVIDERS))
        child.add_argument("--host-config", required=True, type=Path)
        child.add_argument("--client-config", required=True, type=Path)
        child.add_argument("--version", required=True)
        child.add_argument("--python", type=Path)
        child.add_argument("--hook-config", type=Path)
        child.add_argument("--enable-hooks", action="store_true")
        child.add_argument("--harness-version")
        child.add_argument("--harness-binary", type=Path,
            help="Explicit native CLI for the bounded --version capability probe")
        child.add_argument("--dsh-home", type=Path)
        child.add_argument("--profile")
        child.add_argument("--event-bridge", choices=("claude-code", "codex", "native-root"))
        sources = child.add_mutually_exclusive_group()
        sources.add_argument("--workspace", type=Path,
            help="Select a workspace and the standard per-session analysis.md policy (DRAFT / NOT_RUN)")
        sources.add_argument("--artifact-source", type=Path,
            help="Private JSON file declaring an approved artifact source strategy")
    for name in ("doctor", "uninstall", "rollback"):
        child = commands.add_parser(name)
        child.add_argument("--directory", required=True, type=Path)
        child.add_argument("--harness", required=True, choices=tuple(HOST_PROVIDERS))
    child = commands.add_parser("hook")
    child.add_argument("--config", required=True, type=Path)
    child = commands.add_parser("submit-manifest", help="Submit the explicitly selected approved manifest")
    child.add_argument("--config", required=True, type=Path)
    child.add_argument("--manifest", type=Path, help="Must match the manifest selected in the private config")
    child = commands.add_parser("recover-install", help="Safely roll back interrupted owned config transactions")
    child.add_argument("--directory", required=True, type=Path)
    child = commands.add_parser("drain-source", help="Recover one existing native source without creating a Hook event")
    child.add_argument("--config", required=True, type=Path)
    child.add_argument("--session-id", required=True)
    child = commands.add_parser("upgrade-owned", help="Upgrade runtime using the existing owned receipt, preserving hooks and artifact policy")
    child.add_argument("--directory", required=True, type=Path)
    child.add_argument("--harness", required=True, choices=tuple(HOST_PROVIDERS))
    child.add_argument("--version", required=True)
    child.add_argument("--python", required=True, type=Path)
    for name in ("bind-task", "get-task-binding", "capabilities"):
        child = commands.add_parser(name)
        child.add_argument("--config", required=True, type=Path)
        if name != "capabilities":
            child.add_argument("--project-id", required=True)
            child.add_argument("--idempotency-key", required=True)
        if name == "bind-task":
            child.add_argument("--task-id", required=True)
            child.add_argument("--provider", required=True)
            child.add_argument("--session-id", required=True)
            child.add_argument("--expected-version", required=True, type=int)
    args = parser.parse_args()
    try:
        if args.command in {"bind-task", "get-task-binding", "capabilities"}:
            from hypertest.interactive_client.__main__ import ensure_daemon
            config = ClientConfig.load(args.config, validate_credentials=False)
            async def call_binding():
                await ensure_daemon(config, args.config)
                client = LocalClient(config.socket_path, config.local_token_file)
                if args.command == "capabilities":
                    return await client.exchange("list", {})
                arguments = {"project_id": args.project_id, "idempotency_key": args.idempotency_key}
                if args.command == "bind-task":
                    arguments.update(task_id=args.task_id, provider=args.provider, session_id=args.session_id,
                                     expected_version=args.expected_version)
                return await client.exchange("call", {
                    "name": "hypertest_bind_task" if args.command == "bind-task" else "hypertest_get_task_binding",
                    "arguments": arguments})
            result = asyncio.run(call_binding())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("status") in {"UNKNOWN", "BLOCKED", "REJECTED"}:
                raise SystemExit(1)
            return
        if args.command == "hook":
            result = asyncio.run(hook(args.config))
            if result.get("_hook_context"):
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                    "additionalContext": result["_hook_context"]}}))
            # Never inject a platform report/receipt into a model-visible hook
            # answer. Only bounded diagnostics go to stderr on incomplete sync.
            if result.get("status") in {"UNKNOWN", "BLOCKED"}:
                print("HYPERTEST_LOCAL_SYNC_PENDING", file=sys.stderr)
            return
        if args.command == "submit-manifest":
            config = ClientConfig.load(args.config, validate_credentials=False)
            if args.manifest is not None and str(args.manifest.expanduser().absolute()) != config.local_sync.get("manifest_file"):
                raise ClientError("MANIFEST_NOT_SELECTED_IN_PRIVATE_CONFIGURATION")
            client = LocalClient(config.socket_path, config.local_token_file)
            result = asyncio.run(client.exchange("local-manifest", {}))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("status") in {"UNKNOWN", "BLOCKED", "REJECTED"} or (
                    result.get("status") == "ACCEPTED" and not result.get("_sync", {}).get("readback_complete")):
                raise SystemExit(1)
            return
        if args.command == "drain-source":
            from hypertest.interactive_client.__main__ import ensure_daemon
            config = ClientConfig.load(args.config, validate_credentials=False)
            async def recover():
                await ensure_daemon(config, args.config)
                return await LocalClient(config.socket_path, config.local_token_file).exchange(
                    "local-source", {"session_id": args.session_id})
            result = asyncio.run(recover())
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("status") in {"UNKNOWN", "BLOCKED", "REJECTED"}:
                raise SystemExit(1)
            return
        if args.command == "upgrade-owned":
            result = upgrade_owned(directory=args.directory, host=args.harness,
                                   version=args.version, python=args.python)
        elif args.command == "recover-install":
            result = recover_install(directory=args.directory)
        elif args.command in {"install", "upgrade"}:
            result = install(directory=args.directory, host=args.harness,
                host_config=args.host_config, client_config=args.client_config,
                version=args.version, python=args.python, hook_config=args.hook_config,
                enable_hooks=args.enable_hooks, harness_version=args.harness_version,
                dsh_home=args.dsh_home, profile=args.profile, event_bridge=args.event_bridge,
                workspace=args.workspace, artifact_source=args.artifact_source,
                harness_binary=args.harness_binary)
        else:
            operation = {"doctor": doctor, "uninstall": uninstall, "rollback": rollback}[args.command]
            result = operation(directory=args.directory, host=args.harness)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ClientError, OSError, ValueError, KeyError, TypeError) as exc:
        print(exc.code if isinstance(exc, ClientError) else "LOCAL_OPERATION_BLOCKED", file=sys.stderr)
        # Advisory hooks cannot block host tools or ask the Agent to continue.
        if args.command != "hook":
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
