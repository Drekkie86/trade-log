#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

systemctl daemon-reload
systemctl enable --now christiania-theta-watchdog.timer
systemctl enable --now christiania-theta-refresh.timer
systemctl enable --now christiania-supervisor.timer
systemctl start christiania-supervisor.service

echo "Christiania reliability baseline activated."
echo
systemctl is-active christiania-theta.service christiania-daemon.service christiania-app.service christiania-supervisor.timer christiania-theta-watchdog.timer christiania-theta-refresh.timer
echo
systemctl list-timers --all | grep -E 'christiania-(supervisor|theta-watchdog|theta-refresh)'
