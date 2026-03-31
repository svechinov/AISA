#!/usr/bin/env python3
"""
Fetch GOOGLE_REFRESH_TOKEN using GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from .env.

OAuth always needs a human to sign in once — this script only automates the localhost redirect
(so you do not need OAuth Playground or the web UI).

0) In the same GCP project as the OAuth client: APIs & Services → Library → enable Gmail API
   (otherwise tokens work but Gmail REST calls return 403).

1) In Google Cloud Console → Credentials → your Web OAuth client → Authorized redirect URIs, add
   EXACTLY (same port as below, default 8765):

     http://127.0.0.1:8765/oauth2/callback

2) From the backend package directory:

     cd backend
     python scripts/fetch_google_refresh_token.py

3) Complete login in the browser. On success the refresh token is printed and, if allowed,
   merged into your .env file(s) the same way as the Gmail Connect flow.

Options:
  --port 8765     (must match the URI registered in Google Cloud)
  --no-browser    print the URL only
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# package root: backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.env_bootstrap import (  # noqa: E402
    bootstrap_env_write_allowed,
    load_env_from_file,
    upsert_env_files_everywhere,
)
from app.services.gmail_oauth import (  # noqa: E402
    GmailOAuthError,
    build_authorization_url,
    exchange_code_for_tokens,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Obtain GOOGLE_REFRESH_TOKEN via localhost OAuth callback.")
    parser.add_argument("--port", type=int, default=8765, help="Local callback port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = parser.parse_args()

    load_env_from_file()
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        print(
            "error: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env (or environment), then retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    redirect_uri = f"http://127.0.0.1:{args.port}/oauth2/callback"
    state = secrets.token_urlsafe(24)
    result: dict[str, str | None] = {"code": None, "error": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/oauth2/callback":
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("state", [None])[0] != state:
                result["error"] = "invalid state"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<p>Invalid state. Close this tab and run the script again.</p>")
                return
            err = (qs.get("error") or [None])[0]
            if err:
                desc = (qs.get("error_description") or [""])[0]
                result["error"] = f"{err}: {desc}"
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    f"<p>Google returned an error: {err}</p><p>{desc}</p>".encode(),
                )
                return
            code = (qs.get("code") or [None])[0]
            if not code:
                result["error"] = "missing code"
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<p>OK - you can close this tab and return to the terminal.</p>",
            )

    server = HTTPServer(("127.0.0.1", args.port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth_url = build_authorization_url(client_id=cid, redirect_uri=redirect_uri, state=state)
    print()
    print("Register this redirect URI on your OAuth Web client (if not already):")
    print(f"  {redirect_uri}")
    print()
    print("Opening authorization URL...")
    print(auth_url)
    print()
    if not args.no_browser:
        webbrowser.open(auth_url)

    deadline = time.time() + 300.0
    while time.time() < deadline and result["code"] is None and result["error"] is None:
        time.sleep(0.2)

    server.shutdown()
    server.server_close()

    if result["error"]:
        print(f"error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    if not result["code"]:
        print("error: timed out waiting for callback (5 min).", file=sys.stderr)
        sys.exit(1)

    try:
        tokens = exchange_code_for_tokens(result["code"], redirect_uri)
    except GmailOAuthError as e:
        print(f"error: token exchange failed: {e}", file=sys.stderr)
        sys.exit(1)

    refresh = (tokens.get("refresh_token") or "").strip()
    if not refresh:
        print(
            "error: no refresh_token in Google's response. "
            "Revoke app access in Google Account → Security → Third-party access, then run this script again.",
            file=sys.stderr,
        )
        sys.exit(1)

    print()
    print("GOOGLE_REFRESH_TOKEN=(use this value in backend/.env)")
    print(refresh)
    print()

    if bootstrap_env_write_allowed():
        try:
            upsert_env_files_everywhere({"GOOGLE_REFRESH_TOKEN": refresh})
            print("Saved GOOGLE_REFRESH_TOKEN via upsert_env_files_everywhere(). Restart API if it does not reload .env.")
        except OSError as e:
            print(f"warning: could not write .env: {e}", file=sys.stderr)
    else:
        print("ALLOW_SETUP_ENV_WRITE is off — copy the token into backend/.env manually and restart the API.")


if __name__ == "__main__":
    main()
