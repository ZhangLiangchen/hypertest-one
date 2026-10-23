#!/usr/bin/env python3
"""Bounded read-only metadata inventory of the existing dedicated test server.

No environment/key values, remote URLs, model call, Git mutation, Docker build,
service start, migration or file write is performed. Invoke with Python -B.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import ssl
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/opt/hypertest')
COMPOSE_ENV = Path('/etc/hypertest/container/compose.env')
PUBLIC_KEYS = frozenset({
    'HYPERTEST_STACK_NAME', 'HYPERTEST_UID', 'HYPERTEST_GID', 'HYPERTEST_API_IMAGE',
    'HYPERTEST_WORKER_IMAGE', 'HYPERTEST_WEB_IMAGE', 'HYPERTEST_POSTGRES_IMAGE',
    'HYPERTEST_NGINX_IMAGE', 'HYPERTEST_API_PORT', 'HYPERTEST_WEB_PORT',
    'HYPERTEST_POSTGRES_PORT', 'HYPERTEST_INGRESS_PORT', 'HYPERTEST_PUBLIC_IP',
    'HYPERTEST_VPN_CIDR', 'HYPERTEST_PUBLIC_INGRESS', 'HYPERTEST_INGRESS_TLS',
    'HYPERTEST_TLS_SERVER_NAME', 'HYPERTEST_TLS_CERT_FILE', 'HYPERTEST_TLS_KEY_FILE',
    'HYPERTEST_TLS_CA_FILE', 'HYPERTEST_NGINX_CONFIG', 'HYPERTEST_PLATFORM_ENV_FILE',
    'HYPERTEST_POSTGRES_ENV_FILE', 'HYPERTEST_POSTGRES_VOLUME', 'HYPERTEST_ARTIFACT_ROOT',
    'HYPERTEST_WORKSPACE_ROOT', 'HYPERTEST_CLOUD_API_SOCKET_DIR', 'HYPERTEST_CLOUD_API_CA_FILE',
})
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent',
    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0',
    'GIT_OPTIONAL_LOCKS': '0'}
DEADLINE = 0.0


def run(argv: list[str], *, cwd: Path | None = None, limit=65536) -> bytes | None:
    remaining = DEADLINE - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = subprocess.run(argv, cwd=cwd, env=ENV, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=min(6, remaining), check=False)
        return result.stdout if result.returncode == 0 and len(result.stdout) <= limit else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def metadata(path: Path) -> dict:
    try:
        info = path.lstat()
        return {'exists': True, 'canonical': str(path.resolve(strict=True)), 'symlink': path.is_symlink(),
            'uid': info.st_uid, 'gid': info.st_gid, 'mode': format(stat.S_IMODE(info.st_mode), '04o'),
            'regular': stat.S_ISREG(info.st_mode), 'directory': stat.S_ISDIR(info.st_mode)}
    except OSError:
        return {'exists': False}


def public_configuration() -> tuple[dict, dict[str, str]]:
    info = metadata(COMPOSE_ENV)
    values = {}
    if info.get('regular') and COMPOSE_ENV.stat().st_size <= 65536:
        for line in COMPOSE_ENV.read_text().splitlines():
            name, separator, value = line.partition('=')
            if separator and name in PUBLIC_KEYS and len(value) <= 4096 and not any(c in value for c in '\r\n\x00'):
                values[name] = value
    projected = {}
    for key, value in values.items():
        if key.endswith('_IMAGE'):
            valid = re.fullmatch(r'(?:sha256:[a-f0-9]{64}|[A-Za-z0-9_./:-]+@sha256:[a-f0-9]{64})', value)
        elif key.endswith(('_FILE', '_ROOT', '_DIR', '_CONFIG')):
            valid = value.startswith(('/etc/hypertest/', '/opt/hypertest/', '/run/', '/var/lib/hypertest/')) and '..' not in Path(value).parts
        elif key.endswith(('_PORT', '_UID', '_GID')):
            valid = value.isdigit() and 0 < int(value) <= 65535
        else:
            valid = re.fullmatch(r'[A-Za-z0-9_.:/-]{1,253}', value)
        projected[key] = value if valid else 'PRESENT_VALUE_NOT_PROJECTED'
    return {'file': info, 'present_public_keys': sorted(values), 'public_values': projected}, values


def git_state(path: Path) -> dict:
    result = {'path': str(path), **metadata(path)}
    try:
        canonical = path.resolve(strict=True)
    except OSError:
        return result
    flags = ['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null',
        '-c', 'core.untrackedCache=false', '-C', str(canonical)]
    head = run(flags + ['rev-parse', '--verify', 'HEAD^{commit}'])
    if head is None or not re.fullmatch(rb'[a-f0-9]{40}\n', head):
        result['git_checkout'] = False
        return result
    status = run(flags + ['status', '--porcelain=v1', '-z', '--untracked-files=all'], limit=1024**2)
    result.update(git_checkout=True, head=head.decode().strip(), clean=status == b'' if status is not None else None,
        changed_entries=len([row for row in status.split(b'\0') if row]) if status is not None else None)
    return result


def checkouts() -> list[dict]:
    candidates = [ROOT / 'ops-current', ROOT / 'container-current']
    try:
        first = sorted(ROOT.iterdir())[:80]
        for path in first:
            if path.is_dir() and not path.is_symlink():
                if (path / '.git').exists():
                    candidates.append(path)
                elif path.name in {'git', 'checkouts', 'repositories', 'source'}:
                    candidates.extend(p for p in sorted(path.iterdir())[:16] if p.is_dir() and (p / '.git').exists())
    except OSError:
        pass
    unique = list(dict.fromkeys(candidates))[:10]
    return [git_state(path) for path in unique]


def containers(stack: str) -> tuple[list[dict], str | None]:
    raw = run(['docker', 'ps', '--filter', 'label=com.docker.compose.project=' + stack,
        '--format', '{{.ID}}'])
    if raw is None:
        return [], None
    rows, postgres = [], []
    projection = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
        '"running":{{json .State.Running}},"status":{{json .State.Status}},"user":{{json .Config.User}},'
        '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"ports":{{json .HostConfig.PortBindings}}}')
    for identity in raw.decode().splitlines()[:12]:
        if not re.fullmatch('[a-f0-9]{12,64}', identity):
            continue
        value = run(['docker', 'inspect', '--format', projection, identity])
        try:
            row = json.loads(value) if value else None
            if not isinstance(row, dict) or not re.fullmatch('sha256:[a-f0-9]{64}', row.get('image', '')):
                continue
            if row.get('service') == 'postgres' and row.get('running') is True:
                postgres.append(row['id'])
            rows.append(row)
        except (ValueError, TypeError):
            continue
    return rows, postgres[0] if len(postgres) == 1 else None


def schema(identity: str | None) -> dict:
    if identity is None or not re.fullmatch('[a-f0-9]{64}', identity):
        return {'status': 'NOT_OBSERVED'}
    # Existing container-local identity only; never inspect or print Config.Env.
    command = 'exec psql -w -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "BEGIN READ ONLY; SELECT version_num FROM alembic_version ORDER BY version_num; ROLLBACK;"'
    raw = run(['docker', 'exec', '--env', 'PGCONNECT_TIMEOUT=3', '--env', 'PGOPTIONS=-c statement_timeout=3000',
        identity, '/bin/sh', '-c', command], limit=4096)
    if raw is None:
        return {'status': 'NOT_OBSERVED'}
    values = raw.decode().splitlines()
    if not 1 <= len(values) <= 8 or any(not re.fullmatch('[A-Za-z0-9_]{1,100}', value) for value in values):
        return {'status': 'NOT_OBSERVED'}
    return {'status': 'OBSERVED_READ_ONLY', 'alembic_heads': values}


def certificate(values: dict[str, str]) -> dict:
    raw = values.get('HYPERTEST_TLS_CERT_FILE', '')
    if not raw.startswith('/etc/hypertest/'):
        return {'status': 'NOT_OBSERVED'}
    try:
        decoded = ssl._ssl._test_decode_cert(raw)
        sans = [[kind, value] for kind, value in decoded.get('subjectAltName', [])
            if kind in {'DNS', 'IP Address'} and re.fullmatch('[A-Za-z0-9.*:-]{1,253}', value)]
        return {'status': 'PUBLIC_CERTIFICATE_ONLY', 'san': sans, 'not_after': decoded.get('notAfter'),
            'certificate_sha256': hashlib.sha256(Path(raw).read_bytes()).hexdigest()}
    except (OSError, ValueError, ssl.SSLError):
        return {'status': 'NOT_OBSERVED'}


def main() -> int:
    global DEADLINE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-read-only-inventory', action='store_true')
    args = parser.parse_args()
    if not args.allow_read_only_inventory or sys.platform != 'linux':
        return 2
    DEADLINE = time.monotonic() + 45
    configuration, values = public_configuration()
    stack = values.get('HYPERTEST_STACK_NAME', 'hypertest-production')
    if not re.fullmatch('[A-Za-z0-9_.-]{1,128}', stack):
        return 2
    running, postgres = containers(stack)
    files = [Path(name) for name in ('/etc/hypertest/cloud/deepseek-api-key',
        '/etc/hypertest/cloud/wrapping-key', '/etc/hypertest/cloud/acceptance/wrapping-key',
        '/var/lib/hypertest/.codex/auth.json', '/var/lib/hypertest-cloud/runtime',
        '/etc/hypertest/container/tls/ca.crt', '/run/hypertest-cloud-web')]
    identities = {}
    for name in ('hypertest-cloud', 'hypertest'):
        try:
            user = pwd.getpwnam(name)
            identities[name] = {'exists': True, 'uid': user.pw_uid, 'gid': user.pw_gid,
                'home': user.pw_dir, 'shell': user.pw_shell}
        except KeyError:
            identities[name] = {'exists': False}
    disk = shutil.disk_usage(ROOT)
    memory = {key: int(value.split()[0]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
        for key, _, value in [line.partition(':')] if key in {'MemTotal', 'MemAvailable', 'SwapTotal'}}
    result = {'profile': 'hypertest-cloud-host-readonly-inventory/v1', 'read_only': True,
        'configuration': configuration, 'checkouts': checkouts(), 'containers': running,
        'schema': schema(postgres), 'public_tls_certificate': certificate(values), 'accounts': identities,
        'worker_prerequisite_metadata_only': {str(path): metadata(path) for path in files},
        'tools': {name: shutil.which(name, path=ENV['PATH']) for name in ('docker', 'git', 'systemd-run', 'bwrap', 'ssh')},
        'build_resources': {'cpu_count': os.cpu_count(), 'disk_free_bytes': disk.free, **memory},
        'services_started': False, 'database_mutated': False, 'credentials_emitted': False}
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"INVENTORY_UNOBSERVED","credentials_emitted":false}')
        raise SystemExit(1) from None
