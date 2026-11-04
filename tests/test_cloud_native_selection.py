"""Harness-native default selection without any model or SUT request."""
from __future__ import annotations

import pytest

from hypertest.cloud.native_selection import _Expression, _parse_configuration, _parse_selection


def test_extracts_profile_selection_and_treats_js_tag_as_inert_data():
    raw = b"""
- id: untrusted-plugin
  disabled: !!js 'this is data, not code'
  config:
    secret: do-not-return
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config:
    provider: deepseek-official
    model: deepseek-v4-pro
    reasoningEffort: max
"""
    assert _parse_selection(raw) == {"provider": "deepseek-official", "model": "deepseek-v4-pro",
                                      "reasoning_effort": "max"}


def test_omitted_reasoning_follows_native_provider_default():
    raw = b"""
- id: agent-default-model
  name: '@deepseek-ai/dsh-agent-default-model'
  config: {provider: deepseek-official, model: native-choice}
"""
    assert _parse_selection(raw) == {"provider": "deepseek-official", "model": "native-choice"}


@pytest.mark.parametrize("raw", [
    b"[]",
    b"- {id: agent-default-model, name: '@deepseek-ai/dsh-agent-default-model', config: {provider: x, model: ''}}",
    b"- {id: agent-default-model, name: '@deepseek-ai/dsh-agent-default-model', config: {provider: x, model: a}}\n"
    b"- {id: agent-default-model, name: '@deepseek-ai/dsh-agent-default-model', config: {provider: x, model: b}}",
])
def test_missing_or_ambiguous_selection_is_rejected(raw):
    with pytest.raises(ValueError):
        _parse_selection(raw)


_MODEL = b"- {id: agent-default-model, name: '@deepseek-ai/dsh-agent-default-model', config: {provider: x, model: y}}\n"


def test_configuration_preserves_native_policy_without_returning_other_plugin_values():
    raw = _MODEL + b"""
- id: private-plugin
  config: {secret: never-return}
- id: sandbox-policy
  name: '@deepseek-ai/dsh-sandbox-policy'
  config:
    mode: !!js "process.env.DSH_PERMISSION_MODE ?? 'workspace-write'"
    workspaceRoot: !!js process.cwd()
    additionalWritableRoots: [/existing/authorized]
"""
    selection, policy = _parse_configuration(raw, {"DSH_PERMISSION_MODE": "read-only"})
    assert selection == {"provider": "x", "model": "y"}
    assert policy == {"mode": "process.env.DSH_PERMISSION_MODE ?? 'workspace-write'",
                      "workspaceRoot": "process.cwd()", "additionalWritableRoots": ["/existing/authorized"]}
    assert isinstance(policy["mode"], _Expression) and isinstance(policy["workspaceRoot"], _Expression)
    with pytest.raises(ValueError):
        _parse_configuration(raw, {"DSH_PERMISSION_MODE": "danger-full-access"})


@pytest.mark.parametrize("config", [
    "{mode: danger-full-access}", "{mode: [workspace-write]}", "{mode: null}",
    "{mode: workspace-write, unexpected: value}", "{workspaceRoot: relative}", "{workspaceRoot: null}",
    "{mode: !!js 'process.env.UNKNOWN'}", "{workspaceRoot: !!js 'process.env.HOME'}",
    "{additionalWritableRoots: [relative]}", "{additionalWritableRoots: !!js '[]'}",
    "{additionalWritableRoots: [!!js 'process.cwd()']}",
])
def test_configuration_rejects_unknown_or_unconfined_policy(config):
    raw = _MODEL + ("- id: sandbox-policy\n  name: '@deepseek-ai/dsh-sandbox-policy'\n  config: " + config + "\n").encode()
    with pytest.raises(ValueError):
        _parse_configuration(raw, {})


@pytest.mark.parametrize("rows", ["", "- {id: sandbox-policy, name: wrong, config: {}}\n",
    "- {id: sandbox-policy, name: '@deepseek-ai/dsh-sandbox-policy', disabled: true, config: {}}\n",
    "- {id: sandbox-policy, name: '@deepseek-ai/dsh-sandbox-policy', config: {}}\n" * 2,
])
def test_configuration_rejects_missing_or_ambiguous_policy(rows):
    with pytest.raises(ValueError):
        _parse_configuration(_MODEL + rows.encode(), {})


def test_configuration_preserves_omitted_policy_defaults():
    assert _parse_configuration(_MODEL + b"- {id: sandbox-policy, name: '@deepseek-ai/dsh-sandbox-policy', config: {}}\n", {}) == (
        {"provider": "x", "model": "y"}, {})
