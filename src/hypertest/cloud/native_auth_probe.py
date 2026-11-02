"""Read-only, redacted authentication observation for the native Harness profile."""
from __future__ import annotations

import hmac
import json
import os
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _key(home: Path) -> str | None:
    import yaml
    path = home / ".credentials.yaml"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
            return None
        doc = yaml.safe_load(stream.read(1024 * 1024 + 1))
    value = doc.get("refs", {}).get("DEEPSEEK_API_KEY") if isinstance(doc, dict) else None
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        return None
    return value


def _check(home: str) -> str:
    """Only the known official API-key route is admitted; other profiles stay unknown."""
    import yaml
    from deepseek_harness_runtime import resolve_bundled_launch_args

    from .native_selection import _parse_selection

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
    env = dict(os.environ)
    env["DSH_HOME"] = home
    # An origin override may point at another provider; do not send its secret.
    if env.get("DEEPSEEK_BASE_URL") not in (None, "", "https://api.deepseek.com"):
        return "UNKNOWN"
    result = subprocess.run([*resolve_bundled_launch_args(), "--profile", "sdk", "--dump-config"],
                            cwd=home, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=25, check=False)
    if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
        return "UNKNOWN"
    if _parse_selection(result.stdout).get("provider") != "deepseek-official":
        return "UNKNOWN"
    rows = yaml.load(result.stdout, Loader=Loader)
    credentials = [r for r in rows if isinstance(r, dict) and r.get("name") == "@deepseek-ai/dsh-credentials-local"
                   and r.get("disabled") is not True]
    if len(credentials) != 1:
        return "UNKNOWN"
    credential_config = credentials[0].get("config")
    if credential_config is not None and not isinstance(credential_config, dict):
        return "UNKNOWN"
    if (credential_config or {}).get("path") not in (None, ""):
        return "UNKNOWN"
    plugins = [r for r in rows if isinstance(r, dict) and r.get("name") == "@deepseek-ai/dsh-llm-deepseek-api-key"
               and r.get("disabled") is not True]
    if len(plugins) != 1:
        return "UNKNOWN"
    config = plugins[0].get("config")
    if config is not None and not isinstance(config, dict):
        return "UNKNOWN"
    config = config or {}
    if config.get("apiKeyEnv", "DEEPSEEK_API_KEY") != "DEEPSEEK_API_KEY":
        return "UNKNOWN"
    if config.get("baseURL") not in (None, "", "https://api.deepseek.com"):
        return "UNKNOWN"
    key = _key(Path(home))
    if key is None:
        return "UNKNOWN"
    try:
        request = urllib.request.Request("https://api.deepseek.com/models", method="GET", headers={"x-api-key": key})
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                status = "VALID" if response.status == 200 else "UNKNOWN"
        except urllib.error.HTTPError as error:
            status = "INVALID" if error.code == 401 else "UNKNOWN"
            error.close()
        current = _key(Path(home))
        return status if current is not None and hmac.compare_digest(key, current) else "UNKNOWN"
    finally:
        del key


def probe_native_auth(dsh_home: str) -> str:
    """Bound DNS/runtime latency and return only VALID, INVALID or UNKNOWN."""
    from .native_sdk_adapter import host_environment
    try:
        result = subprocess.run([sys.executable, "-P", "-m", "hypertest.cloud.native_auth_probe"],
                                input=json.dumps({"dsh_home": dsh_home}).encode(),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=host_environment(os.environ), timeout=35, check=False)
        if result.returncode == 0 and result.stdout in (b"VALID\n", b"INVALID\n"):
            return result.stdout.decode().strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "UNKNOWN"


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(8193)
        arg = json.loads(raw)
        value = _check(arg["dsh_home"]) if len(raw) <= 8192 else "UNKNOWN"
    except Exception:
        value = "UNKNOWN"
    print(value if value in {"VALID", "INVALID", "UNKNOWN"} else "UNKNOWN", flush=True)
