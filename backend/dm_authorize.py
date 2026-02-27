"""
One-time Dailymotion Authorization Script.

Run this ONCE to get a refresh token. The refresh token is stored in .env
and used by the uploader indefinitely (no password needed).

Usage:
    python3 dm_authorize.py

This will:
1. Open your browser to Dailymotion's authorization page
2. You log in and click "Allow"
3. Dailymotion redirects to localhost:8765
4. This script catches the code and exchanges it for tokens
5. The refresh token is saved to .env as DAILYMOTION_REFRESH_TOKEN
"""

import os
import sys
import json
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Load config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import DAILYMOTION_API_KEY, DAILYMOTION_API_SECRET

REDIRECT_URI = "http://localhost:8765/callback"
SCOPE = "manage_videos"
AUTH_CODE = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global AUTH_CODE
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            AUTH_CODE = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization successful!</h1><p>You can close this tab now.</p>")
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>Authorization failed</h1><p>{error}</p>".encode())

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def main():
    if not DAILYMOTION_API_KEY or not DAILYMOTION_API_SECRET:
        print("ERROR: DAILYMOTION_API_KEY and DAILYMOTION_API_SECRET must be set in .env")
        sys.exit(1)

    # Step 1: Build auth URL
    auth_url = (
        f"https://api.dailymotion.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={DAILYMOTION_API_KEY}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPE}"
    )

    print("=" * 60)
    print("DAILYMOTION AUTHORIZATION")
    print("=" * 60)
    print()
    print("IMPORTANT: Before running this, you must set the Callback URL")
    print("in your Dailymotion API key settings to:")
    print(f"  {REDIRECT_URI}")
    print()
    print("Go to: https://www.dailymotion.com/partner/api-keys/")
    print("Edit your API key -> Set Callback URL -> Save")
    print()
    print("Opening your browser now...")
    print()

    # Step 2: Open browser
    webbrowser.open(auth_url)

    # Step 3: Start local server to catch callback
    print(f"Waiting for callback on {REDIRECT_URI}...")
    server = HTTPServer(("localhost", 8765), CallbackHandler)
    server.handle_request()  # Handle exactly one request

    if not AUTH_CODE:
        print("ERROR: No authorization code received.")
        sys.exit(1)

    print(f"Authorization code received!")

    # Step 4: Exchange code for tokens
    print("Exchanging code for access token...")
    resp = requests.post("https://api.dailymotion.com/oauth/token", data={
        "grant_type": "authorization_code",
        "client_id": DAILYMOTION_API_KEY,
        "client_secret": DAILYMOTION_API_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": AUTH_CODE,
    })

    if resp.status_code != 200:
        print(f"ERROR: Token exchange failed: {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        print(f"ERROR: No refresh token in response: {token_data}")
        sys.exit(1)

    print(f"Access token: {access_token[:15]}...")
    print(f"Refresh token: {refresh_token[:15]}...")

    # Step 5: Save refresh token to .env
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(env_path, "r") as f:
        env_content = f.read()

    if "DAILYMOTION_REFRESH_TOKEN" in env_content:
        # Replace existing
        lines = env_content.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("DAILYMOTION_REFRESH_TOKEN"):
                new_lines.append(f"DAILYMOTION_REFRESH_TOKEN={refresh_token}")
            else:
                new_lines.append(line)
        env_content = "\n".join(new_lines) + "\n"
    else:
        # Append
        env_content += f"\nDAILYMOTION_REFRESH_TOKEN={refresh_token}\n"

    with open(env_path, "w") as f:
        f.write(env_content)

    print()
    print("=" * 60)
    print("SUCCESS! Refresh token saved to .env")
    print("The uploader will now use this token automatically.")
    print("You do NOT need to run this script again.")
    print("=" * 60)


if __name__ == "__main__":
    main()
