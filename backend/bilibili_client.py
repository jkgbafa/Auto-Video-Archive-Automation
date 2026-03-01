"""
Bilibili video uploader using the biliup library.

Bilibili requires session cookies for authentication:
  - SESSDATA: Main session token
  - bili_jct: CSRF token
  - DedeUserID: User ID

Since the account was created via Google OAuth, there's no
password-based API login. Use one of these methods to get cookies:

Method 1 (Recommended): QR Code Login via biliup
  Run: biliup login
  Scan the QR code with the Bilibili mobile app.
  Cookies are saved automatically (~6 months validity).

Method 2: Extract from browser
  1. Log into bilibili.com in Chrome
  2. Open DevTools (F12) > Application > Cookies > bilibili.com
  3. Copy SESSDATA, bili_jct, DedeUserID values
  4. Run: python bilibili_client.py --save-cookies

Upload modes:
  - bup: Direct upload to Bilibili CDN (domestic + overseas routes)
  - Overseas CDN routes: kodo (Qiniu), alia (Alibaba), txa (Tencent)

Rate limit: Upload 2-3 videos/day to avoid spam detection.
Cookie validity: ~6 months, auto-refresh supported.

Used as the DESTINATION for Darius's 2020 uploads (pCloud -> Bilibili).
"""

import os
import json
import time
from config import (
    BILIBILI_EMAIL, BILIBILI_PASSWORD,
)

SESSDATA = os.getenv("BILIBILI_SESSDATA", "")
BILI_JCT = os.getenv("BILIBILI_BILI_JCT", "")
DEDEUSERID = os.getenv("BILIBILI_DEDEUSERID", "")

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bilibili_cookies.json')

MAX_RETRIES = 2
RETRY_DELAY = 60

# Rate limit: max uploads per day to avoid spam detection
MAX_UPLOADS_PER_DAY = 3
_daily_upload_count = 0
_daily_upload_date = None


def _load_cookies():
    """Load Bilibili cookies from file or env."""
    sessdata = SESSDATA
    bili_jct = BILI_JCT
    dedeuserid = DEDEUSERID

    # Try cookies file if env is empty
    if not sessdata and os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE) as f:
                data = json.load(f)
            sessdata = data.get('SESSDATA', '')
            bili_jct = data.get('bili_jct', '')
            dedeuserid = data.get('DedeUserID', '')
        except Exception:
            pass

    # Also check biliup's default cookie location
    if not sessdata:
        biliup_cookie = os.path.expanduser('~/.biliup/cookies.json')
        if os.path.exists(biliup_cookie):
            try:
                with open(biliup_cookie) as f:
                    data = json.load(f)
                # biliup stores cookies in a different format
                if isinstance(data, dict):
                    cookie_info = data.get('cookie_info', {}).get('cookies', [])
                    for c in cookie_info:
                        if c.get('name') == 'SESSDATA':
                            sessdata = c.get('value', '')
                        elif c.get('name') == 'bili_jct':
                            bili_jct = c.get('value', '')
                        elif c.get('name') == 'DedeUserID':
                            dedeuserid = c.get('value', '')
                    # Also try flat format
                    if not sessdata:
                        sessdata = data.get('SESSDATA', '')
                        bili_jct = data.get('bili_jct', '')
                        dedeuserid = data.get('DedeUserID', '')
            except Exception:
                pass

    if not sessdata or not bili_jct:
        return None

    return {
        'SESSDATA': sessdata,
        'bili_jct': bili_jct,
        'DedeUserID': dedeuserid,
    }


