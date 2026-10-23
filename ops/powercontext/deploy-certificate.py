#!/usr/bin/python3
"""Root-only certificate staging; atomically replace one validated pair pointer."""

import argparse
import datetime
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid


TLS_ROOT = Path("/etc/powercontext/proxy-tls")
CONFIG = Path("/etc/powercontext/proxy.conf")
NGINX = "/opt/powercontext/proxy/nginx-1.26.3-3+deb13u10/root/usr/sbin/nginx"
SERVICE = "powercontext-proxy.service"


def checked(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "command failed: " + args[0])
    return result.stdout


def validate_config(path):
    checked(["runuser", "-u", "powercontext-proxy", "--", NGINX, "-t", "-c", str(path)])


def point_to(target):
    temporary = TLS_ROOT / (".current-" + uuid.uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, TLS_ROOT / "current")


def leaf_digest(path):
    pem = path.read_text().split("-----END CERTIFICATE-----", 1)[0]
    pem += "-----END CERTIFICATE-----\n"
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest()


def verify_served_certificate(expected):
    host = json.loads(Path("/etc/powercontext/deployment.json").read_text())["host"]
    context = ssl.create_default_context()
    last_error = None
    for _ in range(10):
        try:
            with socket.create_connection((host, 8443), timeout=3) as raw:
                with context.wrap_socket(raw, server_hostname=host) as connection:
                    if hashlib.sha256(connection.getpeercert(binary_form=True)).digest() == expected:
                        return
                    last_error = "proxy has not loaded the staged certificate"
        except OSError as error:
            last_error = str(error)
        time.sleep(0.5)
    raise RuntimeError(str(last_error))


def main():
    if os.geteuid() != 0:
        raise RuntimeError("certificate deployment requires root")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/etc/powercontext/acme/live/powercontext-ip"))
    args = parser.parse_args()
    proxy_gid = grp.getgrnam("powercontext-proxy").gr_gid
    releases = TLS_ROOT / "releases"
    releases.mkdir(exist_ok=True)
    os.chown(releases, 0, proxy_gid)
    releases.chmod(0o750)
    current = TLS_ROOT / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError("current must be a root-managed symlink")
    previous = current.resolve(strict=True) if current.is_symlink() else None
    active = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0
    if active and previous is None:
        raise RuntimeError("an active proxy requires a previous certificate pair")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    stage = Path(tempfile.mkdtemp(prefix=stamp, dir=releases))
    for name, mode in [("fullchain.pem", 0o644), ("privkey.pem", 0o640)]:
        target = stage / name
        shutil.copyfile(args.source / name, target)
        os.chown(target, 0, proxy_gid)
        target.chmod(mode)
    os.chown(stage, 0, proxy_gid)
    stage.chmod(0o750)
    checked(["openssl", "x509", "-in", str(stage / "fullchain.pem"), "-checkend", "3600", "-noout"])
    checked(["openssl", "pkey", "-in", str(stage / "privkey.pem"), "-check", "-noout"])
    certificate_key = checked(["openssl", "x509", "-in", str(stage / "fullchain.pem"), "-pubkey", "-noout"])
    private_key_public = checked(["openssl", "pkey", "-in", str(stage / "privkey.pem"), "-pubout"])
    if certificate_key != private_key_public:
        raise RuntimeError("staged certificate and private key do not match")
    checked(["openssl", "verify", "-purpose", "sslserver", "-untrusted", str(stage / "fullchain.pem"), str(stage / "fullchain.pem")])
    runtime = Path("/run/powercontext-proxy")
    runtime.mkdir(exist_ok=True)
    os.chown(runtime, pwd.getpwnam("powercontext-proxy").pw_uid, proxy_gid)
    runtime.chmod(0o750)
    candidate = stage / "proxy-test.conf"
    original = CONFIG.read_text()
    if original.count(str(TLS_ROOT / "current") + "/") != 2:
        raise RuntimeError("proxy must reference the current certificate pair")
    candidate.write_text(original.replace(str(TLS_ROOT / "current") + "/", str(stage) + "/"))
    os.chown(candidate, 0, proxy_gid)
    candidate.chmod(0o640)
    validate_config(candidate)
    switched = False
    try:
        point_to(stage)
        switched = True
        validate_config(CONFIG)
        if active:
            checked(["systemctl", "reload", SERVICE])
            verify_served_certificate(leaf_digest(stage / "fullchain.pem"))
    except BaseException:
        if switched:
            if previous is not None:
                point_to(previous)
                try:
                    validate_config(CONFIG)
                    if active:
                        checked(["systemctl", "reload", SERVICE])
                        verify_served_certificate(leaf_digest(previous / "fullchain.pem"))
                except Exception as recovery_error:
                    print("Previous pair restored; proxy recovery needs inspection: " + str(recovery_error), file=sys.stderr)
            elif current.is_symlink() and current.resolve() == stage:
                current.unlink()
        raise
    print("PowerContext certificate pair activated; previous versions retained")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("PowerContext certificate activation failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
