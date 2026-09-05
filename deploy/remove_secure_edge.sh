#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 2
fi

systemctl disable --now christiania-oauth2-proxy.service 2>/dev/null || true
rm -f /etc/systemd/system/christiania-oauth2-proxy.service
rm -f /usr/local/libexec/christiania/oauth2-proxy

if [[ -f /etc/caddy/Caddyfile ]] && grep -q "Managed by Christiania V1 secure edge" /etc/caddy/Caddyfile; then
  rm -f /etc/caddy/Caddyfile
fi

systemctl daemon-reload

echo "Removed Christiania-owned secure-edge service/configuration."
echo "Identity secrets and /etc/christiania/authorized_emails.txt were preserved."
