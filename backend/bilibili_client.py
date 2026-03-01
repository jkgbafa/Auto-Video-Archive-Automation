"""
Bilibili video uploader using the biliup library.

Bilibili requires browser session cookies for authentication:
  - SESSDATA: Main session token
  - bili_jct: CSRF token
  - DedeUserID: User ID

Since the account was created via Google OAuth, there's no
password-based API login. Cookies must be extracted from the browser.

How to get cookies:
  1. Log into bilibili.com in Chrome
  2. Open DevTools (F12) > Application > Cookies > bilibili.com
  3. Copy SESSDATA, bili_jct, DedeUserID values
  4. Put them in .env

Upload flow (biliup library):
  - bup mode: Direct upload to Bilibili (domestic)
  - bupfetch mode: Upload to third-party CDN, Bilibili fetches (overseas)

Used as the DESTINATION for Darius's 2020 uploads (pCloud -> Bilibili).
"""

import os
import json
import time
import asyncio
import subprocess
from config import (
    BILIBILI_EMAIL, BILIBILI_PASSWORD,
)

SESSDATA = os.getenv("BILIBILI_SESSDATA", "")
BILI_JCT = os.getenv("BILIBILI_BILI_JCT", "")
DEDEUSERID = os.getenv("BILIBILI_DEDEUSERID", "")

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bilibili_cookies.json')

MAX_RETRIES = 2
RETRY_DELAY = 60


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


def _upload_via_biliup_cli(video_path, title, description="", tags=None):
    """
    Upload using biliup CLI tool.
    This is the most reliable method as it handles all the upload complexity.
    """
    cookies = _load_cookies()
    if not cookies:
        print("[Bilibili] No cookies configured")
        return None

    # Write cookies to a temp file for biliup
    cookie_str = f"SESSDATA={cookies['SESSDATA']};bili_jct={cookies['bili_jct']}"
    if cookies.get('DedeUserID'):
        cookie_str += f";DedeUserID={cookies['DedeUserID']}"

    tag_list = tags or ['sermon', 'church', 'daghewardmills']
    tag_str = ','.join(tag_list)

    cmd = [
        'biliup', 'upload',
        '--cookies', cookie_str,
        '--title', title[:80],
        '--desc', (description or title)[:250],
        '--tag', tag_str,
        '--tid', '174',  # 生活 > 其他 (Life > Other)
        video_path,
    ]

    print(f"[Bilibili] Uploading via biliup CLI: {title[:50]}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=14400,  # 4 hours
        )

        if result.returncode == 0:
            print(f"[Bilibili] Upload SUCCESS")
            # Try to extract BV number from output
            for line in result.stdout.splitlines():
                if 'BV' in line or 'bv' in line:
                    print(f"  {line.strip()}")
            return True

        print(f"[Bilibili] Upload failed: {result.stderr[-300:] if result.stderr else result.stdout[-300:]}")
        return None

    except subprocess.TimeoutExpired:
        print("[Bilibili] Upload timed out (4 hours)")
        return None
    except FileNotFoundError:
        print("[Bilibili] biliup not found. Install with: pip install biliup")
        return None
    except Exception as e:
        print(f"[Bilibili] Upload error: {e}")
        return None


def _upload_via_api(video_path, title, description="", tags=None):
    """
    Upload using bilibili-api-python library (async).
    Fallback if biliup CLI doesn't work.
    """
    cookies = _load_cookies()
    if not cookies:
        print("[Bilibili] No cookies configured")
        return None

    try:
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
            'tid': 174,  # Life > Other
            'copyright': 1,
        }

        uploader = video_uploader.VideoUploader(
            pages=[page],
            meta=meta,
            credential=credential,
        )

        async def _do_upload():
            result = await uploader.start()
            return result

        result = asyncio.run(_do_upload())
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

    Tries biliup CLI first, falls back to bilibili-api-python.
    Returns True/result on success, None on failure.
    """
    if not os.path.exists(video_path):
        print(f"[Bilibili] File not found: {video_path}")
        return None

    if not has_credentials():
        print("[Bilibili] No cookies configured. Need SESSDATA + bili_jct from browser.")
        print("  1. Log into bilibili.com in Chrome")
        print("  2. F12 > Application > Cookies > bilibili.com")
        print("  3. Copy SESSDATA, bili_jct, DedeUserID")
        print("  4. Add to .env or run: python bilibili_client.py --save-cookies")
        return None

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        print(f"[Bilibili] File too small ({file_size} bytes)")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[Bilibili {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title[:50]} ({file_size / 1024 / 1024:.1f} MB)")

        # Try biliup CLI first
        result = _upload_via_biliup_cli(video_path, title, description, tags)
        if result:
            return result

        # Fallback to API
        result = _upload_via_api(video_path, title, description, tags)
        if result:
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

    elif len(sys.argv) > 2:
        video_path = sys.argv[1]
        title = sys.argv[2]
        result = upload_to_bilibili(video_path, title)
        print(f"Result: {result}")

    else:
        print("Usage:")
        print("  python bilibili_client.py --save-cookies    # Save browser cookies")
        print("  python bilibili_client.py --check           # Check if cookies are set")
        print("  python bilibili_client.py <video> <title>   # Upload a video")
