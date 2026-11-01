"""Harness-native default selection without any model or SUT request."""
from __future__ import annotations

import pytest

from hypertest.cloud.native_selection import _parse_selection


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
