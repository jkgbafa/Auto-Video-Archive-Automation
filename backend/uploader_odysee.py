"""
Odysee Video Uploader via TUS resumable upload protocol.

Upload flow:
  1. Authenticate: Get auth_token (from saved file or user/signin API)
  2. Resolve channel: Get channel claim_id via proxy API
  3. TUS upload: POST to create slot, PATCH to upload file data
  4. Notify: POST to /notify with publish JSON-RPC payload to finalize

Endpoints:
  - API proxy: https://api.na-backend.odysee.com/api/v1/proxy
  - Publish v2 (TUS): https://publish.na-backend.odysee.com/api/v2/publish/
  - User API: https://api.odysee.com

Auth token is saved to odysee_token.json after first successful login.
"""

import os
import sys
import json
import time
import re
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 30

ODYSEE_API = "https://api.odysee.com"
ODYSEE_PROXY = "https://api.na-backend.odysee.com/api/v1/proxy"
PUBLISH_URL = "https://publish.na-backend.odysee.com/api/v2/publish/"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'odysee_token.json')

# Default bid amount in LBC (very small to conserve credits)
DEFAULT_BID = "0.001"

# Chunk size for TUS upload (5 MB)
CHUNK_SIZE = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _load_token():
    """Load saved auth token from disk."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        return data.get('auth_token')
    except Exception:
        return None


def _save_token(auth_token, email=""):
    """Save auth token to disk."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'auth_token': auth_token,
            'email': email,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)
    print(f"  [Odysee] Auth token saved to {TOKEN_FILE}")


def authenticate(email=None, password=None):
    """
    Get a valid Odysee auth token.

    1. Try loading from saved file
    2. Try user/signin with email+password
    3. Fall back to instructions for manual login

    Returns auth_token string or None.
    """
    # Try saved token first
    token = _load_token()
    if token:
        # Verify it's still valid
        if _verify_token(token):
            print("  [Odysee] Using saved auth token")
            return token
        print("  [Odysee] Saved token expired, re-authenticating...")

    # Try API signin
    if email and password:
        token = _signin_api(email, password)
        if token:
            _save_token(token, email)
            return token

    print("  [Odysee] ERROR: No valid auth token. Run odysee_auth.py to authenticate.")
    return None


