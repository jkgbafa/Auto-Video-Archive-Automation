"""
Internxt API client — list and download files.

Internxt uses end-to-end encryption, which makes API access more complex
than standard cloud storage. Their web app uses a REST API with JWT auth.

Auth flow:
  1. POST /api/access with email + password -> token + user info
  2. Use Bearer token for subsequent requests

Used as the SOURCE platform for Eniola's 2021 uploads.
Automation monitors Internxt for new files and transfers to Icedrive.
"""

import os
import json
import time
import hashlib
import requests
from config import INTERNXT_EMAIL, INTERNXT_PASSWORD

API_BASE = "https://drive.internxt.com"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'internxt_token.json')

_auth_cache = {'token': None, 'user': None, 'expires': 0}


def _save_token(token, user_data=None):
    """Save auth token to disk."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'token': token,
            'user': user_data,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)


def _load_token():
    """Load saved auth token."""
    if not os.path.exists(TOKEN_FILE):
        return None, None
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        return data.get('token'), data.get('user')
    except Exception:
        return None, None


def authenticate(email=None, password=None):
    """
    Authenticate with Internxt.
    Returns (token, user_data) or (None, None).
    """
    now = time.time()
    if _auth_cache['token'] and _auth_cache['expires'] > now:
        return _auth_cache['token'], _auth_cache['user']

    # Try saved token
    saved_token, saved_user = _load_token()
    if saved_token:
        # Verify token is still valid
        try:
            r = requests.get(f'{API_BASE}/api/user', headers={
                'Authorization': f'Bearer {saved_token}',
            }, timeout=15)
            if r.status_code == 200:
                _auth_cache['token'] = saved_token
                _auth_cache['user'] = saved_user
                _auth_cache['expires'] = now + 3600
                print("[Internxt] Using saved token")
                return saved_token, saved_user
        except Exception:
            pass

    # Fresh login
    email = email or INTERNXT_EMAIL
    password = password or INTERNXT_PASSWORD
    if not email or not password:
        print("[Internxt] No credentials configured")
        return None, None

    try:
        # Internxt uses SHA-256 hashed password for some endpoints
        # But the /api/access endpoint accepts plain password
        r = requests.post(f'{API_BASE}/api/access', json={
            'email': email,
            'password': password,
        }, timeout=30)

        if r.status_code != 200:
            print(f"[Internxt] Auth failed: HTTP {r.status_code} - {r.text[:200]}")
            return None, None

        data = r.json()
        token = data.get('token')
        user = data.get('user', data)

        if not token:
            # Try alternative auth endpoint
            r = requests.post(f'{API_BASE}/api/login', json={
                'email': email,
                'password': password,
            }, timeout=30)
            if r.status_code == 200:
                data = r.json()
                token = data.get('token')
                user = data.get('user', data)

        if not token:
            print(f"[Internxt] No token in response: {str(data)[:200]}")
            return None, None

        _save_token(token, user)
        _auth_cache['token'] = token
        _auth_cache['user'] = user
        _auth_cache['expires'] = now + 3600
        print(f"[Internxt] Authenticated as {email}")
        return token, user

    except Exception as e:
        print(f"[Internxt] Auth error: {e}")
        return None, None


def list_folder(folder_id=None):
    """
    List contents of an Internxt folder.
    If folder_id is None, lists the root folder.
    Returns list of file/folder dicts.
    """
    token, user = authenticate()
    if not token:
        return []

    # Get root folder ID from user data if needed
    if folder_id is None:
        folder_id = user.get('root_folder_id') if user else None
        if not folder_id:
            print("[Internxt] Cannot determine root folder ID")
            return []

    try:
        r = requests.get(
            f'{API_BASE}/api/storage/v2/folder/{folder_id}',
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )

        if r.status_code != 200:
            print(f"[Internxt] list_folder failed: HTTP {r.status_code}")
            return []

        data = r.json()
        files = data.get('files', [])
        children = data.get('children', [])  # subfolders

        items = []
        for f in files:
            items.append({
                'name': f.get('name', '') + ('.' + f.get('type', '') if f.get('type') else ''),
                'file_id': f.get('fileId') or f.get('id'),
                'size': f.get('size', 0),
                'is_folder': False,
                'created_at': f.get('createdAt', ''),
                'updated_at': f.get('updatedAt', ''),
                'bucket': f.get('bucket', ''),
            })

        for c in children:
            items.append({
                'name': c.get('name', ''),
                'folder_id': c.get('id'),
                'is_folder': True,
                'created_at': c.get('createdAt', ''),
            })

        return items

    except Exception as e:
        print(f"[Internxt] list_folder error: {e}")
        return []


def list_videos(folder_id=None):
    """List only video files in a folder."""
    items = list_folder(folder_id)
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v'}
    return [
        item for item in items
        if not item.get('is_folder')
        and os.path.splitext(item.get('name', ''))[1].lower() in video_exts
    ]


def get_download_link(file_id):
    """
    Get a download link for a file.
    Internxt files are encrypted, so this returns a link to the encrypted file.
    The client must decrypt after download.
    """
    token, _ = authenticate()
    if not token:
        return None

    try:
        r = requests.get(
            f'{API_BASE}/api/storage/file/{file_id}',
            headers={'Authorization': f'Bearer {token}'},
            timeout=30,
        )

        if r.status_code == 200:
            return r.json()
        print(f"[Internxt] get_download_link failed: HTTP {r.status_code}")
        return None

    except Exception as e:
        print(f"[Internxt] get_download_link error: {e}")
        return None


def download_file(file_id, dest_path, file_name=None):
    """
    Download a file from Internxt.

    Note: Internxt uses encryption. For files uploaded via the web UI,
    the download endpoint handles decryption server-side when using
    the correct auth token.

    Returns local file path on success, or None.
    """
    token, _ = authenticate()
    if not token:
        return None

    try:
        # Try the direct download endpoint
        r = requests.get(
            f'{API_BASE}/api/storage/file/{file_id}/download',
            headers={'Authorization': f'Bearer {token}'},
            stream=True,
            timeout=7200,
        )

        if r.status_code != 200:
            print(f"[Internxt] Download failed: HTTP {r.status_code}")
            return None

        total = int(r.headers.get('content-length', 0))
        downloaded = 0

        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = (downloaded / total) * 100
                    if pct % 10 < (8 * 1024 * 1024 / total * 100):
                        print(f"  [Internxt] Download: {pct:.0f}%")

        print(f"  [Internxt] Downloaded: {os.path.getsize(dest_path) / 1024 / 1024:.1f} MB")
        return dest_path

    except Exception as e:
        print(f"  [Internxt] Download error: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        token, user = authenticate()
        if token:
            print(f"Token: {token[:30]}...")
            root_id = user.get('root_folder_id') if user else None
            print(f"Root folder ID: {root_id}")
            items = list_folder()
            print(f"\nRoot folder ({len(items)} items):")
            for item in items:
                kind = "DIR" if item.get('is_folder') else "FILE"
                if item.get('is_folder'):
                    print(f"  [{kind}] {item['name']}/")
                else:
                    print(f"  [{kind}] {item['name']}  ({item.get('size', 0) / 1024 / 1024:.1f} MB)")
        else:
            print("Auth failed")
    elif len(sys.argv) > 1 and sys.argv[1] == '--videos':
        folder_id = sys.argv[2] if len(sys.argv) > 2 else None
        videos = list_videos(folder_id)
        print(f"Videos ({len(videos)}):")
        for v in videos:
            print(f"  {v['name']}  ({v.get('size', 0) / 1024 / 1024:.1f} MB)")
    else:
        print("Usage:")
        print("  python internxt_client.py --test       # Test auth + list root")
        print("  python internxt_client.py --videos     # List videos in root")
