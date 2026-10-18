"""Production boundary checks: unsafe identity/configuration must fail before launch."""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hypertest_container_stack", ROOT / "ops/container/stack.py")
stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stack)


def configuration(tmp_path: Path) -> dict[str, str]:
    values = stack.read_env(ROOT / "ops/container/compose.env.example")
    for index, key in enumerate(stack.IMAGE_KEYS):
        values[key] = "sha256:" + f"{index + 1:064x}"
    values["HYPERTEST_DOCKER_GID"] = "998"
    values["HYPERTEST_BRIDGE_GID"] = "997"
    return values


def test_fixed_images_and_authorized_peer_are_required(tmp_path):
    values = configuration(tmp_path)
    stack.validate(values, live=False)
    for unsafe in ("latest", "hypertest:release", "sha256:short", "repo@sha256:" + "g" * 64):
        with pytest.raises(ValueError, match="tags are refused"):
            stack.validate({**values, "HYPERTEST_API_IMAGE": unsafe}, live=False)
    for unsafe in ("0.0.0.0/0", "45.76.149.0/24", "127.0.0.1/32"):
        with pytest.raises(ValueError, match="authorized VPN"):
            stack.validate({**values, "HYPERTEST_VPN_CIDR": unsafe}, live=False)


def test_rejects_ambiguous_or_dangerous_paths_and_identity(tmp_path):
    values = configuration(tmp_path)
    for key, unsafe in (
        ("HYPERTEST_ARTIFACT_ROOT", "/"),
        ("HYPERTEST_ARTIFACT_ROOT", values["HYPERTEST_WORKSPACE_ROOT"] + "/artifacts"),
        ("HYPERTEST_WORKSPACE_ROOT", "/safe/../elsewhere"),
        ("HYPERTEST_UID", "0"),
        ("HYPERTEST_PUBLIC_IP", "0.0.0.0"),
        ("HYPERTEST_PUBLIC_IP", "::"),
        ("HYPERTEST_API_PORT", values["HYPERTEST_WEB_PORT"]),
    ):
        with pytest.raises(ValueError):
            stack.validate({**values, key: unsafe}, live=False)


def test_env_is_data_never_shell_or_compose_expansion(tmp_path):
    path = tmp_path / "compose.env"
    for unsafe in ("KEY=$(touch /tmp/should-never-run)", "KEY=`whoami`", "KEY=x\nKEY=y", 'KEY="secret"'):
        path.write_text(unsafe)
        with pytest.raises(ValueError):
            stack.read_env(path)


def test_nginx_uses_specific_host_listeners_and_overwrites_forwarded_identity(tmp_path):
    values = configuration(tmp_path)
    config = stack.render_nginx(values)
    assert "listen 127.0.0.1:8080;" in config
    assert "listen 155.138.206.106:8080 default_server;" in config
    assert "allow 45.76.149.233/32;" in config
    assert "real_ip_header" not in config and "set_real_ip_from" not in config
    assert "$proxy_add_x_forwarded_for" not in config
    assert config.count("proxy_set_header X-Forwarded-For $remote_addr;") == 4
    assert "deny all;" in config
    assert "map $http_origin" in config


