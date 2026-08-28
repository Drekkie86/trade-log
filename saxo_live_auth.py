from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.config import get_required_setting, set_local_settings


APP_KEY = get_required_setting("SAXO_LIVE_APP_KEY")

REDIRECT_URI = "http://localhost:8765/christiania"

AUTHORIZE_URL = "https://live.logonvalidation.net/authorize"
TOKEN_URL = "https://live.logonvalidation.net/token"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return (
        value.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def base64url(data: bytes) -> str:
    return (
        base64.urlsafe_b64encode(data)
        .rstrip(b"=")
        .decode("ascii")
    )


code_verifier = base64url(
    secrets.token_bytes(64)
)

code_challenge = base64url(
    hashlib.sha256(
        code_verifier.encode("ascii")
    ).digest()
)

state = secrets.token_urlsafe(32)

authorization_code = None
returned_state = None
callback_error = None
callback_error_description = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global authorization_code
        global returned_state
        global callback_error
        global callback_error_description

        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/christiania":
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(
            parsed.query
        )

        authorization_code = (
            params.get("code", [None])[0]
        )

        returned_state = (
            params.get("state", [None])[0]
        )

        callback_error = (
            params.get("error", [None])[0]
        )

        callback_error_description = (
            params.get(
                "error_description",
                [None],
            )[0]
        )

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )
        self.end_headers()

        if callback_error:
            html = """
            <html>
            <body>
            <h2>Christiania authentication failed.</h2>
            <p>You can close this tab.</p>
            </body>
            </html>
            """
        else:
            html = """
            <html>
            <body>
            <h2>Christiania authenticated with Saxo LIVE.</h2>
            <p>You can close this tab and return to PowerShell.</p>
            </body>
            </html>
            """

        self.wfile.write(
            html.encode("utf-8")
        )

    def log_message(self, format, *args):
        pass


query = urllib.parse.urlencode(
    {
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
)

authorization_url = (
    f"{AUTHORIZE_URL}?{query}"
)


print()
print("Christiania - Saxo LIVE authentication")
print("--------------------------------------")
print()
print("Opening Saxo LIVE login...")
print()


server = HTTPServer(
    ("localhost", 8765),
    CallbackHandler,
)

server_thread = threading.Thread(
    target=server.handle_request
)

server_thread.start()

webbrowser.open(authorization_url)

server_thread.join()
server.server_close()


if callback_error:
    detail = (
        f": {callback_error_description}"
        if callback_error_description
        else ""
    )

    raise RuntimeError(
        f"Saxo authentication failed: "
        f"{callback_error}{detail}"
    )

if not authorization_code:
    raise RuntimeError(
        "Saxo returned no authorization code."
    )

if returned_state != state:
    raise RuntimeError(
        "OAuth state mismatch. "
        "Authentication aborted."
    )


body = urllib.parse.urlencode(
    {
        "grant_type": "authorization_code",
        "client_id": APP_KEY,
        "code": authorization_code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
).encode("utf-8")


request = urllib.request.Request(
    TOKEN_URL,
    data=body,
    method="POST",
    headers={
        "Content-Type":
            "application/x-www-form-urlencoded",
        "Accept":
            "application/json",
    },
)


with urllib.request.urlopen(
    request,
    timeout=30,
) as response:

    payload = json.loads(
        response.read().decode("utf-8")
    )


access_token = payload.get(
    "access_token"
)

refresh_token = payload.get(
    "refresh_token"
)

expires_in = int(
    payload.get("expires_in") or 0
)

refresh_expires_in = int(
    payload.get(
        "refresh_token_expires_in"
    )
    or 0
)


if not access_token:
    raise RuntimeError(
        "Saxo returned no access token."
    )

if not refresh_token:
    raise RuntimeError(
        "Saxo returned no refresh token."
    )


now = utc_now()

access_expires_at = (
    now + timedelta(seconds=expires_in)
)

refresh_expires_at = (
    now
    + timedelta(
        seconds=refresh_expires_in
    )
)


set_local_settings(
    {
        "SAXO_LIVE_ACCESS_TOKEN":
            access_token,

        "SAXO_LIVE_ACCESS_EXPIRES_AT":
            iso_utc(access_expires_at),

        "SAXO_LIVE_REFRESH_TOKEN":
            refresh_token,

        "SAXO_LIVE_REFRESH_EXPIRES_AT":
            iso_utc(refresh_expires_at),

        "SAXO_LIVE_CODE_VERIFIER":
            code_verifier,
    }
)


print()
print("Authentication successful.")
print()
print(
    f"Access token lifetime: "
    f"{expires_in} seconds"
)
print(
    f"Refresh token lifetime: "
    f"{refresh_expires_in} seconds"
)
print()
print(
    "Access token, refresh token, expiry times "
    "and PKCE verifier were saved locally."
)
print()
print(
    "Christiania can now refresh the access "
    "token without another login while the "
    "refresh token remains valid."
)