"""
Koofr cloud storage client — upload, download, and manage files.

Koofr REST API base: https://app.koofr.net
Auth: GET /token with X-Koofr-Email + X-Koofr-Password headers
      Returns token in X-Koofr-Token response header.
      Subsequent requests: Authorization: Token <token>

WebDAV also available at https://app.koofr.net/dav/Koofr
but requires an app-specific password (generated in web UI).

Free account: 10 GB storage.

Used as DESTINATION for backup copies of sermon archive videos.
"""

import os
import json
import time
import requests
from config import KOOFR_EMAIL, KOOFR_PASSWORD

API_BASE = "https://app.koofr.net"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'koofr_token.json')

_auth_cache = {'token': None, 'mount_id': None, 'expires': 0}

MAX_RETRIES = 3
RETRY_DELAY = 30


def _save_token(token, mount_id=None):
    """Save auth token to disk."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'token': token,
            'mount_id': mount_id,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)


def _load_token():
    """Load saved auth token from disk."""
    if not os.path.exists(TOKEN_FILE):
        return None, None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        return data.get('token'), data.get('mount_id')
    except Exception:
        return None, None


def authenticate(email=None, password=None):
    """
    Authenticate with Koofr API.
    Returns (token, mount_id) tuple or (None, None).
    """
    now = time.time()
    if _auth_cache['token'] and _auth_cache['expires'] > now:
        return _auth_cache['token'], _auth_cache['mount_id']

    # Try saved token
    saved_token, saved_mount = _load_token()
    if saved_token:
        # Verify it still works
        r = requests.get(f'{API_BASE}/api/v2/user',
                         headers={'Authorization': f'Token {saved_token}'},
                         timeout=15)
        if r.status_code == 200:
            _auth_cache['token'] = saved_token
            _auth_cache['mount_id'] = saved_mount
            _auth_cache['expires'] = now + 3600
            return saved_token, saved_mount

    email = email or KOOFR_EMAIL
    password = password or KOOFR_PASSWORD

    if not email or not password:
        print("[Koofr] No credentials configured")
        return None, None

    try:
        r = requests.get(f'{API_BASE}/token',
                         headers={
                             'X-Koofr-Email': email,
                             'X-Koofr-Password': password,
                         },
                         timeout=30)

        if r.status_code != 200:
            print(f"[Koofr] Auth failed: {r.status_code}")
            return None, None

        token = r.headers.get('X-Koofr-Token', '')
        if not token:
            print("[Koofr] No token in response")
            return None, None

        # Get primary mount ID
        mount_id = _get_primary_mount(token)

        _auth_cache['token'] = token
        _auth_cache['mount_id'] = mount_id
        _auth_cache['expires'] = now + 3600

        _save_token(token, mount_id)
        print(f"[Koofr] Authenticated successfully")
        return token, mount_id

    except Exception as e:
        print(f"[Koofr] Auth error: {e}")
        return None, None


def _get_primary_mount(token):
    """Get the primary mount ID."""
    r = requests.get(f'{API_BASE}/api/v2/mounts',
                     headers={'Authorization': f'Token {token}'},
                     timeout=15)
    if r.status_code != 200:
        return None

    mounts = r.json().get('mounts', [])
    for m in mounts:
        if m.get('isPrimary'):
            return m['id']
    return mounts[0]['id'] if mounts else None


def get_quota():
    """Get storage quota info. Returns (used_bytes, total_bytes) or None."""
    token, _ = authenticate()
    if not token:
        return None

    r = requests.get(f'{API_BASE}/api/v2/mounts',
                     headers={'Authorization': f'Token {token}'},
                     timeout=15)
    if r.status_code != 200:
        return None

    mounts = r.json().get('mounts', [])
    for m in mounts:
        if m.get('isPrimary'):
            return m.get('spaceUsed', 0), m.get('spaceTotal', 0)
    return None


def list_files(remote_path="/"):
    """List files in a directory."""
    token, mount_id = authenticate()
    if not token or not mount_id:
        return None

    r = requests.get(f'{API_BASE}/api/v2/mounts/{mount_id}/files/list',
                     params={'path': remote_path},
                     headers={'Authorization': f'Token {token}'},
                     timeout=30)

    if r.status_code != 200:
        print(f"[Koofr] List failed: {r.status_code}")
        return None

    return r.json().get('files', [])


def create_folder(remote_path):
    """Create a folder (and parents)."""
    token, mount_id = authenticate()
    if not token or not mount_id:
        return False

    # Create path segments one by one
    parts = [p for p in remote_path.split('/') if p]
    current = '/'
    for part in parts:
        current = current.rstrip('/') + '/' + part
        r = requests.post(f'{API_BASE}/api/v2/mounts/{mount_id}/files/folder',
                          params={'path': current},
                          headers={'Authorization': f'Token {token}'},
                          timeout=15)
        # 200 = created, 409 = already exists
        if r.status_code not in (200, 409):
            print(f"[Koofr] Create folder failed: {r.status_code} for {current}")
            return False

    return True


def upload_file(local_path, remote_dir="/", remote_name=None):
    """
    Upload a file to Koofr.
    Returns True on success, None on failure.
    """
    token, mount_id = authenticate()
    if not token or not mount_id:
        return None

    if not os.path.exists(local_path):
        print(f"[Koofr] File not found: {local_path}")
        return None

    file_name = remote_name or os.path.basename(local_path)
    file_size = os.path.getsize(local_path)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Koofr {attempt}/{MAX_RETRIES}] Uploading: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

            with open(local_path, 'rb') as f:
                r = requests.post(
                    f'{API_BASE}/content/api/v2/mounts/{mount_id}/files/put',
                    params={'path': remote_dir, 'filename': file_name},
                    files={'file': (file_name, f)},
                    headers={'Authorization': f'Token {token}'},
                    timeout=7200,  # 2 hours for large files
                )

            if r.status_code == 200:
                print(f"[Koofr] Upload SUCCESS: {file_name}")
                return True

            print(f"[Koofr] Upload failed: {r.status_code} - {r.text[:200]}")

        except Exception as e:
            print(f"[Koofr] Upload error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    return None


def download_file(remote_path, local_path):
    """Download a file from Koofr."""
    token, mount_id = authenticate()
    if not token or not mount_id:
        return None

    try:
        r = requests.get(
            f'{API_BASE}/content/api/v2/mounts/{mount_id}/files/get',
            params={'path': remote_path},
            headers={'Authorization': f'Token {token}'},
            stream=True,
            timeout=7200,
        )

        if r.status_code != 200:
            print(f"[Koofr] Download failed: {r.status_code}")
            return None

        os.makedirs(os.path.dirname(local_path) or '.', exist_ok=True)
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=10 * 1024 * 1024):
                f.write(chunk)

        print(f"[Koofr] Downloaded: {remote_path}")
        return local_path

    except Exception as e:
        print(f"[Koofr] Download error: {e}")
        return None


def has_credentials():
    """Check if Koofr credentials are configured."""
    return bool(KOOFR_EMAIL and KOOFR_PASSWORD)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        if not has_credentials():
            print("[Koofr] No credentials configured")
        else:
            token, mount_id = authenticate()
            if token:
                quota = get_quota()
                if quota:
                    used, total = quota
                    print(f"[Koofr] Connected!")
                    print(f"  Storage: {used / 1024 / 1024:.1f} MB / {total / 1024 / 1024 / 1024:.1f} GB")
                    print(f"  Mount ID: {mount_id}")

                files = list_files('/')
                if files:
                    print(f"  Root files: {len(files)}")
                    for f in files[:10]:
                        print(f"    {f.get('name', '?')} ({f.get('size', 0) / 1024:.0f} KB)")
            else:
                print("[Koofr] Authentication failed")

    elif len(sys.argv) > 2 and sys.argv[1] == '--upload':
        local_file = sys.argv[2]
        remote_dir = sys.argv[3] if len(sys.argv) > 3 else '/Archive/'
        result = upload_file(local_file, remote_dir)
        print(f"Result: {result}")

    elif len(sys.argv) > 1 and sys.argv[1] == '--list':
        path = sys.argv[2] if len(sys.argv) > 2 else '/'
        files = list_files(path)
        if files:
            for f in files:
                size = f.get('size', 0)
                name = f.get('name', '?')
                ftype = 'DIR' if f.get('type') == 'dir' else f'{size / 1024:.0f}KB'
                print(f"  {ftype:>10}  {name}")

    else:
        print("Usage:")
        print("  python koofr_client.py --check              # Check connection")
        print("  python koofr_client.py --list [path]         # List files")
        print("  python koofr_client.py --upload <file> [dir] # Upload a file")
