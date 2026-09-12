#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
ENV_FILE="/etc/christiania/christiania.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}." >&2
  exit 3
fi

echo "Activating Christiania core runtime..."
bash "${APP_DIR}/deploy/activate_one_vm.sh"

echo "Activating unattended reliability baseline..."
bash "${APP_DIR}/deploy/activate_reliability_baseline.sh"

echo "Enabling V1 operational-readiness gate..."
systemctl enable --now christiania-v1-readiness.timer

echo "Refreshing supervisor evidence..."
systemctl start christiania-supervisor.service

echo "Evaluating fail-closed V1 operational independence..."
systemctl start christiania-v1-readiness.service

echo
echo "Christiania V1 operational independence gate PASSED."
cat /var/lib/christiania/audit/v1_operational_readiness.json
