# Saxo LIVE OAuth & Health — Christiania P0

## Objective

Saxo stays **the broker of execution**, while Christiania's independent
engine searches for positive-expectancy trades. This first connector slice
does not submit, modify or cancel broker orders. The only automatic health
request is:

`GET https://gateway.saxobank.com/openapi/port/v1/users/me`

Saxo's LIVE user response verifies whether an OAuth session is functioning,
the OpenAPI market-data terms were accepted, and `StockOption` appears in
the user's `LegalAssetTypes`. None of these facts alone guarantees a
real-time OPRA option quote or an executable broker fill.

## What the System page reports

- **Saxo LIVE** — NOT CONFIGURED / LOGIN REQUIRED / CONNECTED READ ONLY /
  API PERMISSION DENIED / UNREACHABLE / RATE LIMITED / PROBE FAILED.
- **Saxo options eligibility** — `StockOption` advertised by account,
  explicitly refused, or unknown.
- **Saxo market data** — missing OpenAPI market-data terms, or
  **UNVERIFIED US STOCK AND OPRA QUOTES**. Actual market-data subscriptions
  and quote quality require a separately authenticated live quote test.
- A user-auth failure is visible in System; it does **not stop** independent
  market collection, and no stale Saxo quote is turned into a trade.
- The System probe is cached for 120 seconds, and Refresh deck clears it.
  It is read-only; it discards Name, UserKey, ClientKey, UserId and all
  other personal Saxo response fields without logging them.

## Refresh token rotation

Existing `saxo_live_auth.py` performs interactive LIVE OAuth Authorization
Code + PKCE on a trusted desktop. Saxo rotates refresh tokens; using one
invalidated token twice can break sessions. This branch wraps
`get_saxo_live_access_token()` and refresh in an interprocess file lock,
rechecks the token after acquiring that lock, and writes BOTH replacement
tokens and expiries via one fsync + atomic rename. Broker provider error
bodies are never echoed to System or logs; failures require re-login.

Token-file persistence is **owner-only file permissions (0600 on Linux)**,
not application-level ciphertext encryption; use encrypted disks/volume
facilities if at-rest encryption is needed.

## Initial setup (requires the account owner's explicit login)

1. Register/confirm a Saxo OpenAPI **LIVE** app and use the approved
   redirect URI `http://localhost:8765/christiania`. The app must have
   portfolio/user READ permissions and market-data access where applicable.
2. On the trusted Windows PC with the Saxo live app key configured,
   run `python saxo_live_auth.py`. Complete Saxo's interactive browser
   login/approval yourself. The PKCE access and rotating refresh tokens
   are saved in the local **gitignored** `.env`.
3. For Hetzner, provision **only** these Saxo entries (not the whole
   application .env) into an owner-only file outside the checkout, e.g.
   `/var/lib/christiania/secure/saxo-live.env`:
   `SAXO_LIVE_APP_KEY`, `SAXO_LIVE_CODE_VERIFIER`,
   `SAXO_LIVE_ACCESS_TOKEN`, `SAXO_LIVE_ACCESS_EXPIRES_AT`,
   `SAXO_LIVE_REFRESH_TOKEN`, `SAXO_LIVE_REFRESH_EXPIRES_AT`.
   Copy via authenticated SSH or another protected channel; avoid shell
   history, screenshots, email and chat messages containing tokens.
   Own the file/directory as the Christiania service identity,
   set file mode 0600, directory mode 0700 and ensure the filesystem
   persists across atomic application releases.
4. Configure `CHRISTIANIA_SAXO_TOKEN_STORE` **to the absolute file path**
   in the service's protected runtime environment. Do not put the tokens
   themselves in systemd unit files, git, source code or deployment logs.
   The System page can then refresh tokens from the dedicated store.
   The workstation must **not** independently keep refreshing the
   migrated old token, or it will conflict with the server's rotated token.
