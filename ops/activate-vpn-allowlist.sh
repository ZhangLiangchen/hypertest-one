#!/usr/bin/env bash
# Activate only after review, confirmed VPN source, and a tested HTTP-compatible Web release.
# Upload ops/nginx/hypertest-vpn-allowlist.conf; HYPERTEST_ACCESS_CANDIDATE is its remote path.
# Set the explicit activation token, reviewed application SHA and uploaded config SHA256 below.
set -euo pipefail
umask 077
[ "${HYPERTEST_ALLOWLIST_ACTIVATE:-}" = '45.76.149.233:8080' ] || { echo 'Explicit reviewed activation token is required.' >&2; exit 2; }
: "${HYPERTEST_ACCESS_EXPECTED_COMMIT:?Set the reviewed application SHA}"
: "${HYPERTEST_ACCESS_CANDIDATE:?Set the uploaded reviewed ops/nginx/hypertest-vpn-allowlist.conf path}"
: "${HYPERTEST_ACCESS_CONFIG_SHA256:?Set its reviewed SHA256}"
exec 9>/run/lock/hypertest-maintenance.lock
flock -n 9
available=/etc/nginx/sites-available/hypertest-vpn-allowlist.conf
enabled=/etc/nginx/sites-enabled/hypertest-vpn-allowlist.conf
[ ! -e "$enabled" ] && [ ! -L "$enabled" ]
initial_available=0
if [ -e "$available" ] || [ -L "$available" ]; then
    [ -f "$available" ] && [ ! -L "$available" ]
    printf '%s  %s\n' "$HYPERTEST_ACCESS_CONFIG_SHA256" "$available" | sha256sum -c -
    initial_available=1
fi
release=$(readlink -f /opt/hypertest/current)
[ "$(git -c safe.directory="$release" -C "$release" rev-parse HEAD)" = "$HYPERTEST_ACCESS_EXPECTED_COMMIT" ]
printf '%s  %s\n' "$HYPERTEST_ACCESS_CONFIG_SHA256" "$HYPERTEST_ACCESS_CANDIDATE" | sha256sum -c -
[ "$(sha256sum /etc/nginx/sites-enabled/hypertest.conf | cut -d' ' -f1)" = b847ea3183367bdfac17869ebabee7672ae7a2065a779fbdce90642c1498a8e5 ]
python3 - <<'PY'
import json,re,subprocess
cmd=lambda *a:subprocess.check_output(a,text=True)
ufw=cmd('ufw','status','verbose');rules=[x for x in ufw.splitlines() if 'ALLOW' in x]
assert 'Status: active' in ufw and 'deny (incoming)' in ufw and len(rules)==2 and all(x.startswith('22/tcp ') for x in rules)
conf=subprocess.run(['nginx','-T'],text=True,capture_output=True,check=True).stdout
active='\n'.join(x for x in conf.splitlines() if x.strip() and not x.lstrip().startswith('#'))
assert not re.search(r'\b(?:set_real_ip_from|real_ip_header|real_ip_recursive|proxy_protocol)\b',active)
assert int(cmd('docker','exec','hypertest-postgres','psql','-X','-U','hypertest','-d','hypertest','-Atc',"SELECT count(*) FROM durable_jobs WHERE status IN ('QUEUED','RUNNING','CANCEL_REQUESTED')"))==0
addresses=json.loads(cmd('ip','-j','-4','addr','show','enp1s0'))
assert any(a.get('local')=='155.138.206.106' for i in addresses for a in i.get('addr_info',[]))
PY
backup="/var/backups/hypertest-access/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup"
cp -a /etc/nginx/sites-available/hypertest.conf "$backup/loopback-nginx.conf"
cp -a /etc/ufw/user.rules /etc/ufw/user6.rules "$backup/"
ufw status verbose > "$backup/ufw-before.txt"
ss -H -lnt > "$backup/listeners-before.txt"
rule_added=0
reloaded=0
rollback() {
    status=$?
    if [ "$status" != 0 ]; then
        if [ "$rule_added" = 1 ]; then ufw --force delete allow in on enp1s0 proto tcp from 45.76.149.233/32 to 155.138.206.106 port 8080 || true; fi
        rm -f "$enabled"
        if [ "$initial_available" = 0 ]; then rm -f "$available"; fi
        if [ "$reloaded" = 1 ]; then nginx -t && systemctl reload nginx || true; fi
        echo 'Allowlist activation failed; new rule/site withdrawn. SSH22 and app/data untouched.' >&2
    fi
}
trap rollback EXIT
install -o root -g root -m 0644 "$HYPERTEST_ACCESS_CANDIDATE" "$available"
ln -s "$available" "$enabled"
nginx -t
# Only the narrow IPv4 rule is added. At this point nginx still has no public listener.
# Mark the attempt before UFW mutation so a partial failure also deletes this exact rule.
rule_added=1
ufw allow in on enp1s0 proto tcp from 45.76.149.233/32 to 155.138.206.106 port 8080 comment 'HyperTest VPN Web allowlist'
reloaded=1
systemctl reload nginx
python3 - <<'PY'
import json,subprocess,urllib.error,urllib.request
listeners=[x.split()[3] for x in subprocess.check_output(['ss','-H','-lnt'],text=True).splitlines()]
assert '155.138.206.106:8080' in listeners and '127.0.0.1:8080' in listeners
assert all(a not in ('0.0.0.0:8080','[::]:8080','*:8080') for a in listeners)
for port in (8000,3000,5432):assert '127.0.0.1:'+str(port) in listeners
with urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health',timeout=10) as r:assert json.load(r)['status']=='ok'
# Host self-request bypasses the external firewall but must still fail the peer ACL.
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for headers in ({},{'X-Forwarded-For':'45.76.149.233'},{'X-Real-IP':'45.76.149.233'}):
 try:opener.open(urllib.request.Request('http://155.138.206.106:8080/api/v1/health',headers=headers),timeout=5)
 except urllib.error.HTTPError as e:assert e.code==403
 else:raise AssertionError('Nginx allowed a non-allowlisted TCP peer')
PY
ufw status verbose > "$backup/ufw-after.txt"
ss -H -lnt > "$backup/listeners-after.txt"
printf '%s\n' "$HYPERTEST_ACCESS_EXPECTED_COMMIT" > "$backup/application-sha.txt"
printf '%s\n' "$HYPERTEST_ACCESS_CONFIG_SHA256" > "$backup/public-config-sha256.txt"
trap - EXIT
printf 'Allowlist activated; network configuration snapshot: %s. External allow/non-allow protocol tests remain required.\n' "$backup"
