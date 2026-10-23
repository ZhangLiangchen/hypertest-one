#!/bin/bash
set -euo pipefail
umask 077
exec 9>/run/powercontext-maintenance.lock
flock -n 9 || exit 75

backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="/var/backups/powercontext/${backup_stamp}"
install -d -m 0700 "$backup_dir"
service_was_active=false
if systemctl is-active --quiet powercontext.service; then
  service_was_active=true
fi
restore_service() {
  if "$service_was_active"; then
    systemctl start powercontext.service
  fi
}
trap restore_service EXIT

# Stop this independent service so all SQLite/WAL/scheduler state is consistent.
# Do not copy a running database or stop Xray/HyperTest/SSH/the TLS proxy.
systemctl stop powercontext.service
tar --one-file-system --numeric-owner -czf "$backup_dir/home.tar.gz" -C /var/lib powercontext
tar --one-file-system --numeric-owner -czf "$backup_dir/config.tar.gz" \
  /etc/powercontext \
  /etc/systemd/system/powercontext.service \
  /etc/systemd/system/powercontext-proxy.service \
  /etc/systemd/system/powercontext-cert-renew.service \
  /etc/systemd/system/powercontext-cert-renew.timer \
  /etc/systemd/system/powercontext-backup.service \
  /etc/systemd/system/powercontext-backup.timer \
  /opt/powercontext/releases/1.4.0/provenance.json \
  /opt/powercontext/releases/1.4.0/requirements.in \
  /opt/powercontext/releases/1.4.0/requirements.lock \
  /opt/powercontext/certbot/5.8.0/requirements.in \
  /opt/powercontext/certbot/5.8.0/requirements.lock \
  /opt/powercontext/deploy-certificate.py \
  /opt/powercontext/backup.sh
(
  cd "$backup_dir"
  sha256sum home.tar.gz config.tar.gz > SHA256SUMS
)
restore_service
trap - EXIT
printf 'PowerContext backup: %s\n' "$backup_dir"