def test_compose_isolates_privileged_mounts_and_preserves_external_volume(tmp_path):
    # Compose's own parser validates the fully merged service definitions.
    if not __import__("shutil").which("docker"):
        pytest.skip("Docker CLI required for production Compose parser check")
    values = configuration(tmp_path)
    platform = tmp_path / "platform.env"
    platform.write_text("HYPERTEST_EXECUTION_MODE=queued\nHYPERTEST_HARNESS_MODE=bridge\n")
    postgres = tmp_path / "postgres.env"
    postgres.write_text("POSTGRES_DB=hypertest\n")
    values["HYPERTEST_PLATFORM_ENV_FILE"] = str(platform)
    values["HYPERTEST_POSTGRES_ENV_FILE"] = str(postgres)
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    result = subprocess.run(stack.compose_command(env, "config", "--format", "json"), capture_output=True, text=True, check=True)
    parsed = __import__("json").loads(result.stdout)
    services = parsed["services"]
    for service in ("api", "worker", "web", "nginx"):
        # YAML flow sequences split unquoted comma-separated mount options.
        assert len(services[service]["tmpfs"]) == 1
        assert services[service]["tmpfs"][0].startswith("/tmp:rw,nosuid,nodev,size=")
    assert services["nginx"]["network_mode"] == "host"
    assert "ports" not in services["nginx"]
    for service in ("api", "web", "postgres"):
        assert all(port["host_ip"] == "127.0.0.1" for port in services[service]["ports"])
    for service in ("api", "web"):
        mounts = repr(services[service].get("volumes", []))
        assert "docker.sock" not in mounts and "bridge-execution" not in mounts
        assert ".codex" not in mounts and "harness.sock" not in mounts
    assert "docker.sock" in repr(services["worker"]["volumes"])
    assert parsed["volumes"]["postgres_data"]["external"] is True
    assert "build" not in repr(services)
    assert all(service["pull_policy"] == "never" for service in services.values())
    assert all(service["restart"] == "no" for service in services.values())


def test_runner_staged_contract_files_stay_world_readable_under_restrictive_umask(tmp_path):
    # Exercise the real script staging, without downloading wheels or building an image.
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker = binary_dir / "docker"
    capture = tmp_path / "modes.txt"
    docker.write_text("""#!/usr/bin/env python3
import os, pathlib, stat, sys
args = sys.argv[1:]
if args[:2] == ['image', 'inspect']:
    print('arm64' if 'Architecture' in args[-1] else 'python@sha256:' + '1' * 64)
elif args[0] == 'build':
    root = pathlib.Path(args[-1])
    with open(os.environ['CAPTURE_MODES'], 'w') as out:
        for name in ('Dockerfile', 'requirements.txt', 'service_launcher.py'):
            out.write(name + ':' + oct(stat.S_IMODE((root / name).stat().st_mode)) + '\\n')
""")
    python = binary_dir / "python"
    python.write_text(f"""#!{sys.executable}
import os, sys
if sys.argv[1:4] == ['-m', 'pip', 'download']:
    os.makedirs(sys.argv[sys.argv.index('--dest') + 1], exist_ok=True)
else:
    os.execv({sys.executable!r}, [{sys.executable!r}] + sys.argv[1:])
""")
    for executable in (docker, python):
        executable.chmod(stat.S_IRWXU)
    environment = {**os.environ, "PATH": str(binary_dir) + os.pathsep + os.environ["PATH"], "CAPTURE_MODES": str(capture)}
    subprocess.run(["bash", "-c", 'umask 027; exec bash "$1" python-api-v2', "_", str(ROOT / "scripts/build-runner-image.sh")],
                   env=environment, check=True, capture_output=True)
    assert capture.read_text().splitlines() == [
        "Dockerfile:0o644", "requirements.txt:0o644", "service_launcher.py:0o644",
    ]


def backup_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("hypertest_container_backup", ROOT / "ops/container/backup.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "stack", stack)
    spec.loader.exec_module(module)
    return module


def test_restore_refuses_existing_destination_and_production_database(tmp_path, monkeypatch):
    backup = backup_module(monkeypatch)
    destination = tmp_path / "new"
    with pytest.raises(ValueError, match="isolated database"):
        backup.restore_verify(tmp_path / "env", tmp_path / "missing", destination, "hypertest")
    destination.mkdir()
    with pytest.raises(ValueError, match="new absolute directory"):
        backup.restore_verify(tmp_path / "env", tmp_path / "missing", destination, "hypertest_verify_test")


def test_backup_rejects_live_writers_before_copying(tmp_path, monkeypatch):
    backup = backup_module(monkeypatch)
    monkeypatch.setattr(backup, "compose", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="api\npostgres\n"))
    with pytest.raises(ValueError, match="stop API/Worker"):
        backup.quiescent(tmp_path / "env")


