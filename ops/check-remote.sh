#!/usr/bin/env bash
# Run from the configured local Mac; no password fallback or business Run creation.
# Container capabilities use the Worker operational queue, not Canonical writes.
set -euo pipefail

exec ssh -T \
    -o BatchMode=yes \
    -o PreferredAuthentications=publickey \
    -o StrictHostKeyChecking=yes \
    -o ConnectTimeout=15 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=2 \
    hypertest-one 'bash -se' <<'REMOTE'
set -euo pipefail

date -Is
deployment_mode=legacy
if [ -e /etc/hypertest/deployment-mode ]; then
    deployment_mode=$(cat /etc/hypertest/deployment-mode)
fi
case "$deployment_mode" in
    container-v1)
        readlink -f /opt/hypertest/container-current
        for service in hypertest-container-stack hypertest-harness-bridge; do
            systemctl is-active --quiet "$service"
            printf '%s: active\n' "$service"
        done
        for service in hypertest-api hypertest-worker hypertest-web nginx; do
            state=$(systemctl is-active "$service" || true)
            if [ "$state" != inactive ]; then
                printf 'Legacy service must be inactive in container mode: %s (%s)\n' "$service" "$state" >&2
                exit 1
            fi
        done
        python3 /opt/hypertest/container-current/ops/container/readiness.py \
            --env /etc/hypertest/container/compose.env
        printf 'Remote container platform health checks passed.\n'
        exit 0
        ;;
    legacy) ;;
    *)
        printf 'Unknown HyperTest deployment mode: %s\n' "$deployment_mode" >&2
        exit 1
        ;;
esac

readlink -f /opt/hypertest/current
for service in hypertest-api hypertest-worker hypertest-web nginx; do
    systemctl is-active --quiet "$service"
    printf '%s: active\n' "$service"
done

database_state=$(docker inspect hypertest-postgres --format '{{.State.Running}} {{.State.Health.Status}}')
if [ "$database_state" != 'true healthy' ]; then
    printf 'PostgreSQL container is not healthy: %s\n' "$database_state" >&2
    exit 1
fi
database_result=$(docker exec hypertest-postgres psql -w -U hypertest -d hypertest -Atc 'SELECT 1;')
if [ "$database_result" != '1' ]; then
    printf 'PostgreSQL query failed.\n' >&2
    exit 1
fi
printf 'PostgreSQL: healthy, SELECT 1 passed\n'

python3 - <<'PY'
import json
from urllib.request import ProxyHandler, build_opener

opener = build_opener(ProxyHandler({}))


def get_json(url):
    with opener.open(url, timeout=10) as response:
        if response.status != 200:
            raise SystemExit(f'Unexpected HTTP status: {url}: {response.status}')
        return json.load(response)


for origin in ('http://127.0.0.1:8000', 'http://127.0.0.1:8080'):
    if get_json(origin + '/api/v1/health').get('status') != 'ok':
        raise SystemExit(f'API health check failed: {origin}')
print('API: healthy, direct and via nginx')

worker = get_json('http://127.0.0.1:8080/api/v1/capabilities')['worker']
if worker.get('available') is not True or worker.get('active_workers', 0) < 1:
    raise SystemExit('Worker heartbeat is unavailable')
print(f"Worker: available, active_workers={worker['active_workers']}")

for origin in ('http://127.0.0.1:3000', 'http://127.0.0.1:8080'):
    with opener.open(origin + '/', timeout=10) as response:
        if response.status != 200:
            raise SystemExit(f'Web check failed: {origin}: {response.status}')
    print(f'Web: HTTP 200 at {origin}')
PY
printf 'Remote platform health checks passed.\n'
REMOTE
