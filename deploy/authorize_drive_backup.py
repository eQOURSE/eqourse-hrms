"""Authorize the existing HRMS backup folder via Google's desktop Picker."""

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

SCOPE = "https://www.googleapis.com/auth/drive.file"
REGION = "ap-south-1"
ACCOUNT = "284874841026"
PARAMETER = "/eqourse/hrms/google-drive-backup-credentials"


def aws(*args):
    result = subprocess.run(
        ["aws", *args, "--region", REGION, "--no-cli-pager"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        # Avoid printing errors that might contain supplied credential input.
        raise RuntimeError(f"AWS {args[0]} {args[1]} failed (exit {result.returncode}).")
    return result.stdout.strip()


def google_json(url, *, form=None, access_token=None):
    data = urlencode(form).encode() if form else None
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"Google {urlsplit(url).hostname} returned HTTP {error.code}."
        ) from None
    except URLError:
        raise RuntimeError("Could not reach Google.") from None


def authorize(client, account_email, folder_id):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    callback = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            nonlocal callback
            request = urlsplit(self.path)
            params = parse_qs(request.query)
            supplied_state = params.get("state", [""])[0]
            valid = (
                request.path == "/callback"
                and hmac.compare_digest(supplied_state.encode(), state.encode())
            )
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if valid:
                callback = params
                self.wfile.write(b"Google response received. Return to the setup chat.")
            else:
                self.wfile.write(b"Invalid or expired backup authorization request.")

    with HTTPServer(("127.0.0.1", 0), CallbackHandler) as server:
        server.timeout = 1
        redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
        query = urlencode({
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "login_hint": account_email,
            "trigger_onepick": "true",
            "allow_folder_selection": "true",
            "file_ids": folder_id,
        })
        print(f"Open this one-time URL: https://accounts.google.com/o/oauth2/v2/auth?{query}", flush=True)
        deadline = time.monotonic() + 600
        while callback is None and time.monotonic() < deadline:
            server.handle_request()
    if not callback or "error" in callback or not callback.get("code"):
        raise RuntimeError("Google authorization was cancelled or expired.")
    if callback.get("picked_file_ids") != [folder_id]:
        raise RuntimeError("Select only the existing horilla_backup folder.")

    token = google_json("https://oauth2.googleapis.com/token", form={
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code": callback["code"][0],
        "code_verifier": verifier,
    })
    if set(token.get("scope", "").split()) != {SCOPE} or not token.get("refresh_token"):
        raise RuntimeError("Google did not issue the required folder backup authorization.")
    access_token = token["access_token"]
    api = "https://www.googleapis.com/drive/v3"
    identity = google_json(
        f"{api}/about?fields=user(emailAddress)", access_token=access_token
    )
    if identity.get("user", {}).get("emailAddress", "").lower() != account_email:
        raise RuntimeError("Sign in with the requested backup account.")
    folder_fields = urlencode({"fields": "id,mimeType,capabilities(canAddChildren)"})
    folder = google_json(
        f"{api}/files/{folder_id}?{folder_fields}", access_token=access_token
    )
    if (
        folder.get("id") != folder_id
        or folder.get("mimeType") != "application/vnd.google-apps.folder"
        or not folder.get("capabilities", {}).get("canAddChildren")
    ):
        raise RuntimeError("The selected Drive folder does not allow backup uploads.")
    return {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "refresh_token": token["refresh_token"],
        "folder_id": folder_id,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-json", type=Path, required=True)
    parser.add_argument("--account-email", required=True)
    parser.add_argument("--folder-id", required=True)
    args = parser.parse_args()

    if aws("sts", "get-caller-identity", "--query", "Account", "--output", "text") != ACCOUNT:
        raise RuntimeError("The AWS session is for a different account.")
    client = json.loads(args.client_json.read_text(encoding="utf-8-sig")).get("installed")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        raise RuntimeError("Download the JSON for a Google Desktop app OAuth client.")

    credentials = authorize(client, args.account_email.lower(), args.folder_id)
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "parameter.json"
        path.write_text(json.dumps({
            "Name": PARAMETER,
            "Description": "Folder-scoped eQOURSE Work backup uploader",
            "Type": "SecureString",
            "Tier": "Standard",
            "Value": json.dumps(credentials),
            "Overwrite": False,
        }), encoding="utf-8")
        aws("ssm", "put-parameter", "--cli-input-json", f"file://{path}")
    print("The selected folder was verified and the uploader credential was stored.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error) if isinstance(error, RuntimeError) else "Backup authorization setup failed.") from None
