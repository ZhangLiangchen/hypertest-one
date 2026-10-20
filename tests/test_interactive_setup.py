"""Installer authorization, durable one-time issuance, and credential boundaries."""
import json
import stat
import tempfile
import tomllib
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from hypertest.interactive_client import PROFILE
from hypertest.interactive_client.errors import ClientError
from hypertest.interactive_client.setup import READ_SCOPES, doctor, setup


class Platform:
    def __init__(self, directory, project_id):
        self.directory = directory
        self.project_id = project_id
        self.calls = []
        self.nodes = []
        self.capabilities = []
        self.registrations = []
        self.fail = None
        self.profile = PROFILE
        self.redirect = False

    def __call__(self, request):
        path = request.url.path.removeprefix("/api/v1/")
        self.calls.append((request.method, path, request))
        if self.redirect:
            return httpx.Response(302, headers={"Location": "https://attacker.invalid/"})
        if request.method == "POST":
            state = json.loads((self.directory / "setup.json").read_text())
            step = {"harness-nodes/pair": "pair", "interactive/registrations": "registration"}.get(path, "harness")
            assert state["steps"][step]["status"] == "UNKNOWN"
            assert "operator-private-secret" not in json.dumps(state)
            if self.fail == step:
                raise httpx.ReadTimeout("private response must not escape", request=request)
        body = json.loads(request.content) if request.content else {}
        if path == "interactive/capabilities":
            return httpx.Response(200, json={"profile": self.profile})
        if path == "projects/" + self.project_id:
            return httpx.Response(200, json={"id": self.project_id})
        if path == "interactive/submissions/by-key":
            assert request.headers["Authorization"] == "Bearer integration-private-secret-0123456789"
            assert "X-Hypertest-Operator-Key" not in request.headers
            return httpx.Response(200, json={"status": "NOT_FOUND"})
        assert request.headers["X-Hypertest-Operator-Key"] == "operator-private-secret"
        if path == "harness-nodes":
            return httpx.Response(200, json=self.nodes)
        if path == "harness-nodes/pair":
            node = {"id": str(uuid4()), "node_key": body["node_key"], "registration_status": "ACTIVE"}
            self.nodes.append(node)
            return httpx.Response(201, json={"node": node, "grant_id": str(uuid4()),
                "device_token": "device-private-secret-0123456789", "expires_at": "2099-01-01T00:00:00Z"})
        if path.endswith("/capabilities"):
            if request.method == "GET":
                return httpx.Response(200, json=self.capabilities)
            scope = {**body, "id": str(uuid4()), "status": "ACTIVE"}
            self.capabilities.append(scope)
            return httpx.Response(201, json={"id": scope["id"], "status": "ACTIVE"})
        if path == "interactive/registrations":
            self.registrations.append(body)
            return httpx.Response(201, json={**body, "grant_id": str(uuid4()),
                "actor_identity_id": str(uuid4()), "integration_token": "integration-private-secret-0123456789"})
        raise AssertionError(path)


