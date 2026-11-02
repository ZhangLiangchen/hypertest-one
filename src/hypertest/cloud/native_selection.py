"""Read the pinned Harness SDK profile's native model selection without inference.

The SDK initialize protocol requires a provider and model.  The owning Harness
profile persists that selection, so project only that native configuration;
never persist or log the remaining resolved configuration, which may contain
private provider and plugin settings.
"""
from __future__ import annotations

import os
import selectors
import subprocess
import time
from pathlib import Path

from .errors import CloudBlocked

_MAX_DUMP_BYTES = 4 * 1024 * 1024
_DUMP_TIMEOUT_SECONDS = 30


def _parse_selection(data: bytes) -> dict:
    import yaml

    class DataOnlyLoader(yaml.SafeLoader):
        pass

    # The official resolved dump contains JS expressions as tagged scalar
    # values. Treat them as inert text: do not evaluate or construct objects.
    DataOnlyLoader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
    document = yaml.load(data, Loader=DataOnlyLoader)
    if not isinstance(document, list):
        raise ValueError("invalid resolved composition")
    matches = [row for row in document if isinstance(row, dict)
               and row.get("id") == "agent-default-model"
               and row.get("name") == "@deepseek-ai/dsh-agent-default-model"
               and row.get("disabled") is not True]
    if len(matches) != 1 or not isinstance(matches[0].get("config"), dict):
        raise ValueError("default selection unavailable")
    config = matches[0]["config"]
    result = {"provider": config.get("provider"), "model": config.get("model")}
    if config.get("reasoningEffort") is not None:
        result["reasoning_effort"] = config["reasoningEffort"]
    if any(not isinstance(value, str) or not value or len(value) > 255 or "\x00" in value
           for value in result.values()):
        raise ValueError("invalid default selection")
    return result


def read_native_selection(*, dsh_home: str, cwd: str, environment: dict[str, str] | None = None) -> dict:
    """Project SDK profile selection using the pinned runtime, with no prompt."""
    from deepseek_harness_runtime import resolve_bundled_launch_args

    process = None
    try:
        command = [*resolve_bundled_launch_args(), "--profile", "sdk", "--dump-config"]
        # Existing isolated callers receive a minimal environment. The host
        # driver may explicitly supply its already filtered native environment.
        env = ({"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path(dsh_home).parent),
                "LANG": "C.UTF-8"} if environment is None else dict(environment))
        env["DSH_HOME"] = dsh_home
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert process.stdout is not None
        output = bytearray()
        deadline = time.monotonic() + _DUMP_TIMEOUT_SECONDS
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError
                chunk = os.read(process.stdout.fileno(), min(65536, _MAX_DUMP_BYTES + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > _MAX_DUMP_BYTES:
                    raise ValueError("resolved configuration exceeds limit")
        if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
            raise ValueError("profile resolution failed")
        return _parse_selection(bytes(output))
    except Exception:
        raise CloudBlocked("HARNESS_CONFIG_UNAVAILABLE", "The SDK profile's native model selection could not be read") from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
