"""
NicoNico (nicovideo.jp) video uploader.

NicoNico has NO official public upload API (removed March 2017).
Upload must be done via reverse-engineered internal API or browser automation.

Authentication: Cookie-based (user_session cookie)
  - Login: POST https://account.nicovideo.jp/login/redirector?site=niconico
  - MFA: Required — 6-digit code sent to email on every login
  - Cookies needed: user_session, user_session_secure

Upload flow (reverse-engineered, may break):
  1. POST /v2/videos — create video entry
  2. POST /v2/videos/{id}/upload-chunk-stream — get chunk URL
  3. POST {chunk_url} — upload in 10MB chunks
  4. POST {chunk_url}?done — finalize
  5. POST /v2/videos/{id} — set metadata

Region restrictions: IP-based geo-blocking since Oct 2024.
  European VPS may need a Japanese VPN/proxy.

Free account limits:
  - 6 GB per video, 6 hours max duration
  - 50 videos (Level 1-7), scales up with level
  - 720p playback cap for viewers

Supported formats: MP4, MOV, MKV (H.264 recommended)

Status: NOT YET FUNCTIONAL — needs:
  1. Account registration on nicovideo.jp
  2. MFA handling (Gmail API to read 6-digit codes)
  3. Japanese VPN/proxy for upload endpoints
"""

import os
import time
import requests
from config import NICONICO_EMAIL, NICONICO_PASSWORD

BASE_URL = "https://www.upload.nicovideo.jp"
LOGIN_URL = "https://account.nicovideo.jp/login/redirector"

MAX_RETRIES = 2
RETRY_DELAY = 60

# Session cookie storage
_session_cookies = None


def _login(email=None, password=None):
    """
    Login to NicoNico. Returns session cookies or None.

    WARNING: NicoNico requires MFA (email code) on every login.
    This function will fail without MFA handling.
    """
    global _session_cookies

    if _session_cookies:
        return _session_cookies

    email = email or NICONICO_EMAIL
    password = password or NICONICO_PASSWORD

    if not email or not password:
        print("[NicoNico] No credentials configured")
        return None

    try:
        session = requests.Session()
        session.headers['User-Agent'] = (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )

        r = session.post(
            f'{LOGIN_URL}?site=niconico',
            data={'mail_tel': email, 'password': password},
            allow_redirects=False,
            timeout=30,
        )

        # Check for MFA challenge
        if 'mfa' in r.headers.get('Location', '').lower() or 'oneTimePw' in r.text:
            print("[NicoNico] MFA required — need 6-digit code from email")
            print("  Automated MFA not yet implemented")
            return None

        # Check for successful login
        user_session = session.cookies.get('user_session')
        if user_session:
            _session_cookies = dict(session.cookies)
            print("[NicoNico] Login successful")
            return _session_cookies

        # Check redirect for error
        location = r.headers.get('Location', '')
        if 'cant_login' in location:
            print("[NicoNico] Login failed — wrong credentials or account not found")
        else:
            print(f"[NicoNico] Login unclear — status {r.status_code}, redirect: {location}")

        return None

    except Exception as e:
        print(f"[NicoNico] Login error: {e}")
        return None


def has_credentials():
    """Check if NicoNico credentials are configured."""
    return bool(NICONICO_EMAIL and NICONICO_PASSWORD)


def upload_to_niconico(video_path, title, description="", tags=None):
    """
    Upload a video to NicoNico.

    NOT YET FUNCTIONAL — placeholder for future implementation.
    Requires: MFA handling, Japanese VPN, reverse-engineered API.
    """
    if not os.path.exists(video_path):
        print(f"[NicoNico] File not found: {video_path}")
        return None

    print("[NicoNico] Upload not yet implemented")
    print("  Blockers:")
    print("  1. MFA required on every login (need Gmail API)")
    print("  2. No official upload API (reverse-engineered only)")
    print("  3. May need Japanese VPN from European VPS")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        if has_credentials():
            print(f"[NicoNico] Credentials configured: {NICONICO_EMAIL}")
            print("  Attempting login...")
            cookies = _login()
            if cookies:
                print("  Login successful!")
            else:
                print("  Login failed (likely needs MFA or account registration)")
        else:
            print("[NicoNico] No credentials configured")

    elif len(sys.argv) > 1 and sys.argv[1] == '--login':
        print("[NicoNico] Testing login...")
        cookies = _login()
        if cookies:
            print(f"  user_session: {cookies.get('user_session', 'N/A')[:20]}...")

    else:
        print("Usage:")
        print("  python niconico_client.py --check   # Check credentials")
        print("  python niconico_client.py --login    # Test login")
        print()
        print("Status: NOT YET FUNCTIONAL")
        print("  Needs: MFA handling, Japanese VPN, account registration")
