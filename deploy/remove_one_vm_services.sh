#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

units=(
  christiania-app.service christiania-daemon.service christiania-theta.service
  christiania-backup.service christiania-backup.timer christiania-health.service christiania-health.timer
  christiania-audit.service christiania-audit.timer christiania-restore-drill.service christiania-restore-drill.timer
)

for unit in "${units[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$unit"
done
systemctl daemon-reload

echo "Christiania systemd units removed. Application data, backups, audit exports, environment file and Theta JAR were intentionally left untouched."
