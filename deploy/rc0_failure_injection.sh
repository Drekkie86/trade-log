#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

if [[ "${1:-}" != "--i-understand-this-stops-services" ]]; then
  echo "Refusing failure injection without explicit acknowledgement:" >&2
  echo "  $0 --i-understand-this-stops-services" >&2
  exit 3
fi

APP_DIR="/opt/christiania"
ENV_FILE="/etc/christiania/christiania.env"

echo "[1/3] Restarting Christiania app and proving recovery..."
systemctl restart christiania-app.service
sleep 5
systemctl is-active --quiet christiania-app.service

echo "[2/3] Restarting research daemon and proving recovery..."
systemctl restart christiania-daemon.service
sleep 20
systemctl is-active --quiet christiania-daemon.service

echo "[3/3] Running full post-disturbance acceptance..."
sudo -u christiania \
  "${APP_DIR}/.venv/bin/python" \
  "${APP_DIR}/christiania_rc0_acceptance.py" \
  --phase full \
  --env-file "${ENV_FILE}"

echo "SAFE RC0 FAILURE-INJECTION REHEARSAL PASSED."
echo "This script never corrupts or edits the live database."
