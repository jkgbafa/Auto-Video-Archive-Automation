"""
pCloud API client — list, download, and manage files.

pCloud API docs: https://docs.pcloud.com/
Auth: email/password -> auth token (valid ~1 week)
All API calls go to eapi.pcloud.com (EU) or api.pcloud.com (US).
pCloud is based in Switzerland so we use the EU endpoint.

Used as the SOURCE platform for Darius's 2020 uploads.
Automation monitors pCloud for new files and transfers to Bilibili.
"""

import os
import json
import time
import requests
from config import PCLOUD_EMAIL, PCLOUD_PASSWORD

# pCloud EU API (Switzerland-based)
API_BASE = "https://eapi.pcloud.com"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pcloud_token.json')

# Cache auth token in memory
_auth_cache = {'token': None, 'expires': 0}


def _save_token(auth_token, locationid=None):
    """Save auth token to disk."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'auth_token': auth_token,
            'locationid': locationid,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)


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


def authenticate(email=None, password=None):
    """
    Authenticate with pCloud API.
    Returns auth token string or None.
    """
    now = time.time()
    if _auth_cache['token'] and _auth_cache['expires'] > now:
        return _auth_cache['token']

    # Try saved token
    saved = _load_token()
    if saved:
        try:
            r = requests.get(f'{API_BASE}/userinfo', params={
                'auth': saved,
            }, timeout=15)
            if r.status_code == 200 and r.json().get('result') == 0:
                _auth_cache['token'] = saved
                _auth_cache['expires'] = now + 3600
                return saved
        except Exception:
            pass

    # Fresh login
    email = email or PCLOUD_EMAIL
    password = password or PCLOUD_PASSWORD
    if not email or not password:
        print("[pCloud] No credentials configured")
        return None

    try:
        r = requests.get(f'{API_BASE}/userinfo', params={
            'getauth': 1,
            'logout': 1,
            'username': email,
            'password': password,
            'authexpire': 604800,  # 1 week
        }, timeout=30)

        data = r.json()
        if data.get('result') != 0:
            print(f"[pCloud] Auth failed: {data.get('error', 'unknown')}")
            return None

        token = data.get('auth')
        if not token:
            print("[pCloud] No auth token in response")
            return None

        locationid = data.get('locationid')
        _save_token(token, locationid)
        _auth_cache['token'] = token
        _auth_cache['expires'] = now + 3600
        print(f"[pCloud] Authenticated as {email}")
        return token

    except Exception as e:
        print(f"[pCloud] Auth error: {e}")
        return None


def list_folder(folder_path="/", folder_id=None):
    """
    List contents of a pCloud folder.
    Returns list of file/folder dicts, or empty list.

    Each item has: name, isfolder, fileid/folderid, size, modified, contenttype
    """
    token = authenticate()
    if not token:
        return []

    params = {'auth': token}
    if folder_id is not None:
        params['folderid'] = folder_id
    else:
        params['path'] = folder_path

    try:
        r = requests.get(f'{API_BASE}/listfolder', params=params, timeout=30)
        data = r.json()

        if data.get('result') != 0:
            print(f"[pCloud] listfolder error: {data.get('error', 'unknown')}")
            return []

        contents = data.get('metadata', {}).get('contents', [])
        return contents

    except Exception as e:
        print(f"[pCloud] listfolder error: {e}")
        return []


def list_videos(folder_path="/", folder_id=None):
    """List only video files in a folder."""
    items = list_folder(folder_path, folder_id)
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v'}
    return [
        item for item in items
        if not item.get('isfolder')
        and os.path.splitext(item.get('name', ''))[1].lower() in video_exts
    ]


def get_download_link(file_id=None, file_path=None):
    """
    Get a direct download link for a file.
    Returns URL string or None.
    """
    token = authenticate()
    if not token:
        return None

    params = {'auth': token}
    if file_id is not None:
        params['fileid'] = file_id
    elif file_path:
        params['path'] = file_path
    else:
        return None

    try:
        r = requests.get(f'{API_BASE}/getfilelink', params=params, timeout=30)
        data = r.json()

        if data.get('result') != 0:
            print(f"[pCloud] getfilelink error: {data.get('error', 'unknown')}")
            return None

        hosts = data.get('hosts', [])
        path = data.get('path', '')
        if hosts and path:
            return f"https://{hosts[0]}{path}"
        return None

    except Exception as e:
        print(f"[pCloud] getfilelink error: {e}")
        return None


def download_file(file_id=None, file_path=None, dest_path=None):
    """
    Download a file from pCloud to local disk.
    Returns local file path on success, or None.
    """
    url = get_download_link(file_id=file_id, file_path=file_path)
    if not url:
        return None

    if not dest_path:
        # Use a temp directory
        from config import DOWNLOAD_DIR
        dest_path = os.path.join(DOWNLOAD_DIR, f"pcloud_{file_id or 'file'}.mp4")

    try:
        print(f"  [pCloud] Downloading to {dest_path}...")
        r = requests.get(url, stream=True, timeout=7200)
        r.raise_for_status()

        total = int(r.headers.get('content-length', 0))
        downloaded = 0

        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = (downloaded / total) * 100
                    if pct % 10 < (8 * 1024 * 1024 / total * 100):
                        print(f"  [pCloud] Download: {pct:.0f}%")

        print(f"  [pCloud] Downloaded: {os.path.getsize(dest_path) / 1024 / 1024:.1f} MB")
        return dest_path

    except Exception as e:
        print(f"  [pCloud] Download error: {e}")
        if dest_path and os.path.exists(dest_path):
            os.remove(dest_path)
        return None


def create_folder(folder_name, parent_path="/", parent_id=None):
    """Create a folder on pCloud. Returns folder metadata or None."""
    token = authenticate()
    if not token:
        return None

    params = {'auth': token, 'name': folder_name}
    if parent_id is not None:
        params['folderid'] = parent_id
    else:
        params['path'] = parent_path

    try:
        r = requests.get(f'{API_BASE}/createfolder', params=params, timeout=30)
        data = r.json()
        if data.get('result') == 0:
            return data.get('metadata')
        elif data.get('result') == 2004:
            # Folder already exists
            return True
        print(f"[pCloud] createfolder error: {data.get('error', 'unknown')}")
        return None
    except Exception as e:
        print(f"[pCloud] createfolder error: {e}")
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        token = authenticate()
        if token:
            print(f"Token: {token[:20]}...")
            items = list_folder("/")
            print(f"\nRoot folder ({len(items)} items):")
            for item in items:
                kind = "DIR" if item.get('isfolder') else "FILE"
                size = item.get('size', 0)
                print(f"  [{kind}] {item['name']}  ({size / 1024 / 1024:.1f} MB)" if not item.get('isfolder') else f"  [{kind}] {item['name']}/")
        else:
            print("Auth failed")
    elif len(sys.argv) > 1 and sys.argv[1] == '--videos':
        folder = sys.argv[2] if len(sys.argv) > 2 else "/"
        videos = list_videos(folder)
        print(f"Videos in {folder} ({len(videos)}):")
        for v in videos:
            print(f"  {v['name']}  ({v.get('size', 0) / 1024 / 1024:.1f} MB)")
    else:
        print("Usage:")
        print("  python pcloud_client.py --test       # Test auth + list root")
        print("  python pcloud_client.py --videos /    # List videos in folder")
