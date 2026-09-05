#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
STATE_DIR="/var/lib/christiania"
ENV_DIR="/etc/christiania"
SERVICE_USER="christiania"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for required in python3 rsync systemctl useradd install; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o root -g "${SERVICE_USER}" "${APP_DIR}" "${APP_DIR}/vendor"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STATE_DIR}/data" "${STATE_DIR}/backups" "${STATE_DIR}/audit"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${ENV_DIR}"

rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'vendor/' --exclude '*.db*' --exclude '.env' "${SOURCE_DIR}/" "${APP_DIR}/"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
chown -R root:"${SERVICE_USER}" "${APP_DIR}"
chmod -R g+rX,o-rwx "${APP_DIR}"

if [[ ! -f "${ENV_DIR}/christiania.env" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${APP_DIR}/deploy/christiania.env.example" "${ENV_DIR}/christiania.env"
  echo "Created ${ENV_DIR}/christiania.env. Populate secrets and Theta JAR path before enabling services." >&2
fi

for unit in "${APP_DIR}"/deploy/systemd/christiania-*.service "${APP_DIR}"/deploy/systemd/christiania-*.timer; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done

systemctl daemon-reload

echo "Installed Christiania runtime files."
echo "Next: populate ${ENV_DIR}/christiania.env, place ThetaTerminalv3.jar, copy/restore the database, then run:"
echo "  sudo -u ${SERVICE_USER} ${APP_DIR}/.venv/bin/python ${APP_DIR}/christiania_deploy_preflight.py --require-theta-live"
echo "No services were enabled automatically."
