"""
Rumble Video Uploader via curl subprocess.

Uses session cookies + curl (not Python requests) to bypass Cloudflare
TLS fingerprinting that blocks Python's requests library.

Upload flow (single curl session with cookie jar):
  1. GET /upload.php → establishes PHP session
  2. POST file to /upload.php?api=1.3 → returns server filename
  3. POST metadata with video[]= server filename

Channel IDs (from account):
  - 2000ArchiveDHMM: 7856734
  - 2003Archivedhmm: 7856744
  - 2000Archive (User Profile): 0
"""

import os
import sys
import time
import json
import re
import subprocess
import tempfile
from config import RUMBLE_CHANNEL_NAME

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 30

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rumble_cookies.json')
UPLOAD_PAGE_URL = "https://rumble.com/upload.php"
UPLOAD_FILE_URL = "https://rumble.com/upload.php?api=1.3"
UPLOAD_META_URL = "https://rumble.com/upload.php?api=1.3&form=1"

CHANNEL_IDS = {
    "2000": 7856734,
    "2000archive": 0,
    "2000archivedhmm": 7856734,
    "2003archivedhmm": 7856744,
}

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/131.0.0.0 Safari/537.36'
)


# ---------------------------------------------------------------------------
# Cookie management
# ---------------------------------------------------------------------------
def _load_cookie_string():
    """Load session cookies as a curl -b string. Skips Cloudflare cookies."""
    if not os.path.exists(COOKIE_FILE):
        print(f"  [Rumble] Cookie file not found: {COOKIE_FILE}")
        return None
    try:
        with open(COOKIE_FILE) as f:
            raw = json.load(f)
        skip = {'cf_clearance', '__cf_bm', '_ga', '_ga_PRRJGSG9MK', '_gcl_au', '_fbp', 'g_state'}
        cookies = {c['name']: c['value'] for c in raw if c.get('name') and c['name'] not in skip}
        if not any(k in cookies for k in ['u_s', 'a_s', '__ssid']):
            print("  [Rumble] No auth cookies found")
            return None
        return '; '.join(f'{k}={v}' for k, v in cookies.items())
    except Exception as e:
        print(f"  [Rumble] Cookie load error: {e}")
        return None


def _write_cookie_jar(cookie_str, jar_path):
    """Write cookies to a Netscape cookie jar file for curl -b/-c flags."""
    with open(jar_path, 'w') as f:
        f.write("# Netscape HTTP Cookie File\n")
        for pair in cookie_str.split('; '):
            if '=' in pair:
                name, value = pair.split('=', 1)
                f.write(f".rumble.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}\n")


def _get_channel_id(name):
    if not name:
        return 0
    key = name.lower().strip()
    return CHANNEL_IDS.get(key, 0)


# ---------------------------------------------------------------------------
# curl helper with cookie jar
# ---------------------------------------------------------------------------
def _curl(args, jar_path, timeout=120):
    """Run curl with shared cookie jar. Returns (status_code, body)."""
    cmd = [
        'curl', '-s',
        '-w', '\n__HTTP_CODE__%{http_code}',
        '-b', jar_path,
        '-c', jar_path,
        '-H', f'User-Agent: {USER_AGENT}',
        '-H', 'Accept: */*',
        '-H', 'Accept-Language: en-US,en;q=0.9',
    ] + args

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout
        if '__HTTP_CODE__' in output:
            parts = output.rsplit('__HTTP_CODE__', 1)
            body = parts[0].rstrip('\n')
            try:
                status = int(parts[1].strip())
            except ValueError:
                status = 0
        else:
            body = output
            status = 0
        return status, body
    except subprocess.TimeoutExpired:
        print(f"  [Rumble] curl timeout ({timeout}s)")
        return 0, ''
    except Exception as e:
        print(f"  [Rumble] curl error: {e}")
        return 0, ''


