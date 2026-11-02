"""Host-only, bounded, read-only model identity observations.

This module never reports a key, response body, exception, account, or model
result. A successful catalog read proves only provider acceptance at that time.
"""
from __future__ import annotations

import hmac
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from .errors import CloudBlocked
from .private_file import read_private_file

AuthStatus = Literal["VALID", "INVALID", "UNKNOWN"]
_URL = "https://api.deepseek.com/models"
_SOCKET_TIMEOUT = 5
_DEADLINE = 8


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read_key(key_path: str) -> tuple[bytes | None, AuthStatus]:
    try:
        key = read_private_file(key_path, max_bytes=65536).strip()
    except CloudBlocked as error:
        if error.code == "PRIVATE_FILE_SIZE":
            return None, "INVALID"
        if error.code == "PRIVATE_FILE_UNAVAILABLE":
            try:
                os.lstat(key_path)
            except FileNotFoundError:
                return None, "INVALID"
            except OSError:
                pass
        return None, "UNKNOWN"
    if not key or any(c < 33 or c > 126 for c in key):
        return None, "INVALID"
    return key, "UNKNOWN"


def _probe_once(key_path: str) -> AuthStatus:
    """One HTTPS request; only the public worker wrapper supplies a deadline."""
    key, unavailable = _read_key(key_path)
    if key is None:
        return unavailable
    try:
        # Existing service admission permits surrounding whitespace, but not
        # embedded newlines; never place an invalid key in an HTTP header.
        request = urllib.request.Request(_URL, method="GET", headers={"Authorization": "Bearer " + key.decode("ascii")})
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=_SOCKET_TIMEOUT) as response:
                status: AuthStatus = "VALID" if response.status == 200 else "UNKNOWN"
        except urllib.error.HTTPError as error:
            status = "INVALID" if error.code == 401 else "UNKNOWN"
            error.close()
        except Exception:
            return "UNKNOWN"
        current, _ = _read_key(key_path)
        try:
            return status if current is not None and hmac.compare_digest(key, current) else "UNKNOWN"
        finally:
            del current
    finally:
        del key


def probe_deepseek_auth(key_path: str | Path) -> AuthStatus:
    """Read the worker's key and observe provider acceptance with a hard limit.

    DNS resolution is not bounded by Python socket timeouts, so the probe runs
    in a short-lived child and is killed by subprocess.run at the deadline. The
    path goes via stdin, not the command line; the key never leaves the child
    except as the Authorization header to the fixed HTTPS provider. Only the
    standard credentials-directory metadata is inherited, not worker secrets.
    """
    try:
        path = os.fspath(key_path)
        if not isinstance(path, str) or not path or len(path.encode("utf-8")) > 4096:
            return "UNKNOWN"
        env = {"PYTHONDONTWRITEBYTECODE": "1"}
        if "CREDENTIALS_DIRECTORY" in os.environ:
            env["CREDENTIALS_DIRECTORY"] = os.environ["CREDENTIALS_DIRECTORY"]
        result = subprocess.run([sys.executable, "-m", "hypertest.cloud.auth_probe"],
            input=path.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, timeout=_DEADLINE, check=False)
        if result.returncode != 0:
            return "UNKNOWN"
        if result.stdout == b"VALID\n":
            return "VALID"
        if result.stdout == b"INVALID\n":
            return "INVALID"
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        pass
    return "UNKNOWN"


def _main() -> None:
    try:
        raw = sys.stdin.buffer.read(4097)
        status = _probe_once(raw.decode("utf-8")) if len(raw) <= 4096 else "UNKNOWN"
    except Exception:
        status = "UNKNOWN"
    print(status, flush=True)


if __name__ == "__main__":
    _main()