@pytest.fixture
def installation(monkeypatch):
    # Unix socket paths remain short on macOS as well as Linux CI.
    with tempfile.TemporaryDirectory(prefix="htsetup-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        monkeypatch.setenv("HOME", str(root))
        operator = root / "operator.key"
        operator.write_text("operator-private-secret\n")
        operator.chmod(0o600)
        directory = root / "private" / "project"
        project = str(uuid4())
        platform = Platform(directory, project)
        options = {"api_url": "https://platform.invalid/api/v1", "project_id": project,
                   "directory": directory, "operator_key_file": operator,
                   "transport": httpx.MockTransport(platform)}
        yield root, options, platform


@pytest.mark.parametrize("host,post_count", [("generic", 2), ("codex-desktop", 3)])
def test_setup_scopes_permissions_and_rerun_preserves_all_identities(installation, host, post_count):
    _, options, platform = installation
    result = setup(**options, host=host)
    directory = options["directory"]
    state_before = (directory / "setup.json").read_bytes()
    config_path = Path(result["config_path"])
    config = json.loads(config_path.read_text())
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(Path(config["state_dir"]).stat().st_mode) == 0o700
    for name in ("setup.json", "client.json", "device.token", "integration.token", "setup.lock"):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600
    # Later controlled workspace registrations survive setup/doctor unchanged.
    config["workspaces"] = {str(uuid4()): {"path": "/controlled/source"}}
    config_path.write_text(json.dumps(config))
    before_config = config_path.read_bytes()
    second = setup(**options, host=host)
    assert second["node_id"] == result["node_id"]
    assert second["client_instance_id"] == result["client_instance_id"]
    assert second["registration_id"] == result["registration_id"]
    assert (directory / "setup.json").read_bytes() == state_before
    assert config_path.read_bytes() == before_config
    assert len([c for c in platform.calls if c[0] == "POST"]) == post_count
    assert len(platform.nodes) == len(platform.registrations) == 1
    expected = READ_SCOPES + (["run:execute"] if host == "codex-desktop" else [])
    assert platform.registrations[0]["scopes"] == expected
    assert bool(platform.capabilities) == (host == "codex-desktop")
    if platform.capabilities:
        assert platform.capabilities[0]["capability"] == "harness"
        assert platform.capabilities[0]["constraints"] == {"interactive_host_adapters": ["codex-desktop-stdio/v1"]}
    public = json.dumps(result)
    assert "private-secret" not in public
    assert "operator.key" not in public
    assert result["source_acquisition_granted"] is False
    assert result["issue_executor_granted"] is False
    assert result["doctor"]["execution_bound"] is False
    assert result["doctor"]["integration_authorization"] == "CHECKED"
    assert "operator-private-secret" not in "".join(p.read_text() for p in directory.iterdir() if p.is_file())


@pytest.mark.parametrize("step,host", [("pair", "generic"), ("harness", "codex-desktop"),
                                       ("registration", "generic")])
def test_lost_one_time_secret_response_is_durable_and_never_retried(installation, step, host):
    _, options, platform = installation
    platform.fail = step
    code = "SETUP_UNKNOWN_" + step.upper() + "_ADMIN_RECONCILIATION_REQUIRED"
    with pytest.raises(ClientError, match=code):
        setup(**options, host=host)
    state = json.loads((options["directory"] / "setup.json").read_text())
    assert state["steps"][step]["status"] == "UNKNOWN"
    before = len(platform.calls)
    platform.fail = None
    with pytest.raises(ClientError, match=code):
        setup(**options, host=host)
    assert len(platform.calls) == before
    assert json.loads((options["directory"] / "setup.json").read_text())["node_key"] == state["node_key"]
    assert "private response" not in code


@pytest.mark.parametrize("url", ["http://remote.invalid/api/v1", "https://user:secret@platform.invalid/api/v1",
                                 "https://platform.invalid/api/v1?token=secret", "https://platform.invalid/project/1",
                                 "https://platform.invalid/api/v1#fragment"])
def test_setup_rejects_noncanonical_or_credential_urls_before_network(installation, url):
    _, options, platform = installation
    with pytest.raises(ClientError, match="HTTPS_API_BASE_REQUIRED"):
        setup(**{**options, "api_url": url})
    assert not platform.calls


def test_redirect_and_unsupported_profile_fail_before_issuance(installation):
    _, options, platform = installation
    platform.redirect = True
    with pytest.raises(ClientError, match="REQUEST_REJECTED"):
        setup(**options)
    assert len(platform.calls) == 1
    assert platform.calls[0][2].url.host == "platform.invalid"
    platform.redirect = False
    platform.profile = "unknown-profile"
    with pytest.raises(ClientError, match="INTERACTIVE_PROFILE_UNSUPPORTED"):
        setup(**options)
    assert all(c[0] == "GET" for c in platform.calls)


def test_private_operator_file_and_configuration_are_never_overwritten(installation):
    root, options, platform = installation
    options["operator_key_file"].chmod(0o644)
    with pytest.raises(ClientError, match="PRIVATE_FILE_REQUIRED"):
        setup(**options)
    assert not platform.calls
    options["operator_key_file"].chmod(0o600)
    options["operator_key_file"].unlink()
    target = root / "real-key"
    target.write_text("operator-private-secret")
    target.chmod(0o600)
    options["operator_key_file"].symlink_to(target)
    with pytest.raises(ClientError, match="PRIVATE_FILE_UNAVAILABLE"):
        setup(**options)
    assert not platform.calls


def test_bad_private_ca_and_nonprivate_directory_fail_without_post(installation):
    root, options, platform = installation
    bad_ca = root / "bad-ca.pem"
    bad_ca.write_text("invalid certificate")
    with pytest.raises(ClientError, match="TRUSTED_CA_FILE_REQUIRED"):
        setup(**options, ca_file=bad_ca)
    assert not platform.calls
    other = root / "public-directory"
    other.mkdir(mode=0o755)
    with pytest.raises(ClientError, match="PRIVATE_DIRECTORY_REQUIRED"):
        setup(**{**options, "directory": other})
    assert not platform.calls


def test_completed_setup_does_not_replace_revoked_device_or_capability(installation):
    _, options, platform = installation
    setup(**options, host="codex-desktop")
    post_count = len([c for c in platform.calls if c[0] == "POST"])
    platform.capabilities[0]["status"] = "REVOKED"
    with pytest.raises(ClientError, match="SETUP_HARNESS_REVOKED_OR_MISMATCHED"):
        setup(**options, host="codex-desktop")
    platform.nodes[0]["registration_status"] = "REVOKED"
    with pytest.raises(ClientError, match="SETUP_DEVICE_REVOKED_OR_MISMATCHED"):
        setup(**options, host="codex-desktop")
    assert len([c for c in platform.calls if c[0] == "POST"]) == post_count


def test_doctor_is_read_only_and_checks_credentials_without_bind_or_provider(installation):
    _, options, platform = installation
    result = setup(**options)
    platform.calls.clear()
    checked = doctor(Path(result["config_path"]), transport=options["transport"])
    assert checked["local_execution"] == "HOST_UNSUPPORTED"
    assert checked["execution_bound"] is False
    assert [c[:2] for c in platform.calls] == [
        ("GET", "interactive/capabilities"), ("GET", "interactive/submissions/by-key")]
    config = Path(result["config_path"])
    config.chmod(0o644)
    with pytest.raises(ClientError, match="PRIVATE_FILE_REQUIRED"):
        doctor(config, transport=options["transport"])


def test_setup_without_private_tty_requires_secret_file_and_never_prints_prompt(installation, monkeypatch):
    _, options, platform = installation
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(ClientError, match="OPERATOR_KEY_FILE_OR_PRIVATE_TTY_REQUIRED"):
        setup(**{**options, "operator_key_file": None})
    assert not platform.calls


def test_input_changes_do_not_create_a_replacement_registration(installation):
    _, options, platform = installation
    setup(**options)
    before = len(platform.calls)
    with pytest.raises(ClientError, match="SETUP_IDENTITY_CONFLICT"):
        setup(**options, host="codex-desktop")
    assert len(platform.calls) == before


def test_cli_dispatches_setup_and_doctor_and_emits_only_sanitized_result(installation, monkeypatch, capsys):
    from hypertest.interactive_client.__main__ import main

    _, options, _ = installation
    seen = []
    def configured(**kwargs):
        seen.append(kwargs)
        return {"status": "CONFIGURED", "config_path": "/private/client.json"}
    monkeypatch.setattr("hypertest.interactive_client.setup.setup", configured)
    monkeypatch.setattr("sys.argv", ["hypertest-interactive", "setup", "--api-url", options["api_url"],
        "--project-id", options["project_id"], "--directory", str(options["directory"]),
        "--operator-key-file", str(options["operator_key_file"]), "--host", "codex-desktop"])
    main()
    assert json.loads(capsys.readouterr().out)["status"] == "CONFIGURED"
    assert seen[0]["host"] == "codex-desktop"
    assert seen[0]["operator_key_file"] == options["operator_key_file"]


def test_setup_durable_lock_excludes_another_installer(installation):
    from hypertest.interactive_client.setup import _directory, _lock

    _, options, platform = installation
    directory = _directory(options["directory"])
    with _lock(directory), pytest.raises(ClientError, match="SETUP_ALREADY_RUNNING"):
        setup(**options)
    assert not platform.calls


def test_partial_setup_with_known_pair_can_complete_remaining_steps_without_pairing_again(installation, monkeypatch):
    from hypertest.interactive_client import setup as installer

    _, options, platform = installation
    original_post = installer._post
    def interrupted(state, state_path, name, *args):
        if name == "registration":
            raise ClientError("LOCAL_PROCESS_INTERRUPTED_BEFORE_NEW_INTENT")
        return original_post(state, state_path, name, *args)
    monkeypatch.setattr(installer, "_post", interrupted)
    with pytest.raises(ClientError, match="LOCAL_PROCESS_INTERRUPTED"):
        setup(**options)
    monkeypatch.setattr(installer, "_post", original_post)
    result = setup(**options)
    assert result["status"] == "CONFIGURED"
    assert len(platform.nodes) == 1
    assert len([c for c in platform.calls if c[:2] == ("POST", "harness-nodes/pair")]) == 1
    assert len(platform.registrations) == 1


def test_print_client_config_supports_path_only_json_and_codex_toml(installation, monkeypatch, capsys):
    from hypertest.interactive_client.__main__ import main

    _, options, _ = installation
    result = setup(**options)
    config = result["config_path"]
    for encoding in ("json", "codex"):
        monkeypatch.setattr("sys.argv", ["hypertest-interactive", "print-client-config", "--config", config,
                                        "--format", encoding])
        main()
        output = capsys.readouterr().out
        value = json.loads(output)["mcpServers"]["hypertest"] if encoding == "json" else (
            tomllib.loads(output)["mcp_servers"]["hypertest"])
        assert value["args"][-3:] == ["--config", config, "--autostart"]
        assert "private-secret" not in output
        assert "operator.key" not in output


def test_doctor_does_not_claim_live_authorization_without_setup_context(installation):
    _, options, _ = installation
    result = setup(**options)
    (options["directory"] / "setup.json").unlink()
    checked = doctor(Path(result["config_path"]), transport=options["transport"])
    assert checked["integration_authorization"] == "NOT_PROBED"
    assert checked["submission_and_reads"] is False
    assert checked["execution_bound"] is False
