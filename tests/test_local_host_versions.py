"""Automatic trigger enablement uses the installed CLI, not a supplied label."""
from pathlib import Path

import pytest

from hypertest.interactive_client.errors import ClientError
from hypertest.local_sync.hosts import probe_native_version


def executable(tmp_path: Path, output: str) -> Path:
    path = tmp_path / "native-cli"
    path.write_text("#!/bin/sh\nprintf '%s\\n' '" + output + "'\n")
    path.chmod(0o700)
    return path


@pytest.mark.parametrize(("host", "output", "version"), [
    ("codex", "codex-cli 0.144.6", "0.144.6"),
    ("claude-code", "2.1.218 (Claude Code)", "2.1.218"),
])
def test_real_version_probe_returns_only_the_parsed_supported_version(tmp_path, host, output, version):
    metadata = probe_native_version(host, executable=executable(tmp_path, output))
    assert metadata["harness_version"] == version and "stdout" not in metadata


def test_unknown_or_unparseable_native_cli_never_enables_automatic_events(tmp_path):
    with pytest.raises(ClientError, match="LOCAL_HOST_AUTOMATIC_VERSION_UNSUPPORTED"):
        probe_native_version("codex", executable=executable(tmp_path, "codex-cli 0.100.0"))
    with pytest.raises(ClientError, match="LOCAL_HOST_VERSION_PROBE_FAILED"):
        probe_native_version("claude-code", executable=executable(tmp_path, "unrelated tool"))