def test_backup_checks_the_selected_bridge_service(tmp_path, monkeypatch):
    backup = backup_module(monkeypatch)
    monkeypatch.setattr(backup, "compose", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="postgres\n"))
    calls = []

    def active(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="active\n")

    monkeypatch.setattr(backup.subprocess, "run", active)
    with pytest.raises(ValueError, match="stop and verify"):
        backup.quiescent(tmp_path / "env", "hypertest-adr013-staging-bridge")
    assert calls == [["systemctl", "is-active", "hypertest-adr013-staging-bridge"]]


def test_restore_rejects_incomplete_or_tampered_pair_before_any_db_write(tmp_path, monkeypatch):
    import hashlib
    import json

    backup = backup_module(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps({"format": "hypertest.paired-backup/v1", "files": {"database.dump": "0" * 64}}))
    (source / "COMPLETE").write_text(hashlib.sha256(manifest.read_bytes()).hexdigest())
    touched = []
    monkeypatch.setattr(backup, "postgres", lambda *args, **kwargs: touched.append(args))
    with pytest.raises(ValueError, match="missing a required component"):
        backup.restore_verify(tmp_path / "env", source, tmp_path / "new", "hypertest_verify_test")
    assert not touched
    manifest.write_text("{}")
    with pytest.raises(ValueError, match="incomplete or modified"):
        backup.restore_verify(tmp_path / "env", source, tmp_path / "new", "hypertest_verify_test")
    assert not touched


def test_staging_ingress_does_not_open_any_public_listener(tmp_path):
    values = {**configuration(tmp_path), "HYPERTEST_PUBLIC_INGRESS": "disabled", "HYPERTEST_INGRESS_PORT": "18080"}
    stack.validate(values, live=False)
    config = stack.render_nginx(values)
    assert "listen 127.0.0.1:18080;" in config
    assert "listen 155.138.206.106" not in config
    assert config.count("listen ") == 1


def test_optional_gitlab_policy_mount_is_worker_only_and_read_only(tmp_path):
    if not __import__("shutil").which("docker"):
        pytest.skip("Docker CLI required for production Compose parser check")
    values = configuration(tmp_path)
    for key in ("HYPERTEST_PLATFORM_ENV_FILE", "HYPERTEST_POSTGRES_ENV_FILE"):
        path = tmp_path / key
        path.write_text("")
        values[key] = str(path)
    values["HYPERTEST_GITLAB_POLICY_DIR"] = str(tmp_path / "gitlab")
    env = tmp_path / "compose.env"
    env.write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    command = stack.compose_command(env, "config", "--format", "json")
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    services = __import__("json").loads(result.stdout)["services"]
    for name, service in services.items():
        mounts = [mount for mount in service.get("volumes", []) if mount["target"] == "/run/hypertest-gitlab"]
        if name == "worker":
            assert len(mounts) == 1 and mounts[0]["read_only"] is True
            assert mounts[0]["bind"]["create_host_path"] is False
        else:
            assert mounts == []
    unit = (ROOT / "ops/container/hypertest-harness-bridge.service").read_text()
    assert "-/etc/hypertest/container/gitlab" in unit
    assert "RuntimeDirectoryPreserve=yes" in unit


