# Christiania V1 Secure Web Edge

## Design

Public traffic terminates at Caddy, which provides HTTPS. Caddy proxies only to oauth2-proxy on `127.0.0.1:4180`. oauth2-proxy performs generic OIDC login/authorization and proxies authenticated requests to Streamlit on `127.0.0.1:8501`.

No Christiania password table exists.

## Secret separation

Research/provider credentials remain in `/etc/christiania/christiania.env`. The public edge receives a separate `/etc/christiania/secure-edge.env` containing only OIDC/session configuration. Caddy itself receives no Christiania secret environment file; the installer renders only the validated hostname into its Caddyfile.

## Required deployment settings

- `CHRISTIANIA_PUBLIC_HOST`
- `OAUTH2_PROXY_REDIRECT_URL=https://<host>/oauth2/callback`
- `OAUTH2_PROXY_OIDC_ISSUER_URL` (HTTPS)
- `OAUTH2_PROXY_CLIENT_ID`
- `OAUTH2_PROXY_CLIENT_SECRET` (secret)
- `OAUTH2_PROXY_COOKIE_SECRET` (secret; URL-safe base64 key)
- `OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/etc/christiania/authorized_emails.txt`

The authorization file contains individual allowed email addresses. Wildcards are rejected by Christiania's preflight.

## Deployment flow

1. Install Caddy and oauth2-proxy from trusted platform/upstream packages.
2. Point public DNS at the VM.
3. Register an OIDC web application with callback `https://<host>/oauth2/callback`.
4. Populate `/etc/christiania/secure-edge.env` and the explicit email allowlist.
5. Run `deploy/install_secure_edge.sh` as root. It does not start services.
6. Run `christiania_secure_edge_preflight.py --env-file /etc/christiania/christiania.env`.
7. Enable/start the application, oauth2-proxy and Caddy deliberately.
8. Verify an unauthenticated browser request reaches the identity login flow and cannot reach Streamlit directly.

## Network policy

Only public TCP 80/443 (and separately managed SSH administration) should be reachable from the internet. Ports 8501, 4180 and Theta's local API port must never be internet-exposed.

## Session policy

The auth gateway uses Secure/HttpOnly/Lax cookies, a `__Host-` cookie name, an 8-hour expiry and one-hour refresh. Caddy adds HSTS and defensive response headers. Authentication/access logs remain in systemd/journald/Caddy logs; secrets are not written into Christiania audit exports.
