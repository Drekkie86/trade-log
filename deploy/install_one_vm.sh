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
RUNTIME_GROUP="christiania-runtime"
UI_ENV_ROOT="/etc/christiania-ui"
UI_ENV_FILE="${UI_ENV_ROOT}/christiania.env"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for required in python3 rsync systemctl useradd usermod groupadd getent grep sort install git; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

bash "${SOURCE_DIR}/deploy/provision_runtime_identities.sh"

install -d -m 0750 -o root -g "${RUNTIME_GROUP}" "${APP_DIR}"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${APP_DIR}/vendor"
install -d -m 0750 -o root -g "${SERVICE_USER}" "${ENV_DIR}"

DEPLOYED_COMMIT="$(git -C "${SOURCE_DIR}" rev-parse HEAD 2>/dev/null || true)"
if [[ ! "${DEPLOYED_COMMIT}" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Cannot determine a full 40-character source commit for deployment." >&2
  exit 4
fi
DEPLOYED_COMMIT="${DEPLOYED_COMMIT,,}"

rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'vendor/' --exclude '*.db*' --exclude '.env' "${SOURCE_DIR}/" "${APP_DIR}/"
printf '%s\n' "${DEPLOYED_COMMIT}" > "${APP_DIR}/DEPLOYED_COMMIT"
PYTHON_VERSION="$(
  python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
)"
if [[ "${PYTHON_VERSION}" != "3.13" ]]; then
  echo "Christiania requires Python 3.13; found ${PYTHON_VERSION}." >&2
  exit 5
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-compile \
  --no-deps \
  -r "${APP_DIR}/requirements-lock-linux-py313.txt"
"${APP_DIR}/.venv/bin/python" -m pip check

LOCK_ACTUAL="$(
  "${APP_DIR}/.venv/bin/python" -m pip freeze \
    | LC_ALL=C sort -f
)"
LOCK_EXPECTED="$(
  grep -vE '^[[:space:]]*(#|$)' \
    "${APP_DIR}/requirements-lock-linux-py313.txt" \
    | LC_ALL=C sort -f
)"
if [[ "${LOCK_ACTUAL}" != "${LOCK_EXPECTED}" ]]; then
  echo "Installed Python runtime does not match requirements-lock-linux-py313.txt." >&2
  exit 6
fi

chown -R root:"${RUNTIME_GROUP}" "${APP_DIR}"
chmod -R g+rX,o-rwx "${APP_DIR}"
if [[ -d "${APP_DIR}/vendor" ]]; then
  chown -R root:"${SERVICE_USER}" "${APP_DIR}/vendor"
  chmod -R g+rX,o-rwx "${APP_DIR}/vendor"
fi

if [[ ! -f "${ENV_DIR}/christiania.env" ]]; then
  install -m 0640 -o root -g "${SERVICE_USER}" "${APP_DIR}/deploy/christiania.env.example" "${ENV_DIR}/christiania.env"
  echo "Created ${ENV_DIR}/christiania.env. Populate secrets and Theta JAR path before enabling services." >&2
fi

UI_ENV_TEMP="$(mktemp)"
"${APP_DIR}/.venv/bin/python" \
  "${APP_DIR}/christiania_ui_env.py" \
  --source "${ENV_DIR}/christiania.env" \
  --output "${UI_ENV_TEMP}"
install \
  -m 0640 \
  -o root \
  -g "${RUNTIME_GROUP}" \
  "${UI_ENV_TEMP}" \
  "${UI_ENV_FILE}"
rm -f "${UI_ENV_TEMP}"

for unit in "${APP_DIR}"/deploy/systemd/christiania-*.service "${APP_DIR}"/deploy/systemd/christiania-*.timer; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done

systemctl daemon-reload

echo "Installed Christiania runtime files."
echo "Next: populate ${ENV_DIR}/christiania.env, place ThetaTerminalv3.jar, copy/restore the database, then run:"
echo "  sudo -u ${SERVICE_USER} ${APP_DIR}/.venv/bin/python ${APP_DIR}/christiania_deploy_preflight.py --env-file ${ENV_DIR}/christiania.env --require-theta-live"
echo "No services were enabled automatically."
echo "After preflight, activate baseline unattended reliability with:"
echo "  sudo bash ${APP_DIR}/deploy/activate_reliability_baseline.sh"