def test_old_docker_network_guard_fails_closed_and_removes_only_its_rule(tmp_path, monkeypatch):
    import json

    spec = importlib.util.spec_from_file_location("hypertest_network_guard", ROOT / "ops/container/network_guard.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "stack", stack)
    spec.loader.exec_module(module)
    values = configuration(tmp_path)
    network = {"Id": "abcdef012345" + "1" * 52, "Driver": "bridge", "EnableIPv6": False,
               "Options": {}, "Labels": {"com.docker.compose.project": values["HYPERTEST_STACK_NAME"]}}
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    calls, installed, first = [], False, False

    def inspect(command, **kwargs):
        if command[0] == "iptables":
            import shlex
            own = "-A DOCKER-USER " + shlex.join(module.inspect_guard(values)[1]) + "\n" if installed else ""
            return own + "-A DOCKER-USER -j RETURN\n" if first else "-A DOCKER-USER -j RETURN\n" + own
        return "26.1.5+dfsg1" if command[1] == "info" else json.dumps([network])

    monkeypatch.setattr(module.subprocess, "check_output", inspect)

    def firewall(command, **kwargs):
        nonlocal installed, first
        calls.append(command)
        if "-C" in command:
            return subprocess.CompletedProcess(command, 0 if installed else 1)
        if "-I" in command:
            installed = True
            first = True
        if "-D" in command:
            installed = False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", firewall)
    with pytest.raises(ValueError, match="requires the scoped ingress guard"):
        module.guard(values)
    assert module.guard(values, "install")["protected"] is True
    first = False  # An earlier RETURN makes a present DROP unreachable.
    with pytest.raises(ValueError, match="first rule"):
        module.guard(values)
    assert module.guard(values, "install")["first_rule"] is True
    assert module.guard(values, "remove")["protected"] is False
    writes = [command for command in calls if "-I" in command or "-D" in command]
    assert len(writes) == 4
    for command in writes:
        assert "-F" not in command and "--flush" not in command
        assert "br-abcdef012345" in command and "hypertest:hypertest-production:loopback-only" in command
    network["Labels"]["com.docker.compose.project"] = "another-production"
    with pytest.raises(ValueError, match="not this Compose"):
        module.guard(values, "install")


def test_guarded_start_refuses_live_restore_and_never_starts_without_guard(tmp_path, monkeypatch):
    import json

    monkeypatch.setitem(sys.modules, "stack", stack)
    guard_spec = importlib.util.spec_from_file_location("network_guard", ROOT / "ops/container/network_guard.py")
    network = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(network)
    monkeypatch.setitem(sys.modules, "network_guard", network)
    spec = importlib.util.spec_from_file_location("hypertest_start", ROOT / "ops/container/start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "output", lambda command: json.dumps({"LiveRestoreEnabled": True}))
    with pytest.raises(ValueError, match="live-restore"):
        module.verify_daemon()
    values = configuration(tmp_path)
    monkeypatch.setattr(module, "read_env", lambda path: values)
    monkeypatch.setattr(module, "validate", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "verify_daemon", lambda: "stable-daemon")
    monkeypatch.setattr(module, "verify_restart_policy", lambda *args: None)
    commands = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kwargs: commands.append(command))

    def broken_guard(*args):
        raise ValueError("firewall unavailable")

    monkeypatch.setattr(module, "guard", broken_guard)
    with pytest.raises(ValueError, match="firewall unavailable"):
        module.start(tmp_path / "env", ("postgres",))
    assert not any("start" in command for command in commands)
    assert "stop" in commands[0] and "stop" in commands[-1]
    commands.clear()

    def unsafe_policy(*args):
        raise ValueError("existing stack container has unsafe restart policy")

    monkeypatch.setattr(module, "verify_restart_policy", unsafe_policy)
    with pytest.raises(ValueError, match="unsafe restart policy"):
        module.start(tmp_path / "env", ("postgres",))
    assert "stop" in commands[0]
    assert not any("create" in command or "start" in command for command in commands)
    unit = (ROOT / "ops/container/hypertest-container-stack.service").read_text()
    assert "After=docker.service hypertest-harness-bridge.service" in unit
    assert "BindsTo=docker.service" in unit
    assert "Restart=no" in unit
    monkeypatch.setattr(module, "guard", lambda *args: {"protected": False})
    with pytest.raises(ValueError, match="changed while waiting"):
        module.wait_healthy(tmp_path / "env", values, ("postgres",), "stable-daemon")