# ---------------------------------------------------------------------------
# Upload pipeline
# ---------------------------------------------------------------------------
def _do_upload(cookie_str, video_path, title, description, tags, channel_id):
    """
    Full upload pipeline using a shared cookie jar.
    Steps:
      1. GET upload page (establish PHP session in jar)
      2. POST file via multipart (get server filename)
      3. POST metadata with video[]=filename
    Returns True on success.
    """
    # Create temp cookie jar
    jar_fd, jar_path = tempfile.mkstemp(suffix='.txt', prefix='rumble_jar_')
    os.close(jar_fd)

    try:
        # Write auth cookies to jar
        _write_cookie_jar(cookie_str, jar_path)

        # --- Step 1: GET upload page to establish PHPSESSID ---
        print("  [Rumble] Step 1: Loading upload page (establish session)...")
        status, body = _curl([
            '-H', 'Referer: https://rumble.com/',
            UPLOAD_PAGE_URL,
        ], jar_path, timeout=30)

        if status != 200:
            print(f"  [Rumble] Upload page failed: status={status}")
            return False

        if 'Filedata' not in body and 'upload' not in body.lower()[:500]:
            print(f"  [Rumble] Not authenticated or wrong page")
            return False

        user_match = re.search(r'"username":"([^"]+)"', body)
        if user_match:
            print(f"  [Rumble] Authenticated as: {user_match.group(1)}")

        # --- Step 2: POST video file ---
        file_size = os.path.getsize(video_path)
        print(f"  [Rumble] Step 2: Uploading file ({file_size / 1024 / 1024:.1f} MB)...")

        status, body = _curl([
            '-X', 'POST',
            '-H', 'Origin: https://rumble.com',
            '-H', 'Referer: https://rumble.com/upload.php',
            '-F', f'Filedata=@{video_path};type=video/mp4',
            UPLOAD_FILE_URL,
        ], jar_path, timeout=7200)

        if status != 200:
            print(f"  [Rumble] File upload failed: status={status}")
            return False

        # Extract server filename from response
        # Response is typically just the filename: "0-iapug1ibz41vt5joxd5c.mp4"
        video_ref = body.strip()
        if not video_ref or len(video_ref) > 200:
            print(f"  [Rumble] Unexpected upload response: {body[:300]}")
            return False

        print(f"  [Rumble] File uploaded -> server ref: {video_ref}")

        # --- Step 3: POST metadata ---
        print(f"  [Rumble] Step 3: Submitting metadata...")

        tag_str = ','.join(tags[:10]) if isinstance(tags, list) else str(tags or '')

        # Use --data-urlencode for proper encoding of special chars
        metadata_args = [
            '-X', 'POST',
            '-H', 'Origin: https://rumble.com',
            '-H', 'Referer: https://rumble.com/upload.php',
            '-H', 'Content-Type: application/x-www-form-urlencoded',
            '--data-urlencode', f'title={title[:255]}',
            '--data-urlencode', f'description={(description or title)[:5000]}',
            '--data-urlencode', f'tags={tag_str}',
            '-d', f'channelId={channel_id}',
            '-d', 'visibility=public',
            '-d', 'primary-category=0',
            '-d', 'secondary-category=0',
            '--data-urlencode', f'video[]={video_ref}',
            '-d', 'rights=1',
            '-d', 'terms=1',
            '-d', 'featured=6',
            '-d', 'schedulerDatetime=',
            UPLOAD_META_URL,
        ]

        status, body = _curl(metadata_args, jar_path, timeout=60)

        print(f"  [Rumble] Metadata response: status={status}")

        if status == 200:
            body_lower = body[:3000].lower()
            if 'you must upload a file' in body_lower:
                print("  [Rumble] Error: 'You must upload a file' - session linkage broken")
                return False
            if 'error' in body_lower and 'seterrors' in body_lower:
                # Extract error message
                err_match = re.search(r'setErrors\(\{([^}]+)\}', body)
                if err_match:
                    print(f"  [Rumble] Error: {err_match.group(1)}")
                return False
            # Success indicators
            if any(s in body_lower for s in ['success', 'processing', 'uploaded', 'congratulations', 'video management', 'video_id']):
                print("  [Rumble] Upload SUCCESS!")
                return True
            # If we got 200 with no errors, it's likely success
            if 'error' not in body_lower:
                print("  [Rumble] Upload likely succeeded (200, no errors)")
                # Try to extract video URL from response
                url_match = re.search(r'rumble\.com/[a-zA-Z0-9-]+\.html', body)
                if url_match:
                    print(f"  [Rumble] Video URL: https://{url_match.group(0)}")
                return True

            print(f"  [Rumble] Uncertain result: {body[:500]}")
            return False

        print(f"  [Rumble] Metadata failed: status={status}")
        return False

    finally:
        # Clean up cookie jar
        try:
            os.remove(jar_path)
        except:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def upload_to_rumble(video_path, title, description, tags=None):
    """
    Upload a video to Rumble using curl with session cookies.
    Returns True on success, False on failure.
    """
    if not os.path.exists(video_path):
        print(f"[Rumble] Video file not found: {video_path}")
        return False

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        print(f"[Rumble] File too small ({file_size} bytes)")
        return False

    channel_id = _get_channel_id(RUMBLE_CHANNEL_NAME)
    print(f"[Rumble] Channel: {RUMBLE_CHANNEL_NAME} (id={channel_id})")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[Rumble {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title}")

        try:
            cookie_str = _load_cookie_string()
            if not cookie_str:
                print(f"{prefix} No valid cookies.")
                return False

            success = _do_upload(
                cookie_str, video_path,
                title, description, tags or [], channel_id
            )

            if success:
                print(f"{prefix} Complete: {title}")
                return True

            last_error = "Upload failed"

        except Exception as e:
            last_error = str(e)
            print(f"{prefix} Error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    print(f"[Rumble] Failed after {MAX_RETRIES} attempts: {last_error}")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python uploader_rumble.py <video_path> [title] [channel]")
        print("       python uploader_rumble.py --test")
        sys.exit(1)

    if sys.argv[1] == '--test':
        cookie_str = _load_cookie_string()
        if cookie_str:
            jar_fd, jar_path = tempfile.mkstemp(suffix='.txt')
            os.close(jar_fd)
            _write_cookie_jar(cookie_str, jar_path)
            status, body = _curl([UPLOAD_PAGE_URL], jar_path, timeout=30)
            print(f"Status: {status}")
            if status == 200 and 'Filedata' in body:
                m = re.search(r'"username":"([^"]+)"', body)
                print(f"Session valid! User: {m.group(1) if m else 'unknown'}")
            else:
                print(f"Session invalid or blocked")
            os.remove(jar_path)
        sys.exit(0)

    test_path = sys.argv[1]
    test_title = sys.argv[2] if len(sys.argv) > 2 else "Test Upload"
    if len(sys.argv) > 3:
        import config as cfg
        cfg.RUMBLE_CHANNEL_NAME = sys.argv[3]

    result = upload_to_rumble(test_path, test_title, "Test upload", ['sermon', 'church'])
    print(f"\nResult: {'SUCCESS' if result else 'FAILED'}")