5. Open **Christiania → System**. The Saxo LIVE connection should report
   read-only connectivity, or a precise corrective status. If
   LOGIN REQUIRED, repeat the interactive flow and securely replace
   the server's token file while its consumer is stopped/quiesced.

No Saxo credentials or access tokens have been obtained or connected
during development of this branch. Do not assume a live session.

## Market-data validation (separate acceptance step)

A successful GET /port/v1/users/me is only an authentication test.
After authenticating, a separate real-time Saxo quote test must verify:
- stock and OPRA options subscription, and accepted OpenAPI data terms;
- no `NoAccess`, `Indicative`, `DelayedByMinutes > 0` or stale price;
- genuine bid and ask, size, timestamps, exact option contract UIC,
  multipliers and source-to-option clock alignment;
- Saxo's estimated charges, EUR/USD FX and realistic package fill/slippage
  for €500 of experimental defined-risk capital.

Until then, the **market-data** health row remains UNVERIFIED, and no
positive-EV broker recommendation or order authority is implied.

## Release safety

This branch is stacked above the multi-strategy PRs #168–#172 and does
not change schema. **No production deployment** until all earlier PRs
have green exact-SHA CI, v38 migration backup/verified rollback,
service readiness, resource/performance gates and atomic activation.
Presently the latest verified production backup recovery point and
supervisor readiness remain blocked.


## Headless session maintenance (new: no browser session required for refresh)

A new **opt-in** one-shot service and timer are included:

- `deploy/systemd/christiania-saxo-session.service`
- `deploy/systemd/christiania-saxo-session.timer`
- `python -m src.operations.saxo_session_keeper_v1`

The timer has `OnUnitActiveSec=5min`. Its service checks whether the
access token is still usable and otherwise rotates the access and
refresh tokens under the same cross-process store lock. It does not
call a stock/options quote API or any order endpoint; the only
potential network request is Saxo's OAuth refresh-token exchange.
If refresh credentials have expired or been revoked, the service
reports LOGIN_REQUIRED and exits nonzero rather than looping blindly.

**The timer is intentionally NOT enabled by any existing deployment
script.** It must only be installed and enabled after the user's
fresh initial OAuth login, secure server token-store provisioning,
verified release/backup recovery state, and explicit release
acceptance. A user who never configures Saxo should not have a
failed unrelated systemd timer.

The application systemd sandbox also gets a *narrow optional*
write allowance for `/var/lib/christiania/secure`; it preserves
ProtectSystem=strict, NoNewPrivileges and the existing read/write
data allowance. This permits the System page and the keeper to
rotate the same credentials without conflicts.

## Secure one-time transfer helper

After a **fresh** OAuth login, the user can explicitly export only
the six Saxo configuration entries, never other contents of the
Christiania `.env`, using:

`python -m src.operations.saxo_credential_export_v1 --output <ABSOLUTE_PATH_OUTSIDE_REPO>`

The export fails closed if the refresh token has already expired,
the target exists, or the path is relative or within the Git checkout.
On Linux it creates mode 0600. The helper prints no tokens.

Transfer the resulting file to Hetzner through authenticated SSH,
install it as service-owned mode 0600 under
`/var/lib/christiania/secure/saxo-live.env` in an owner-only
directory, verify ownership and permissions, and securely remove
the temporary transfer copies. Avoid pasting credentials into
terminal history, chats, screenshots or GitHub.

Only **one server-side token store** should actively rotate the
credentials. Re-authenticating elsewhere invalidates the old
refresh-token lineage and may require safely reprovisioning the
server store.

## Historical Saxo credentials observed during development

The authorized desktop's existing local `.env` contains the
Saxo LIVE application key and PKCE/token settings, but **both
access and refresh tokens were expired on inspection**. No secrets
were displayed or transmitted. A new interactive Saxo LIVE login
will therefore be required. It has not been performed for the user.

This code and the 5-minute timer **do not guarantee permanent login**:
Saxo may revoke a session, enforce re-authentication or change
application entitlements; the health check must report LOGIN_REQUIRED.
