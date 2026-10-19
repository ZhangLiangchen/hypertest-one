"""Validate the installed OpenSSH parser without starting sshd or connecting."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_ssh_dropin_denies_forwarding_and_preserves_authentication(tmp_path):
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    keygen = shutil.which("ssh-keygen")
    if not Path(sshd).is_file() or not keygen:
        pytest.skip("OpenSSH daemon parser and key generator required")
    key = tmp_path / "test_host_key"
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                   check=True, capture_output=True)
    config = tmp_path / "sshd_config"
    dropin = ROOT / "ops/ssh/00-hypertest-no-forwarding.conf"
    # No daemon is started. These are disposable keys, never the user's host keys.
    baseline = f"HostKey {key}\nPasswordAuthentication yes\nPubkeyAuthentication yes\nPermitRootLogin yes\n"

    def effective(source):
        config.write_text(source)
        result = subprocess.run([sshd, "-T", "-f", str(config), "-C",
                                 "user=root,host=example,addr=192.0.2.44,laddr=203.0.113.10,lport=22"],
                                capture_output=True, text=True)
        if result.returncode and "Missing privilege separation directory" in result.stderr:
            pytest.skip("installed OpenSSH parser requires an unavailable host runtime directory")
        result.check_returncode()
        return dict(line.split(" ", 1) for line in result.stdout.splitlines())

    original = effective(baseline)
    restricted = effective(f"Include {dropin}\n" + baseline)
    assert restricted["disableforwarding"] == "yes"
    assert restricted["allowtcpforwarding"] == "no"
    assert restricted["allowstreamlocalforwarding"] == "no"
    assert restricted["permittunnel"] == "no"
    for field in ("passwordauthentication", "pubkeyauthentication", "permitrootlogin",
                  "authenticationmethods", "hostkey"):
        assert restricted[field] == original[field]
