"""Read the pinned Harness SDK profile's model and sandbox policy without inference.

The SDK initialize protocol requires a provider and model.  The owning Harness
profile persists that selection. Project only it and the explicit sandbox policy;
never persist or log the remaining resolved configuration, which may contain
private provider and plugin settings.
"""
from __future__ import annotations

import os
import selectors
import subprocess
import time
from pathlib import Path

import yaml

from .errors import CloudBlocked

_MAX_DUMP_BYTES = 4 * 1024 * 1024
_DUMP_TIMEOUT_SECONDS = 30


class _Expression(str):
    """An inert Loader expression, never evaluated by Python."""


class _DataOnlyLoader(yaml.SafeLoader):
    pass


_DataOnlyLoader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: _Expression(loader.construct_scalar(node)))
_MODE_EXPRESSION = "process.env.DSH_PERMISSION_MODE ?? 'workspace-write'"
_ROOT_EXPRESSION = "process.cwd()"


def _document(data: bytes) -> list:
    document = yaml.load(data, Loader=_DataOnlyLoader)
    if not isinstance(document, list):
        raise ValueError("invalid resolved composition")
    return document


def _selection(document: list) -> dict:
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


def _parse_selection(data: bytes) -> dict:
    return _selection(_document(data))


def _checked_sandbox_policy(config: dict, environment: dict[str, str]) -> dict:
    """Keep the native policy intact; accept only the pinned inert expressions."""
    if not isinstance(config, dict) or set(config) - {"mode", "workspaceRoot", "additionalWritableRoots"}:
        raise ValueError("unsupported sandbox policy")
    mode = config.get("mode", "read-only")
    if isinstance(mode, _Expression):
        if mode != _MODE_EXPRESSION:
            raise ValueError("unsupported sandbox mode expression")
        effective_mode = environment.get("DSH_PERMISSION_MODE", "workspace-write")
    else:
        effective_mode = mode
    if not isinstance(effective_mode, str) or effective_mode not in {"read-only", "workspace-write"}:
        raise ValueError("unconfined sandbox policy is not permitted")
    root = config.get("workspaceRoot")
    if isinstance(root, _Expression):
        if root != _ROOT_EXPRESSION:
            raise ValueError("unsupported workspace root expression")
    elif "workspaceRoot" in config and (not isinstance(root, str) or not Path(root).is_absolute() or "\x00" in root):
        raise ValueError("invalid workspace root")
    roots = config.get("additionalWritableRoots", [])
    if not isinstance(roots, list) or any(
        not isinstance(path, str) or isinstance(path, _Expression) or not Path(path).is_absolute() or "\x00" in path
        for path in roots
    ):
        raise ValueError("invalid additional writable roots")
    result = dict(config)
    if "additionalWritableRoots" in result:
        result["additionalWritableRoots"] = list(roots)
    return result


def _parse_configuration(data: bytes, environment: dict[str, str]) -> tuple[dict, dict]:
    document = _document(data)
    matches = [row for row in document if isinstance(row, dict) and row.get("id") == "sandbox-policy"]
    if (len(matches) != 1 or matches[0].get("name") != "@deepseek-ai/dsh-sandbox-policy"
            or matches[0].get("disabled", False) is not False or not isinstance(matches[0].get("config"), dict)):
        raise ValueError("sandbox policy unavailable")
    return _selection(document), _checked_sandbox_policy(matches[0]["config"], environment)


def read_native_selection(*, dsh_home: str, cwd: str, environment: dict[str, str] | None = None) -> dict:
    """Project SDK profile selection using the pinned runtime, with no prompt."""
    return _read_native_configuration(dsh_home=dsh_home, cwd=cwd, environment=environment, include_policy=False)


def read_native_configuration(*, dsh_home: str, cwd: str, environment: dict[str, str]) -> tuple[dict, dict]:
    """Project model and sandbox policy from one bounded dump, without a model call."""
    return _read_native_configuration(dsh_home=dsh_home, cwd=cwd, environment=environment, include_policy=True)


def _read_native_configuration(*, dsh_home: str, cwd: str, environment: dict[str, str] | None,
                               include_policy: bool):
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
        return _parse_configuration(bytes(output), env) if include_policy else _parse_selection(bytes(output))
    except Exception:
        raise CloudBlocked("HARNESS_CONFIG_UNAVAILABLE", "The SDK profile's native model selection could not be read") from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
