"""
BitChute Video Uploader via API + curl.

Upload flow (no browser needed):
  1. POST /api/beta/video/new → creates video slot, returns video_id
  2. POST /api/beta/apps/upload/video → returns upload server URL + auth key
  3. GET upload page → extract CSRF token
  4. POST {upload_server}/process_video → upload video file (FilePond)
  5. POST {upload_server}/process_thumbnail → upload thumbnail (FilePond)
  6. POST {upload_server}/finish_upload → submit metadata + publish

Auth: Bearer token from localStorage (extracted from Chrome session).
No Cloudflare issues since API calls go to api.bitchute.com.
File uploads go to upXXX.bitchute.com with URL-based auth (no cookies needed).
"""

import os
import re
import time
import json
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds between retries

# Token file stores the Bearer token extracted from Chrome localStorage
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bitchute_token.json')

API_BASE = "https://api.bitchute.com"
USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/131.0.0.0 Safari/537.36'
)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _load_token():
    """Load BitChute API bearer token from file."""
    if not os.path.exists(TOKEN_FILE):
        print(f"  [BitChute] Token file not found: {TOKEN_FILE}")
        return None, None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        token = data.get('access_token', '')
        channel_id = data.get('channel_id', '')
        if not token:
            print("  [BitChute] No access_token in token file")
            return None, None
        return token, channel_id
    except Exception as e:
        print(f"  [BitChute] Token load error: {e}")
        return None, None


