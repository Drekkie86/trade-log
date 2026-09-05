#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
ENV_DIR="/etc/christiania"
EDGE_ENV="${ENV_DIR}/secure-edge.env"
CADDY_DIR="/etc/caddy"
CADDYFILE="${CADDY_DIR}/Caddyfile"
OAUTH_LINK="/usr/local/libexec/christiania/oauth2-proxy"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for required in caddy oauth2-proxy systemctl install grep mkdir ln python3; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

if [[ ! -f "${ENV_DIR}/christiania.env" ]]; then
  echo "Missing ${ENV_DIR}/christiania.env" >&2
  exit 4
fi

if [[ ! -f "${EDGE_ENV}" ]]; then
  install -m 0640 -o root -g christiania "${SOURCE_DIR}/secure-edge.env.example" "${EDGE_ENV}"
  echo "Created ${EDGE_ENV}; configure its OIDC values before enabling the edge." >&2
fi

if [[ -f "${CADDYFILE}" ]] && ! grep -q "Managed by Christiania V1 secure edge" "${CADDYFILE}"; then
  echo "Refusing to overwrite an unmanaged ${CADDYFILE}." >&2
  exit 5
fi

PUBLIC_HOST="$(cd "${APP_DIR}" && "${APP_DIR}/.venv/bin/python" - "${EDGE_ENV}" <<'PYHOST'
import sys
from src.config import read_env_file
from src.operations.secure_edge import inspect_secure_edge_configuration
import os
values = read_env_file(sys.argv[1])
for key, value in values.items():
    os.environ.setdefault(key, value)
status = inspect_secure_edge_configuration()
if not status.public_host:
    raise SystemExit(2)
print(status.public_host)
PYHOST
)" || {
  echo "Secure-edge public-host configuration is invalid." >&2
  exit 6
}

install -d -m 0755 "${CADDY_DIR}" "/usr/local/libexec/christiania"

cd "${APP_DIR}"
"${APP_DIR}/.venv/bin/python" - "${SOURCE_DIR}/secure-edge/Caddyfile.template" "${CADDYFILE}" "${PUBLIC_HOST}" <<'PYCADDY'
import sys
from pathlib import Path
from src.operations.secure_edge import render_caddyfile
source = Path(sys.argv[1]).read_text(encoding="utf-8")
rendered = render_caddyfile(source, sys.argv[3])
Path(sys.argv[2]).write_text(rendered, encoding="utf-8")
PYCADDY
chmod 0644 "${CADDYFILE}"

if [[ ! -f "${ENV_DIR}/authorized_emails.txt" ]]; then
  install -m 0640 -o root -g christiania "${SOURCE_DIR}/secure-edge/authorized_emails.example" "${ENV_DIR}/authorized_emails.txt"
  echo "Created ${ENV_DIR}/authorized_emails.txt; replace the example identity before enabling the edge." >&2
fi

OAUTH_BIN="$(command -v oauth2-proxy)"
ln -sfn "${OAUTH_BIN}" "${OAUTH_LINK}"
install -m 0644 "${APP_DIR}/deploy/systemd/christiania-oauth2-proxy.service" "/etc/systemd/system/christiania-oauth2-proxy.service"

systemctl daemon-reload

echo "Installed Christiania secure-edge configuration."
echo "Nothing was enabled or started automatically."
echo "Next: configure DNS/OIDC/secrets/authorized_emails, then run:"
echo "  sudo -u christiania ${APP_DIR}/.venv/bin/python ${APP_DIR}/christiania_secure_edge_preflight.py --env-file ${EDGE_ENV}"
