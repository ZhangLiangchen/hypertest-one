#!/usr/bin/env bash
# Roll back only this managed VPN allowlist rule/site after review.
# Set the explicit rollback token and the SHA256 of the activated
# ops/nginx/hypertest-vpn-allowlist.conf. SSH22 and the loopback site are preserved.
set -euo pipefail
[ "${HYPERTEST_ALLOWLIST_ROLLBACK:-}" = '45.76.149.233:8080' ] || { echo 'Rollback not enabled.' >&2; exit 2; }
: "${HYPERTEST_ACCESS_CONFIG_SHA256:?Set the activated reviewed config SHA256}"
exec 9>/run/lock/hypertest-maintenance.lock
flock -n 9
available=/etc/nginx/sites-available/hypertest-vpn-allowlist.conf
enabled=/etc/nginx/sites-enabled/hypertest-vpn-allowlist.conf
[ -f "$available" ] && [ ! -L "$available" ]
if [ -e "$enabled" ] || [ -L "$enabled" ]; then
    [ -L "$enabled" ] && [ "$(readlink -f "$enabled")" = "$available" ]
fi
printf '%s  %s\n' "$HYPERTEST_ACCESS_CONFIG_SHA256" "$available" | sha256sum -c -
# Remove only our IPv4 application rule; SSH22 and all prior firewall rules remain.
if ! ufw --force delete allow in on enp1s0 proto tcp from 45.76.149.233/32 to 155.138.206.106 port 8080; then
    # An already-deleted rule is a valid retry state; any remaining app allow rule is not.
    python3 - <<'RULECHECK'
import subprocess
ufw=subprocess.check_output(['ufw','status','verbose'],text=True)
assert not any('8080' in line for line in ufw.splitlines() if 'ALLOW' in line)
RULECHECK
fi
rm -f "$enabled"
nginx -t
systemctl reload nginx
# Refuse to claim a completed rollback unless the public socket/rule is gone.
python3 - <<'CHECK'
import json,subprocess,urllib.request
listeners=[x.split()[3] for x in subprocess.check_output(['ss','-H','-lnt'],text=True).splitlines()]
assert '127.0.0.1:8080' in listeners
assert all(a not in ('155.138.206.106:8080','0.0.0.0:8080','[::]:8080','*:8080') for a in listeners)
for port in (8000,3000,5432):assert '127.0.0.1:'+str(port) in listeners
ufw=subprocess.check_output(['ufw','status','verbose'],text=True)
assert 'Status: active' in ufw and 'deny (incoming)' in ufw
assert not any('8080' in line for line in ufw.splitlines() if 'ALLOW' in line)
assert sum('ALLOW' in line and line.startswith('22/tcp ') for line in ufw.splitlines())==2
with urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health',timeout=10) as r:assert json.load(r)['status']=='ok'
CHECK
# Keep the now-disabled available config and snapshot as recovery evidence.
ss -H -lnt
ufw status verbose
printf 'Network rollback verified: public8080 removed; SSH22 and loopback health preserved.\n'