def _verify_token(token):
    """Check if an auth token is still valid by calling user/me."""
    try:
        r = requests.post(f'{ODYSEE_API}/user/me', data={
            'auth_token': token,
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get('success') and data.get('data', {}).get('has_verified_email'):
                return True
    except Exception:
        pass
    return False


def _signin_api(email, password):
    """
    Sign in via Odysee API.

    Step 1: Create anonymous user (gets temp auth_token)
    Step 2: Call user/signin with email + password
    """
    try:
        # Step 1: Get anonymous token
        r = requests.post(f'{ODYSEE_API}/user/new', data={}, timeout=15)
        if r.status_code != 200 or not r.json().get('success'):
            print(f"  [Odysee] user/new failed: {r.text[:200]}")
            return None

        temp_token = r.json()['data']['auth_token']

        # Step 2: Sign in
        r = requests.post(f'{ODYSEE_API}/user/signin', data={
            'auth_token': temp_token,
            'email': email,
            'password': password,
        }, timeout=15)

        if r.status_code == 200 and r.json().get('success'):
            print("  [Odysee] Authenticated via API signin")
            return temp_token

        error = r.json().get('error', r.text[:200])
        print(f"  [Odysee] signin failed: {error}")
        return None

    except Exception as e:
        print(f"  [Odysee] Auth error: {e}")
        return None


# ---------------------------------------------------------------------------
# Channel resolution
# ---------------------------------------------------------------------------
_channel_cache = {}


def _resolve_channel(auth_token, channel_name=None):
    """
    Get the channel's claim_id. If channel_name is given, resolve it.
    Otherwise, list channels and use the first one.
    """
    cache_key = channel_name or '__default__'
    if cache_key in _channel_cache:
        return _channel_cache[cache_key]

    try:
        # List user's channels
        r = requests.post(ODYSEE_PROXY, json={
            'jsonrpc': '2.0',
            'method': 'channel_list',
            'params': {'page': 1, 'page_size': 20},
            'id': 1,
        }, headers={
            'X-Lbry-Auth-Token': auth_token,
        }, timeout=30)

        if r.status_code != 200:
            print(f"  [Odysee] channel_list failed: HTTP {r.status_code}")
            return None

        data = r.json()
        if 'error' in data:
            print(f"  [Odysee] channel_list error: {data['error']}")
            return None

        items = data.get('result', {}).get('items', [])
        if not items:
            print("  [Odysee] No channels found. Create one on odysee.com first.")
            return None

        # Find matching channel or use first
        for ch in items:
            name = ch.get('name', '')
            claim_id = ch.get('claim_id', '')
            print(f"  [Odysee] Found channel: {name} ({claim_id[:12]}...)")

            if channel_name and channel_name.lower() in name.lower():
                _channel_cache[cache_key] = claim_id
                return claim_id

        # Default to first channel
        claim_id = items[0].get('claim_id', '')
        _channel_cache[cache_key] = claim_id
        return claim_id

    except Exception as e:
        print(f"  [Odysee] Channel resolution error: {e}")
        return None


# ---------------------------------------------------------------------------
# TUS Upload
# ---------------------------------------------------------------------------
def _tus_upload(auth_token, file_path):
    """
    Upload a file using TUS resumable protocol.

    Returns the file_id (from the Location header) on success, or None.
    """
    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    print(f"  [Odysee] TUS upload: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

    # Step 1: Create upload slot
    headers = {
        'Upload-Length': str(file_size),
        'X-Lbry-Auth-Token': auth_token,
        'Tus-Resumable': '1.0.0',
        'Upload-Metadata': f'filename {_b64encode(file_name)}',
    }

    try:
        r = requests.post(PUBLISH_URL, headers=headers, timeout=60)
    except Exception as e:
        print(f"  [Odysee] TUS create failed: {e}")
        return None

    if r.status_code not in (200, 201):
        print(f"  [Odysee] TUS create failed: HTTP {r.status_code}")
        print(f"  Response: {r.text[:300]}")
        return None

    file_url = r.headers.get('Location')
    if not file_url:
        print("  [Odysee] TUS create: no Location header in response")
        return None

    # Make sure file_url is absolute
    if file_url.startswith('/'):
        file_url = 'https://publish.na-backend.odysee.com' + file_url

    print(f"  [Odysee] TUS slot created: {file_url.split('/')[-1][:20]}...")

    # Step 2: Upload data in chunks
    offset = 0
    with open(file_path, 'rb') as f:
        while offset < file_size:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break

            patch_headers = {
                'Upload-Offset': str(offset),
                'Content-Type': 'application/offset+octet-stream',
                'X-Lbry-Auth-Token': auth_token,
                'Tus-Resumable': '1.0.0',
            }

            try:
                r = requests.patch(file_url, headers=patch_headers, data=chunk, timeout=600)
            except Exception as e:
                print(f"  [Odysee] TUS PATCH failed at offset {offset}: {e}")
                # Try to resume
                resume_offset = _tus_get_offset(file_url, auth_token)
                if resume_offset is not None and resume_offset > offset:
                    offset = resume_offset
                    f.seek(offset)
                    continue
                return None

            if r.status_code not in (200, 204):
                print(f"  [Odysee] TUS PATCH failed: HTTP {r.status_code}")
                return None

            new_offset = r.headers.get('Upload-Offset')
            if new_offset:
                offset = int(new_offset)
            else:
                offset += len(chunk)

            pct = (offset / file_size) * 100
            if pct % 10 < (CHUNK_SIZE / file_size * 100):
                print(f"  [Odysee] Upload progress: {pct:.0f}%")

    print(f"  [Odysee] TUS upload complete")

    # Extract file_id from URL
    file_id = file_url.rstrip('/').split('/')[-1]
    return file_id


def _tus_get_offset(file_url, auth_token):
    """HEAD request to get current upload offset (for resume)."""
    try:
        r = requests.head(file_url, headers={
            'X-Lbry-Auth-Token': auth_token,
            'Tus-Resumable': '1.0.0',
        }, timeout=30)
        if r.status_code == 200:
            offset = r.headers.get('Upload-Offset')
            return int(offset) if offset else None
    except Exception:
        pass
    return None


def _b64encode(s):
    """Base64 encode a string (for TUS metadata)."""
    import base64
    return base64.b64encode(s.encode()).decode()


# ---------------------------------------------------------------------------
# Publish (notify)
# ---------------------------------------------------------------------------
def _notify_publish(auth_token, file_id, name, title, description, channel_id, tags=None, bid=None):
    """
    Call the TUS notify endpoint to finalize the publish.

    This triggers the actual stream_create on the lbrynet backend.
    """
    notify_url = f"{PUBLISH_URL}{file_id}/notify"

    # Clean up the name (must be URL-safe)
    clean_name = _slugify(title or name)

    params = {
        'name': clean_name,
        'title': title[:255] if title else clean_name,
        'description': description[:5000] if description else title,
        'bid': bid or DEFAULT_BID,
        'languages': ['en'],
        'tags': tags or ['sermon', 'church', 'daghewardmills'],
    }

    if channel_id:
        params['channel_id'] = channel_id

    payload = {
        'jsonrpc': '2.0',
        'method': 'publish',
        'params': params,
        'id': int(time.time()),
    }

    headers = {
        'X-Lbry-Auth-Token': auth_token,
        'Content-Type': 'application/json',
    }

    print(f"  [Odysee] Publishing: {clean_name}")

    try:
        r = requests.post(notify_url, headers=headers, json=payload, timeout=120)
    except Exception as e:
        print(f"  [Odysee] Notify failed: {e}")
        return None

    if r.status_code not in (200, 201):
        print(f"  [Odysee] Notify failed: HTTP {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        return None

    try:
        result = r.json()
        if 'error' in result:
            error_msg = result['error'].get('message', str(result['error']))
            print(f"  [Odysee] Publish error: {error_msg}")
            return None

        # Extract the claim info
        outputs = result.get('result', {}).get('outputs', [])
        if outputs:
            claim_id = outputs[0].get('claim_id', '')
            name = outputs[0].get('name', '')
            print(f"  [Odysee] Published! claim_id={claim_id}")
            return {
                'claim_id': claim_id,
                'name': name,
                'url': f"https://odysee.com/{name}:{claim_id}" if claim_id else '',
            }

        print(f"  [Odysee] Publish response: {json.dumps(result)[:300]}")
        return result.get('result')

    except Exception as e:
        print(f"  [Odysee] Parse notify response: {e}")
        return None


def _slugify(text):
    """Convert title to URL-safe slug for LBRY name."""
    # Lowercase, replace spaces/special chars with hyphens
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug)  # Collapse multiple hyphens
    slug = slug.strip('-')
    # LBRY names have max length
    if len(slug) > 200:
        slug = slug[:200].rstrip('-')
    return slug or 'untitled'


# ---------------------------------------------------------------------------
# V1 Multipart Upload (fallback)
# ---------------------------------------------------------------------------
def _upload_v1_multipart(auth_token, file_path, title, description, channel_id, tags=None, bid=None):
    """
    Upload via v1 multipart endpoint (simpler, single request).
    Fallback if TUS doesn't work.
    """
    clean_name = _slugify(title)

    params = {
        'name': clean_name,
        'title': title[:255] if title else clean_name,
        'description': description[:5000] if description else title,
        'bid': bid or DEFAULT_BID,
        'languages': ['en'],
        'tags': tags or ['sermon', 'church', 'daghewardmills'],
    }

    if channel_id:
        params['channel_id'] = channel_id

    json_payload = json.dumps({
        'jsonrpc': '2.0',
        'method': 'publish',
        'params': params,
        'id': int(time.time()),
    })

    publish_v1_url = "https://publish.na-backend.odysee.com/v1"

    file_size = os.path.getsize(file_path)
    print(f"  [Odysee] V1 multipart upload: {file_size / 1024 / 1024:.1f} MB")

    try:
        with open(file_path, 'rb') as f:
            r = requests.post(
                publish_v1_url,
                headers={'X-Lbry-Auth-Token': auth_token},
                files={'file': (os.path.basename(file_path), f, 'video/mp4')},
                data={'json_payload': json_payload},
                timeout=7200,
            )

        if r.status_code not in (200, 201):
            print(f"  [Odysee] V1 upload failed: HTTP {r.status_code}")
            print(f"  Response: {r.text[:500]}")
            return None

        result = r.json()
        if 'error' in result:
            print(f"  [Odysee] V1 error: {result['error']}")
            return None

        outputs = result.get('result', {}).get('outputs', [])
        if outputs:
            claim_id = outputs[0].get('claim_id', '')
            name = outputs[0].get('name', '')
            return {
                'claim_id': claim_id,
                'name': name,
                'url': f"https://odysee.com/{name}:{claim_id}" if claim_id else '',
            }
        return result.get('result')

    except Exception as e:
        print(f"  [Odysee] V1 upload error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main upload entry point
# ---------------------------------------------------------------------------
def upload_to_odysee(video_path, title, description, tags=None, channel_name=None):
    """
    Upload a video to Odysee.

    Returns claim_id string on success, or None on failure.
    """
    if not os.path.exists(video_path):
        print(f"[Odysee] Video file not found: {video_path}")
        return None

    file_size = os.path.getsize(video_path)
    if file_size < 1000:
        print(f"[Odysee] File too small ({file_size} bytes)")
        return None

    # Check file size limit (4 GB for web uploads)
    if file_size > 4 * 1024 * 1024 * 1024:
        print(f"[Odysee] File too large for web upload ({file_size / 1024 / 1024 / 1024:.1f} GB > 4 GB limit)")
        return None

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[Odysee {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title}")

        try:
            # Authenticate
            email = os.getenv('ODYSEE_EMAIL', '')
            password = os.getenv('ODYSEE_PASSWORD', '')
            auth_token = authenticate(email, password)
            if not auth_token:
                print(f"{prefix} Authentication failed")
                return None

            # Resolve channel
            channel_id = _resolve_channel(auth_token, channel_name)
            if not channel_id:
                print(f"{prefix} Warning: No channel found, publishing to anonymous")

            # Try TUS upload first (better for large files)
            file_id = _tus_upload(auth_token, video_path)

            if file_id:
                # Notify to finalize
                result = _notify_publish(
                    auth_token, file_id,
                    _slugify(title), title, description, channel_id,
                    tags=tags,
                )

                if result:
                    claim_id = result.get('claim_id') if isinstance(result, dict) else None
                    if claim_id:
                        print(f"{prefix} Upload SUCCESS! claim_id={claim_id}")
                        return claim_id
                    # Non-dict result might still be success
                    print(f"{prefix} Upload completed (result: {str(result)[:200]})")
                    return str(result)[:64] if result else None

                print(f"{prefix} Notify failed, trying v1 fallback...")

            # Fallback to v1 multipart
            result = _upload_v1_multipart(
                auth_token, video_path,
                title, description, channel_id,
                tags=tags,
            )

            if result:
                claim_id = result.get('claim_id') if isinstance(result, dict) else None
                if claim_id:
                    print(f"{prefix} Upload SUCCESS (v1)! claim_id={claim_id}")
                    return claim_id
                print(f"{prefix} Upload completed via v1")
                return str(result)[:64] if result else None

            last_error = "Both TUS and v1 upload failed"

        except Exception as e:
            last_error = str(e)
            print(f"{prefix} Error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    print(f"[Odysee] Failed after {MAX_RETRIES} attempts: {last_error}")
    return None


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python uploader_odysee.py --auth          # Test authentication")
        print("  python uploader_odysee.py --channels       # List channels")
        print("  python uploader_odysee.py <video_path>     # Upload a video")
        sys.exit(1)

    # Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass

    if sys.argv[1] == '--auth':
        email = os.getenv('ODYSEE_EMAIL', '')
        password = os.getenv('ODYSEE_PASSWORD', '')
        token = authenticate(email, password)
        if token:
            print(f"Auth token: {token[:20]}...")
            print("Token is valid!")
        else:
            print("Authentication failed")

    elif sys.argv[1] == '--channels':
        token = _load_token()
        if not token:
            print("No saved token. Run --auth first.")
            sys.exit(1)
        _resolve_channel(token)

    else:
        video_path = sys.argv[1]
        title = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(video_path)
        result = upload_to_odysee(video_path, title, "Test upload")
        print(f"\nResult: {result}")
