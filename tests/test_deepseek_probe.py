"""Diagnostics distinguish installation, protocol observation and cloud execution."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hypertest import deepseek_probe
from hypertest.deepseek_harness import SDK_VERSION
from hypertest.deepseek_harness.models import SERVER_NAME, SERVER_VERSION


def _compatible(*, sdk=SDK_VERSION, runtime=SDK_VERSION, compatible=True):
    return SimpleNamespace(sdk_version=sdk, runtime_version=runtime, compatible=compatible)


def _installed(monkeypatch):
    monkeypatch.setattr(deepseek_probe, "inspect_compatibility", lambda: _compatible())


def _result(**changes):
    values = {
        "runtime_started": True,
        "initialized": True,
        "session_created": True,
        "runtime_closed": True,
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _must_not_probe(**_):
    raise AssertionError("The runtime must not start for this diagnostic")


@pytest.mark.parametrize("args", [[], ["doctor"]])
def test_default_doctor_does_not_start_runtime_or_claim_model_readiness(monkeypatch, capsys, args):
    _installed(monkeypatch)
    monkeypatch.setattr(deepseek_probe, "probe_protocol", _must_not_probe)
    assert deepseek_probe.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "COMPATIBLE"
    assert report["process_probe"] == "NOT_RUN"
    assert report["reason"] == "PACKAGE_METADATA_ONLY"
    assert report["cloud_execution"] == "NOT_ASSESSED"
    assert report["diagnostic_only"] is True
    assert {"model_execution", "codex_delegation", "claude_code_delegation",
            "project_test_execution", "session_recovery"} <= set(report["not_proven"])
    assert "observations" not in report


def test_probe_requires_explicit_flag_before_even_inspecting_packages(monkeypatch, capsys):
    def forbidden_inspection():
        raise AssertionError("No inspection or runtime work before the explicit flag")

    monkeypatch.setattr(deepseek_probe, "inspect_compatibility", forbidden_inspection)
    monkeypatch.setattr(deepseek_probe, "probe_protocol", _must_not_probe)
    assert deepseek_probe.main(["probe"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["reason"] == "EXPLICIT_PROTOCOL_PROBE_FLAG_REQUIRED"
    assert report["process_probe"] == "NOT_RUN"


@pytest.mark.parametrize(
    ("sdk", "runtime", "compatible", "status", "reason"),
    [
        (None, None, False, "UNAVAILABLE", "SDK_NOT_INSTALLED"),
        (SDK_VERSION, None, False, "UNAVAILABLE", "RUNTIME_NOT_INSTALLED"),
        ("0.2.0", SDK_VERSION, False, "INCOMPATIBLE", "PINNED_PAIR_REQUIRED"),
        ("0.2.0", "0.2.0", False, "INCOMPATIBLE", "PINNED_PAIR_REQUIRED"),
    ],
)
def test_unavailable_or_unpinned_pair_cannot_start_protocol_probe(
    monkeypatch, capsys, sdk, runtime, compatible, status, reason
):
    monkeypatch.setattr(
        deepseek_probe, "inspect_compatibility",
        lambda: _compatible(sdk=sdk, runtime=runtime, compatible=compatible),
    )
    monkeypatch.setattr(deepseek_probe, "probe_protocol", _must_not_probe)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == status
    assert report["reason"] == reason
    assert report["process_probe"] == "NOT_RUN"


def test_successful_probe_checks_wire_server_version_separately_from_package_pin(
    monkeypatch, capsys
):
    _installed(monkeypatch)
    calls = []

    def probe(**kwargs):
        calls.append(kwargs)
        return _result()

    monkeypatch.setattr(deepseek_probe, "probe_protocol", probe)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe", "--timeout-seconds", "7"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert calls == [{"timeout_seconds": 7.0}]
    assert report["installation"]["pinned_version"] == SDK_VERSION
    assert SERVER_VERSION != SDK_VERSION
    assert report["status"] == "PROTOCOL_OBSERVED"
    assert report["observations"]["server_identity_matches_protocol"] is True
    assert report["reason"] == "NO_PROMPT_SUBMITTED"
    assert "project_test_execution" in report["not_proven"]


@pytest.mark.parametrize(
    "changes",
    [
        {"runtime_closed": False},
        {"session_created": False},
        {"server_version": SDK_VERSION},
        {"server_name": "unexpected-server"},
    ],
)
def test_incomplete_probe_or_wrong_wire_identity_is_nonzero(monkeypatch, capsys, changes):
    _installed(monkeypatch)
    monkeypatch.setattr(deepseek_probe, "probe_protocol", lambda **_: _result(**changes))
    assert deepseek_probe.main(["probe", "--allow-protocol-probe"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PROBE_INCOMPLETE"
    assert report["process_probe"] == "INCOMPLETE"


def test_inspection_error_and_untrusted_metadata_never_echo_private_values(monkeypatch, capsys):
    canary = "synthetic-credential-canary@/private/home"
    monkeypatch.setattr(
        deepseek_probe, "inspect_compatibility",
        lambda: _compatible(sdk=canary, compatible=False),
    )
    assert deepseek_probe.main(["doctor"]) == 1
    rendered = capsys.readouterr().out
    assert canary not in rendered
    assert json.loads(rendered)["installation"]["sdk_version"] == "UNRECOGNIZED"

    def broken_inspection():
        raise RuntimeError(canary)

    monkeypatch.setattr(deepseek_probe, "inspect_compatibility", broken_inspection)
    assert deepseek_probe.main(["doctor"]) == 1
    rendered = capsys.readouterr().out
    assert canary not in rendered
    assert json.loads(rendered)["reason"] == "INSTALLATION_INSPECTION_FAILED"


@pytest.mark.parametrize("code", ["PROBE_TIMEOUT", "synthetic-private-exception-value"])
def test_probe_exception_projects_only_allowlisted_code(monkeypatch, capsys, code):
    _installed(monkeypatch)
    canary = "synthetic-private-runtime-output"

    class ProbeFailure(Exception):
        pass

    def fail(**_):
        error = ProbeFailure(canary)
        error.code = code
        raise error

    monkeypatch.setattr(deepseek_probe, "probe_protocol", fail)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe"]) == 1
    rendered = capsys.readouterr().out
    report = json.loads(rendered)
    assert canary not in rendered
    assert report["reason"] == ("PROBE_TIMEOUT" if code == "PROBE_TIMEOUT" else "PROBE_FAILED")
    assert report["cleanup"] == "NOT_PROVEN"
    assert report["process_probe"] == "FAILED"


@pytest.mark.parametrize("timeout", ["0", "61", "nan", "inf", "-1", "private-timeout-value"])
def test_invalid_timeout_cannot_start_process_or_echo_value(monkeypatch, capsys, timeout):
    monkeypatch.setattr(deepseek_probe, "probe_protocol", _must_not_probe)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe", "--timeout-seconds", timeout]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "private-timeout-value" not in captured.out
    assert json.loads(captured.out)["reason"] == "INVALID_ARGUMENTS"


@pytest.mark.parametrize("flag", ["--prompt", "--runtime-executable", "--api-key", "--dsh-home"])
def test_cli_has_no_prompt_credential_custom_runtime_or_existing_home_inputs(monkeypatch, capsys, flag):
    monkeypatch.setattr(deepseek_probe, "probe_protocol", _must_not_probe)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe", flag, "private-value"]) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "private-value" not in captured.out
    assert json.loads(captured.out)["process_probe"] == "NOT_RUN"


def test_native_identifiers_and_provider_metadata_are_not_cli_output(monkeypatch, capsys):
    _installed(monkeypatch)
    canary = "synthetic-private-native-session-and-home"
    observed = _result()
    observed.session_id = canary
    observed.dsh_home = canary
    observed.provider_output = canary
    monkeypatch.setattr(deepseek_probe, "probe_protocol", lambda **_: observed)
    assert deepseek_probe.main(["probe", "--allow-protocol-probe"]) == 0
    assert canary not in capsys.readouterr().out


def test_optional_dependency_pair_and_operator_entrypoint_stay_separate_from_base_install():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    pins = {f"deepseek-harness-sdk=={SDK_VERSION}", f"deepseek-harness-runtime-bin=={SDK_VERSION}"}
    assert pins <= set(project["optional-dependencies"]["cloud"])
    assert not any("deepseek-harness" in item for item in project["dependencies"])
    assert project["scripts"]["hypertest-deepseek"] == "hypertest.deepseek_probe:main"
