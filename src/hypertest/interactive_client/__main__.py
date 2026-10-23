"""Local daemon / stdio entry points. No Provider process is launched here."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import stat
import subprocess
import sys
from pathlib import Path

from hypertest.interactive_client.config import ClientConfig
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.ipc import LocalClient, LocalServer
from hypertest.interactive_client.security import peer_pid, peer_uid


async def daemon(config: ClientConfig):
    from hypertest.interactive_client.api_client import ApiClient
    from hypertest.interactive_client.host_adapter import make_host_adapter
    from hypertest.interactive_client.journal import Journal
    from hypertest.interactive_client.service import InteractiveService

    api = ApiClient(config)
    journal = Journal(config.state_dir / "client.sqlite3")
    host = make_host_adapter(config.model_dump(mode="json"))
    service = InteractiveService(config, api, journal, host)
    server = LocalServer(config, service)
    await server.start()
    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)
    try:
        await stopping.wait()
    finally:
        await server.close()
        service.close_memory()
        await api.close()
        journal.close()


async def ensure_daemon(config: ClientConfig, config_path: Path):
    """Start only the existing fenced transport, shared by MCP and hooks."""
    available = False
    if config.socket_path.exists() and not config.socket_path.is_symlink():
        with socket.socket(socket.AF_UNIX) as probe:
            available = probe.connect_ex(str(config.socket_path)) == 0
    if not available:
        # A transport daemon, never a model/Provider. Preserve the host launch
        # environment so the trusted adapter can attest the current native Agent.
        log_path = config.state_dir / "daemon.log"
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(fd)
            raise ClientError("PRIVATE_FILE_REQUIRED")
        with os.fdopen(fd, "ab") as log:
            child_environment = None
            isolated_client = bool(config.local_sync.get("enabled"))
            if isolated_client:
                # Local management needs only its private platform profile.
                # Do not retain the parent model CLI's API keys in a daemon.
                names = {"PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR",
                         "VIRTUAL_ENV", "SSL_CERT_FILE", "SSL_CERT_DIR"}
                child_environment = {key: value for key, value in os.environ.items() if key in names}
            subprocess.Popen([sys.executable, *(["-I"] if isolated_client else []),
                              "-m", "hypertest.interactive_client", "daemon",
                              "--config", str(config_path)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=log, start_new_session=True,
                             close_fds=True, env=child_environment)
        for _ in range(100):
            if config.socket_path.exists() and not config.socket_path.is_symlink():
                with socket.socket(socket.AF_UNIX) as probe:
                    if probe.connect_ex(str(config.socket_path)) == 0:
                        break
            await asyncio.sleep(0.05)
        else:
            raise ClientError("LOCAL_CONNECTOR_UNAVAILABLE")
    return


async def stdio(config: ClientConfig, config_path: Path, *, autostart: bool):
    if autostart:
        await ensure_daemon(config, config_path)
    from hypertest.interactive_client.mcp_server import run_stdio
    await run_stdio(LocalClient(config.socket_path, config.local_token_file),
                    local_host=config.local_sync.get("host") if config.local_sync.get("enabled") else None)


async def stop(config: ClientConfig):
    reader, writer = await asyncio.open_unix_connection(config.socket_path)
    del reader
    try:
        stream = writer.get_extra_info("socket")
        if peer_uid(stream) != os.getuid():
            raise ClientError("LOCAL_PEER_REJECTED")
        os.kill(peer_pid(stream), signal.SIGTERM)
    finally:
        writer.close()
        await writer.wait_closed()


def main():
    parser = argparse.ArgumentParser(description="HyperTest current-Agent MCP access")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("daemon", "stdio", "stop", "print-client-config", "doctor"):
        child = commands.add_parser(command)
        child.add_argument("--config", required=True, type=Path)
        if command == "stdio":
            child.add_argument("--autostart", action="store_true")
        if command == "print-client-config":
            child.add_argument("--format", choices=["json", "codex"], default="json")
    installer = commands.add_parser("setup", help="Explicit operator-authorized MCP installation")
    installer.add_argument("--api-url", required=True)
    installer.add_argument("--project-id", required=True)
    installer.add_argument("--directory", required=True, type=Path)
    installer.add_argument("--operator-key-file", type=Path)
    installer.add_argument("--ca-file", type=Path)
    installer.add_argument("--name", default="My computer")
    installer.add_argument("--host", choices=["generic", "codex-desktop"], default="generic")
    args = parser.parse_args()
    try:
        if args.command in {"setup", "doctor"}:
            from hypertest.interactive_client.setup import doctor, setup

            result = (setup(api_url=args.api_url, project_id=args.project_id,
                            directory=args.directory, operator_key_file=args.operator_key_file,
                            ca_file=args.ca_file, name=args.name, host=args.host)
                      if args.command == "setup" else doctor(args.config))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.config.is_symlink():
            raise ClientError("PRIVATE_FILE_REQUIRED")
        config_path = args.config.expanduser().resolve(strict=True)
        if args.command == "print-client-config":
            # Only installation paths enter the client config, never credentials.
            arguments = ["-m", "hypertest.interactive_client", "stdio", "--config",
                         str(config_path), "--autostart"]
            if args.format == "codex":
                print("[mcp_servers.hypertest]\ncommand = " + json.dumps(sys.executable, ensure_ascii=False)
                      + "\nargs = " + json.dumps(arguments, ensure_ascii=False)
                      + "\nstartup_timeout_sec = 20\ntool_timeout_sec = 120")
            else:
                print(json.dumps({"mcpServers": {"hypertest": {"command": sys.executable,
                      "args": arguments}}}, indent=2))
            return
        config = ClientConfig.load(config_path, validate_credentials=args.command == "daemon")
        if args.command == "stop":
            asyncio.run(stop(config))
        else:
            asyncio.run(daemon(config) if args.command == "daemon" else stdio(
                config, config_path, autostart=args.autostart))
    except (ClientError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, ClientError) else "INTERACTIVE_CLIENT_UNAVAILABLE"
        print(code, file=sys.stderr)
        if code.startswith("SETUP_UNKNOWN_"):
            print("The original POST may have succeeded. Keep this directory and setup.json. "
                  "Ask the platform administrator to reconcile its original node_key and client_instance_id. "
                  "Do not create a replacement identity or retry one-time credential issuance automatically.",
                  file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
