#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
ENV_FILE="/etc/christiania/christiania.env"

for required in systemctl sudo; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 4
fi

sudo -u christiania "${APP_DIR}/.venv/bin/python" "${APP_DIR}/christiania_deploy_preflight.py" \
  --env-file "${ENV_FILE}"

systemctl enable --now christiania-theta.service
sudo -u christiania "${APP_DIR}/.venv/bin/python" "${APP_DIR}/run_theta_probe.py" --wait-seconds 180

systemctl enable --now christiania-daemon.service christiania-app.service

for timer in \
  christiania-backup.timer \
  christiania-health.timer \
  christiania-audit.timer \
  christiania-restore-drill.timer \
  christiania-burn-in.timer; do
  systemctl enable --now "${timer}"
done

sudo -u christiania bash -c '
  set -a
  . /etc/christiania/christiania.env
  set +a

  exec /opt/christiania/.venv/bin/python \
    /opt/christiania/christiania_health.py \
    --strict-daemon --strict-theta --strict-backup
'

echo "Christiania core runtime activated. Secure web edge remains a separate activation gate."