def save_token(access_token, channel_id):
    """Save BitChute API bearer token to file."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'access_token': access_token,
            'channel_id': channel_id,
        }, f, indent=2)
    print(f"  [BitChute] Token saved to {TOKEN_FILE}")


FFMPEG_PATH = '/tmp/ffmpeg'


def _convert_thumbnail_to_jpeg(thumb_path):
    """Convert a WebP thumbnail to JPEG for BitChute compatibility."""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    if thumb_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        return thumb_path
    try:
        from PIL import Image
        jpeg_path = os.path.splitext(thumb_path)[0] + '.jpg'
        img = Image.open(thumb_path).convert('RGB')
        img.save(jpeg_path, 'JPEG', quality=90)
        print(f"  Converted thumbnail to JPEG: {jpeg_path}")
        return jpeg_path
    except Exception as e:
        print(f"  Could not convert thumbnail: {e}")
        return None


def _generate_thumbnail_from_video(video_path):
    """Extract a frame from the video at ~10% of duration as a JPEG thumbnail."""
    try:
        thumb_path = os.path.splitext(video_path)[0] + '_thumb.jpg'
        # Extract a frame at 5 seconds (or 10% of short videos)
        cmd = [
            FFMPEG_PATH, '-y',
            '-ss', '5',  # Seek to 5 seconds
            '-i', video_path,
            '-vframes', '1',
            '-q:v', '2',  # High quality JPEG
            '-vf', 'scale=1280:-2',  # Scale to 1280px wide, maintain aspect
            thumb_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(thumb_path):
            size = os.path.getsize(thumb_path)
            if size > 1000:  # At least 1KB
                print(f"  [BitChute] Auto-generated thumbnail ({size / 1024:.0f} KB)")
                return thumb_path
            else:
                os.remove(thumb_path)
        # If seeking to 5s failed, try at 0s
        cmd[3] = '0'
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(thumb_path):
            size = os.path.getsize(thumb_path)
            if size > 1000:
                print(f"  [BitChute] Auto-generated thumbnail from start ({size / 1024:.0f} KB)")
                return thumb_path
        return None
    except Exception as e:
        print(f"  [BitChute] Thumbnail generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# API helpers (using curl to avoid Python SSL issues)
# ---------------------------------------------------------------------------
def _api_post_json(url, token, payload, timeout=30):
    """POST JSON to BitChute API with Bearer token. Returns (status, dict)."""
    cmd = [
        'curl', '-sS',
        '-w', '\n__HTTP_CODE__%{http_code}',
        '-X', 'POST',
        '-H', f'Authorization: Bearer {token}',
        '-H', 'Content-Type: application/json',
        '-H', f'User-Agent: {USER_AGENT}',
        '-d', json.dumps(payload),
        url
    ]
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
        try:
            data = json.loads(body)
        except:
            data = {'raw': body[:500]}
        return status, data
    except subprocess.TimeoutExpired:
        return 0, {'error': 'timeout'}
    except Exception as e:
        return 0, {'error': str(e)}


def _curl_get(url, cookie_jar=None, timeout=30):
    """GET a URL. Returns (status, body_text).
    If cookie_jar path is provided, saves cookies to that file."""
    cmd = [
        'curl', '-sS',
        '-w', '\n__HTTP_CODE__%{http_code}',
        '-H', f'User-Agent: {USER_AGENT}',
    ]
    if cookie_jar:
        cmd.extend(['-c', cookie_jar])
    cmd.append(url)
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
    except Exception as e:
        return 0, str(e)


def _curl_upload_file(url, file_path, video_id, channel_id, upload_page_url='', is_video=True, timeout=7200):
    """Upload a file via multipart POST (FilePond style). Returns (status, body).

    FilePond renames files before upload:
      - Video: {video_id}-video.mp4
      - Thumbnail: {video_id}.jpg

    IMPORTANT: The form field name must match the original <input> element's name
    attribute, NOT the default 'filepond'. BitChute uses:
      - 'videoInput' for videos
      - 'thumbnailInput' for thumbnails
    """
    # Determine the FilePond filename (matching the JS fileRenameFunction)
    ext = os.path.splitext(file_path)[1].lower()
    if is_video:
        filepond_name = f"{video_id}-video{ext}"
        field_name = "videoInput"
    else:
        filepond_name = f"{video_id}{ext}"
        field_name = "thumbnailInput"

    # Determine MIME type
    mime_type = 'video/mp4' if is_video else 'image/jpeg'

    cmd = [
        'curl', '-sS',
        '-w', '\n__HTTP_CODE__%{http_code}',
        '-X', 'POST',
        '-H', f'User-Agent: {USER_AGENT}',
        '-H', f'X-VIDEOID: {video_id}',
        '-H', f'X-CHANNELID: {channel_id}',
        '-H', f'Origin: {url.split("/videos/")[0]}',
        '-H', f'Referer: {upload_page_url or url}',
        '-F', f'{field_name}=@{file_path};filename={filepond_name};type={mime_type}',
        url
    ]
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
        return 0, 'timeout'
    except Exception as e:
        return 0, str(e)


def _curl_post_form(url, form_data, cookie_jar=None, referer=None, timeout=60):
    """POST form data. Returns (status, body).
    If cookie_jar path is provided, sends cookies from that file."""
    cmd = [
        'curl', '-sS',
        '-w', '\n__HTTP_CODE__%{http_code}',
        '-X', 'POST',
        '-H', f'User-Agent: {USER_AGENT}',
        '-H', 'Content-Type: application/x-www-form-urlencoded',
    ]
    if cookie_jar:
        cmd.extend(['-b', cookie_jar])
    if referer:
        cmd.extend(['-H', f'Referer: {referer}',
                     '-H', f'Origin: {referer.split("/videos/")[0]}'])
    for key, value in form_data.items():
        cmd.extend(['--data-urlencode', f'{key}={value}'])
    cmd.append(url)

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
    except Exception as e:
        return 0, str(e)


# ---------------------------------------------------------------------------
# Upload pipeline
# ---------------------------------------------------------------------------
def _do_upload(token, channel_id, video_path, title, description, thumb_to_use):
    """
    Full upload pipeline using BitChute API + curl.
    Returns True on success.
    """
    # Create a temp cookie jar for this upload session
    cookie_jar = tempfile.mktemp(suffix='_bc_cookies.txt')

    try:
        return _do_upload_inner(token, channel_id, video_path, title, description, thumb_to_use, cookie_jar)
    finally:
        # Clean up cookie jar
        if os.path.exists(cookie_jar):
            os.remove(cookie_jar)


def _do_upload_inner(token, channel_id, video_path, title, description, thumb_to_use, cookie_jar):
    """Inner upload logic with cookie jar."""

    # --- Step 1: Create new video slot ---
    print("  [BitChute] Step 1: Creating video slot...")
    status, data = _api_post_json(
        f"{API_BASE}/api/beta/video/new",
        token,
        {'channel_id': channel_id}
    )
    if status != 200 or 'video_id' not in data:
        print(f"  [BitChute] Failed to create video slot: status={status} data={data}")
        return False

    video_id = data['video_id']
    print(f"  [BitChute] Video slot created: {video_id}")

    # --- Step 2: Get upload server URL ---
    print("  [BitChute] Step 2: Getting upload server URL...")
    status, data = _api_post_json(
        f"{API_BASE}/api/beta/apps/upload/video",
        token,
        {'channel_id': channel_id, 'video_id': video_id}
    )
    if status != 200 or 'url' not in data:
        print(f"  [BitChute] Failed to get upload URL: status={status} data={data}")
        return False

    upload_base = data['url']  # e.g. https://up110.bitchute.com/videos/upload/
    auth_key = data.get('auth', '')
    country = data.get('country', 'GH')
    print(f"  [BitChute] Upload server: {upload_base}")

    # --- Step 3: Get CSRF token from upload page (also saves cookies) ---
    print("  [BitChute] Step 3: Getting CSRF token...")
    upload_page_url = (
        f"{upload_base}?upload_code={video_id}"
        f"&channel={channel_id}&cid={channel_id}&cdid={channel_id}"
        f"&key={auth_key}&country={country}"
    )
    status, page_html = _curl_get(upload_page_url, cookie_jar=cookie_jar)
    if status != 200:
        print(f"  [BitChute] Failed to load upload page: status={status}")
        return False

    csrf_match = re.search(r'csrfmiddlewaretoken[^a-zA-Z]*([a-zA-Z0-9]{20,})', page_html)
    if not csrf_match:
        print("  [BitChute] Could not extract CSRF token from upload page")
        return False

    csrf_token = csrf_match.group(1)
    print(f"  [BitChute] CSRF token obtained")

    # Extract the key value from the page (may differ from URL-encoded version)
    key_match = re.search(r"'key'\s*:\s*'([^']+)'", page_html)
    page_key = key_match.group(1) if key_match else auth_key

    # --- Step 4: Upload video file ---
    file_size = os.path.getsize(video_path)
    print(f"  [BitChute] Step 4: Uploading video ({file_size / 1024 / 1024:.1f} MB)...")

    process_video_url = f"{upload_base}process_video"
    status, body = _curl_upload_file(
        process_video_url, video_path, video_id, channel_id,
        upload_page_url=upload_page_url, is_video=True,
        timeout=7200  # 2 hours for large files
    )
    if status != 200:
        print(f"  [BitChute] Video upload failed: status={status} body={body[:200]}")
        return False

    print(f"  [BitChute] Video uploaded successfully")

    # --- Step 5: Upload thumbnail ---
    if thumb_to_use and os.path.exists(thumb_to_use):
        print(f"  [BitChute] Step 5: Uploading thumbnail...")
        process_thumb_url = f"{upload_base}process_thumbnail"
        status, body = _curl_upload_file(
            process_thumb_url, thumb_to_use, video_id, channel_id,
            upload_page_url=upload_page_url, is_video=False,
            timeout=120
        )
        if status == 200:
            print(f"  [BitChute] Thumbnail uploaded")
        else:
            print(f"  [BitChute] Thumbnail upload failed (non-fatal): status={status}")
    else:
        print(f"  [BitChute] Step 5: No thumbnail available, skipping")

    # --- Step 6: Finish upload (submit metadata) ---
    print(f"  [BitChute] Step 6: Submitting metadata...")
    finish_url = f"{upload_base}finish_upload"
    form_data = {
        'csrfmiddlewaretoken': csrf_token,
        'key': page_key,
        'title': title[:100],  # BitChute limit: 3-100 chars
        'description': (description or '')[:5000],
        'sensitivity': '10',  # Normal
        'hashtags': 'sermon church',
        'publish': 'true',
    }

    status, body = _curl_post_form(finish_url, form_data, cookie_jar=cookie_jar, referer=upload_page_url)

    if status == 200:
        try:
            result = json.loads(body)
            if result.get('result') is False:
                error_msg = result.get('error', 'Unknown error')
                print(f"  [BitChute] Upload error: {error_msg}")
                return False
            else:
                print(f"  [BitChute] Upload SUCCESS! Title: {title}")
                return True
        except json.JSONDecodeError:
            # Non-JSON response — check for success indicators
            if 'error' in body.lower():
                print(f"  [BitChute] Upload error: {body[:300]}")
                return False
            print(f"  [BitChute] Upload likely succeeded (200 OK)")
            return True
    else:
        print(f"  [BitChute] Finish upload failed: status={status} body={body[:300]}")
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def upload_to_bitchute(video_path, title, description, thumbnail_path=None):
    """
    Upload a video to BitChute using the API + curl approach.

    Prerequisites:
      - Run save_token(access_token, channel_id) once after logging in via Chrome.
        The token is extracted from Chrome's localStorage on www.bitchute.com:
          access_token = localStorage.getItem('user_access_token').replace('__q_strn|', '')
          channel_id from localStorage.getItem('current_channel')

    Returns True on success, False on failure.
    """
    if not os.path.exists(video_path):
        print(f"[BitChute] Video file not found: {video_path}")
        return False

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        print(f"[BitChute] File too small ({file_size} bytes)")
        return False

    if file_size > 2 * 1024 * 1024 * 1024:
        print(f"[BitChute] File too large ({file_size / 1024 / 1024:.0f} MB) — BitChute max is 2GB")
        return False

    token, channel_id = _load_token()
    if not token or not channel_id:
        print("[BitChute] No valid token. Run save_token() after logging in via Chrome.")
        return False

    thumb_to_use = _convert_thumbnail_to_jpeg(thumbnail_path)
    auto_generated_thumb = None

    # BitChute requires a thumbnail — auto-generate from video if none provided
    if not thumb_to_use:
        print("[BitChute] No thumbnail provided, generating from video...")
        auto_generated_thumb = _generate_thumbnail_from_video(video_path)
        thumb_to_use = auto_generated_thumb

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[BitChute {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title}")

        try:
            success = _do_upload(
                token, channel_id,
                video_path, title, description, thumb_to_use
            )

            if success:
                print(f"{prefix} Complete: {title}")
                # Clean up auto-generated thumbnail
                if auto_generated_thumb and os.path.exists(auto_generated_thumb):
                    os.remove(auto_generated_thumb)
                return True

            last_error = "Upload failed"

        except Exception as e:
            last_error = str(e)
            print(f"{prefix} Error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    # Clean up auto-generated thumbnail
    if auto_generated_thumb and os.path.exists(auto_generated_thumb):
        os.remove(auto_generated_thumb)

    print(f"[BitChute] Failed after {MAX_RETRIES} attempts: {last_error}")
    return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python uploader_bitchute.py <video_path> [title]")
        print("       python uploader_bitchute.py --save-token <access_token> <channel_id>")
        print("       python uploader_bitchute.py --test")
        sys.exit(1)

    if sys.argv[1] == '--save-token':
        if len(sys.argv) < 4:
            print("Usage: --save-token <access_token> <channel_id>")
            sys.exit(1)
        save_token(sys.argv[2], sys.argv[3])
        sys.exit(0)

    if sys.argv[1] == '--test':
        token, channel_id = _load_token()
        if not token:
            print("No token saved. Use --save-token first.")
            sys.exit(1)
        print(f"Token length: {len(token)}")
        print(f"Channel ID: {channel_id}")

        # Test API access
        status, data = _api_post_json(
            f"{API_BASE}/api/beta/video/new",
            token,
            {'channel_id': channel_id}
        )
        if status == 200 and 'video_id' in data:
            print(f"API test OK! Created video slot: {data['video_id']}")
        else:
            print(f"API test failed: status={status} data={data}")
        sys.exit(0)

    test_path = sys.argv[1]
    test_title = sys.argv[2] if len(sys.argv) > 2 else "Test Upload"
    result = upload_to_bitchute(test_path, test_title, "Test upload")
    print(f"\nResult: {'SUCCESS' if result else 'FAILED'}")
