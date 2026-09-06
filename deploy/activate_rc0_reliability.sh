#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
ENV_FILE="/etc/christiania/christiania.env"

for required in systemctl sudo ss; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 4
fi

systemctl daemon-reload
systemctl enable --now christiania-supervisor.timer

sudo -u christiania \
  "${APP_DIR}/.venv/bin/python" \
  "${APP_DIR}/christiania_rc0_acceptance.py" \
  --phase full \
  --env-file "${ENV_FILE}"

echo "Christiania RC0 reliability layer activated and accepted."
