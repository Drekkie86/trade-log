#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

APP_DIR="/opt/christiania"
EDGE_ENV="/etc/christiania/secure-edge.env"

for required in systemctl sudo caddy; do
  if ! command -v "${required}" >/dev/null 2>&1; then
    echo "Required command not found: ${required}" >&2
    exit 3
  fi
done

sudo -u christiania "${APP_DIR}/.venv/bin/python" "${APP_DIR}/christiania_secure_edge_preflight.py" \
  --env-file "${EDGE_ENV}"

caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now christiania-oauth2-proxy.service
systemctl reload caddy.service || systemctl restart caddy.service
systemctl is-active --quiet christiania-oauth2-proxy.service
systemctl is-active --quiet caddy.service

echo "Christiania secure web edge activated. Verify external HTTPS/OIDC login before RC acceptance."