def save_cookies(sessdata, bili_jct, dedeuserid):
    """Save Bilibili cookies to file."""
    with open(COOKIES_FILE, 'w') as f:
        json.dump({
            'SESSDATA': sessdata,
            'bili_jct': bili_jct,
            'DedeUserID': dedeuserid,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)
    print(f"[Bilibili] Cookies saved to {COOKIES_FILE}")


def has_credentials():
    """Check if Bilibili cookies are configured."""
    cookies = _load_cookies()
    return cookies is not None


def _check_daily_limit():
    """Check if we've hit the daily upload limit."""
    global _daily_upload_count, _daily_upload_date

    today = time.strftime('%Y-%m-%d')
    if _daily_upload_date != today:
        _daily_upload_count = 0
        _daily_upload_date = today

    if _daily_upload_count >= MAX_UPLOADS_PER_DAY:
        print(f"[Bilibili] Daily upload limit reached ({MAX_UPLOADS_PER_DAY}/day)")
        print(f"  Will resume tomorrow to avoid spam detection")
        return False
    return True


def _upload_via_biliup_lib(video_path, title, description="", tags=None):
    """
    Upload using biliup as a Python library (preferred method).
    Uses the BiliBili class from biliup.plugins.bili_webup.
    """
    cookies = _load_cookies()
    if not cookies:
        print("[Bilibili] No cookies configured")
        return None

    try:
        from biliup.plugins.bili_webup import BiliBili, Data

        video = Data()
        video.title = title[:80]
        video.desc = (description or title)[:250]
        video.tid = 174  # Life > Other
        video.set_tag(tags or ['sermon', 'church', 'daghewardmills'])
        video.copyright = 1

        with BiliBili(video) as bili:
            bili.login("bili.cookie", {
                'cookies': {
                    'SESSDATA': cookies['SESSDATA'],
                    'bili_jct': cookies['bili_jct'],
                    'DedeUserID': cookies.get('DedeUserID', ''),
                },
            })

            # Upload file with auto route detection, 3 concurrent tasks
            video_part = bili.upload_file(video_path, lines='AUTO', tasks=3)
            video.append(video_part)

            # Submit the video
            ret = bili.submit()

        if ret:
            print(f"[Bilibili] Upload SUCCESS via biliup library")
            if isinstance(ret, dict):
                bvid = ret.get('data', {}).get('bvid', '')
                if bvid:
                    print(f"  BV ID: {bvid}")
                    print(f"  URL: https://www.bilibili.com/video/{bvid}")
            return ret

        print(f"[Bilibili] Submit returned empty result")
        return None

    except ImportError:
        print("[Bilibili] biliup not installed. Install with: pip install biliup")
        return None
    except Exception as e:
        print(f"[Bilibili] biliup library error: {e}")
        return None


def _upload_via_api(video_path, title, description="", tags=None):
    """
    Upload using bilibili-api-python library (async).
    Fallback if biliup doesn't work.
    """
    cookies = _load_cookies()
    if not cookies:
        print("[Bilibili] No cookies configured")
        return None

    try:
        import asyncio
        from bilibili_api import video_uploader, Credential

        credential = Credential(
            sessdata=cookies['SESSDATA'],
            bili_jct=cookies['bili_jct'],
            dedeuserid=cookies.get('DedeUserID', ''),
        )

        tag_list = tags or ['sermon', 'church', 'daghewardmills']

        page = video_uploader.VideoUploaderPage(
            path=video_path,
            title=title[:80],
            description=(description or title)[:250],
        )

        meta = {
            'title': title[:80],
            'desc': (description or title)[:250],
            'tag': ','.join(tag_list),
            'tid': 174,
            'copyright': 1,
        }

        uploader = video_uploader.VideoUploader(
            pages=[page],
            meta=meta,
            credential=credential,
        )

        result = asyncio.run(uploader.start())
        print(f"[Bilibili] API upload result: {result}")
        return result

    except ImportError:
        print("[Bilibili] bilibili-api-python not installed")
        return None
    except Exception as e:
        print(f"[Bilibili] API upload error: {e}")
        return None


def upload_to_bilibili(video_path, title, description="", tags=None):
    """
    Upload a video to Bilibili.

    Tries biliup library first, falls back to bilibili-api-python.
    Returns result on success, None on failure.
    """
    global _daily_upload_count

    if not os.path.exists(video_path):
        print(f"[Bilibili] File not found: {video_path}")
        return None

    if not has_credentials():
        print("[Bilibili] No cookies configured.")
        print("  Easiest: run 'biliup login' and scan QR with Bilibili app")
        print("  Or: python bilibili_client.py --save-cookies")
        return None

    if not _check_daily_limit():
        return "RATE_LIMITED"

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        print(f"[Bilibili] File too small ({file_size} bytes)")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[Bilibili {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title[:50]} ({file_size / 1024 / 1024:.1f} MB)")

        # Try biliup library first (handles chunking, routing, retries)
        result = _upload_via_biliup_lib(video_path, title, description, tags)
        if result:
            _daily_upload_count += 1
            return result

        # Fallback to bilibili-api-python
        result = _upload_via_api(video_path, title, description, tags)
        if result:
            _daily_upload_count += 1
            return result

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    print(f"[Bilibili] Upload failed after {MAX_RETRIES} attempts")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--save-cookies':
        print("Enter Bilibili cookies (from browser DevTools):")
        sessdata = input("  SESSDATA: ").strip()
        bili_jct = input("  bili_jct: ").strip()
        dedeuserid = input("  DedeUserID: ").strip()
        save_cookies(sessdata, bili_jct, dedeuserid)
        print("Done! Cookies saved.")

    elif len(sys.argv) > 1 and sys.argv[1] == '--check':
        if has_credentials():
            cookies = _load_cookies()
            print(f"[Bilibili] Cookies configured:")
            print(f"  SESSDATA: {cookies['SESSDATA'][:20]}...")
            print(f"  bili_jct: {cookies['bili_jct'][:20]}...")
            print(f"  DedeUserID: {cookies.get('DedeUserID', 'not set')}")
        else:
            print("[Bilibili] No cookies configured")
            print()
            print("To get cookies, use ONE of these methods:")
            print()
            print("Method 1 (Recommended): QR Code Login")
            print("  Run: biliup login")
            print("  Scan QR code with Bilibili mobile app")
            print()
            print("Method 2: Browser extraction")
            print("  1. Log into bilibili.com")
            print("  2. F12 > Application > Cookies > bilibili.com")
            print("  3. Run: python bilibili_client.py --save-cookies")

    elif len(sys.argv) > 1 and sys.argv[1] == '--login':
        print("Starting biliup QR code login...")
        print("Scan the QR code with your Bilibili mobile app.")
        import subprocess
        result = subprocess.run(['biliup', 'login'], timeout=120)
        if result.returncode == 0:
            print("Login successful! Cookies saved by biliup.")
        else:
            print("Login failed or timed out.")

    elif len(sys.argv) > 2:
        video_path = sys.argv[1]
        title = sys.argv[2]
        result = upload_to_bilibili(video_path, title)
        print(f"Result: {result}")

    else:
        print("Usage:")
        print("  python bilibili_client.py --login          # QR code login (recommended)")
        print("  python bilibili_client.py --save-cookies   # Save browser cookies")
        print("  python bilibili_client.py --check          # Check if cookies are set")
        print("  python bilibili_client.py <video> <title>  # Upload a video")
