"""
Icedrive uploader via WebDAV protocol.

Icedrive WebDAV endpoint: https://webdav.icedrive.io/
Auth: email + Access Key (NOT regular password)
      Access Key is generated from: icedrive.net > Avatar > 2FA & Access > WebDAV
Requires paid plan for WebDAV access.

Used as the DESTINATION for Eniola's 2021 uploads (Internxt -> Icedrive).
"""

import os
import time
import requests
from requests.auth import HTTPBasicAuth
from config import ICEDRIVE_EMAIL, ICEDRIVE_PASSWORD, ICEDRIVE_WEBDAV_URL, ICEDRIVE_ACCESS_KEY

MAX_RETRIES = 3
RETRY_DELAY = 30
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks for progress reporting


def _get_auth():
    """Get HTTPBasicAuth for WebDAV. Uses Access Key if available, falls back to password."""
    webdav_password = ICEDRIVE_ACCESS_KEY or ICEDRIVE_PASSWORD
    if not ICEDRIVE_EMAIL or not webdav_password:
        print("[Icedrive] No credentials configured. WebDAV needs an Access Key.")
        print("  Generate one at: icedrive.net > Avatar > 2FA & Access > WebDAV")
        return None
    return HTTPBasicAuth(ICEDRIVE_EMAIL, webdav_password)


def test_connection():
    """Test WebDAV connection. Returns True if connected."""
    auth = _get_auth()
    if not auth:
        return False

    try:
        r = requests.request(
            'PROPFIND',
            ICEDRIVE_WEBDAV_URL,
            auth=auth,
            headers={'Depth': '0'},
            timeout=30,
        )
        if r.status_code in (200, 207):
            print("[Icedrive] WebDAV connection OK")
            return True
        print(f"[Icedrive] WebDAV connection failed: HTTP {r.status_code}")
        return False
    except Exception as e:
        print(f"[Icedrive] WebDAV connection error: {e}")
        return False


def list_folder(remote_path="/"):
    """
    List contents of a WebDAV folder.
    Returns list of dicts with name, size, is_folder, path.
    """
    auth = _get_auth()
    if not auth:
        return []

    url = ICEDRIVE_WEBDAV_URL.rstrip('/') + '/' + remote_path.strip('/')
    if not url.endswith('/'):
        url += '/'

    try:
        r = requests.request(
            'PROPFIND',
            url,
            auth=auth,
            headers={'Depth': '1'},
            timeout=30,
        )
        if r.status_code not in (200, 207):
            print(f"[Icedrive] PROPFIND failed: HTTP {r.status_code}")
            return []

        # Parse the XML response
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)

        # WebDAV namespace
        ns = {'d': 'DAV:'}
        items = []

        for response in root.findall('d:response', ns):
            href = response.find('d:href', ns)
            if href is None:
                continue

            path = href.text or ''
            name = path.rstrip('/').split('/')[-1]

            # Skip the folder itself
            if not name or path.rstrip('/') == url.rstrip('/').replace(ICEDRIVE_WEBDAV_URL.rstrip('/'), ''):
                continue

            propstat = response.find('d:propstat', ns)
            if propstat is None:
                continue

            prop = propstat.find('d:prop', ns)
            if prop is None:
                continue

            is_folder = prop.find('d:resourcetype/d:collection', ns) is not None
            size_el = prop.find('d:getcontentlength', ns)
            size = int(size_el.text) if size_el is not None and size_el.text else 0

            items.append({
                'name': name,
                'path': path,
                'is_folder': is_folder,
                'size': size,
            })

        return items

    except Exception as e:
        print(f"[Icedrive] list_folder error: {e}")
        return []


def create_folder(remote_path):
    """Create a folder on Icedrive via WebDAV MKCOL."""
    auth = _get_auth()
    if not auth:
        return False

    url = ICEDRIVE_WEBDAV_URL.rstrip('/') + '/' + remote_path.strip('/')
    if not url.endswith('/'):
        url += '/'

    try:
        r = requests.request('MKCOL', url, auth=auth, timeout=30)
        if r.status_code in (201, 405):
            # 201 = created, 405 = already exists
            return True
        print(f"[Icedrive] MKCOL failed: HTTP {r.status_code}")
        return False
    except Exception as e:
        print(f"[Icedrive] create_folder error: {e}")
        return False


def upload_file(local_path, remote_path):
    """
    Upload a file to Icedrive via WebDAV PUT.
    Handles large files by streaming.

    Args:
        local_path: Path to local file
        remote_path: Destination path on Icedrive (e.g., "/Archive/2021/video.mp4")

    Returns True on success, False on failure.
    """
    auth = _get_auth()
    if not auth:
        return False

    if not os.path.exists(local_path):
        print(f"[Icedrive] File not found: {local_path}")
        return False

    file_size = os.path.getsize(local_path)
    url = ICEDRIVE_WEBDAV_URL.rstrip('/') + '/' + remote_path.strip('/')

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[Icedrive {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading {os.path.basename(local_path)} ({file_size / 1024 / 1024:.1f} MB)")

        try:
            with open(local_path, 'rb') as f:
                r = requests.put(
                    url,
                    data=f,
                    auth=auth,
                    headers={
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': str(file_size),
                    },
                    timeout=14400,  # 4 hours for very large files
                )

            if r.status_code in (200, 201, 204):
                print(f"{prefix} Upload SUCCESS: {remote_path}")
                return True

            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            print(f"{prefix} Upload failed: {last_error}")

            # Don't retry on auth errors
            if r.status_code in (401, 403):
                print(f"{prefix} Auth error — check credentials")
                return False

        except Exception as e:
            last_error = str(e)
            print(f"{prefix} Error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    print(f"[Icedrive] Upload failed after {MAX_RETRIES} attempts: {last_error}")
    return False


def file_exists(remote_path):
    """Check if a file exists on Icedrive."""
    auth = _get_auth()
    if not auth:
        return False

    url = ICEDRIVE_WEBDAV_URL.rstrip('/') + '/' + remote_path.strip('/')

    try:
        r = requests.request(
            'PROPFIND',
            url,
            auth=auth,
            headers={'Depth': '0'},
            timeout=15,
        )
        return r.status_code in (200, 207)
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        if test_connection():
            items = list_folder("/")
            print(f"\nRoot ({len(items)} items):")
            for item in items:
                kind = "DIR" if item['is_folder'] else "FILE"
                print(f"  [{kind}] {item['name']}  ({item['size'] / 1024 / 1024:.1f} MB)" if not item['is_folder'] else f"  [{kind}] {item['name']}/")
    elif len(sys.argv) > 1 and sys.argv[1] == '--list':
        folder = sys.argv[2] if len(sys.argv) > 2 else "/"
        items = list_folder(folder)
        for item in items:
            kind = "DIR" if item['is_folder'] else "FILE"
            print(f"  [{kind}] {item['name']}  {item['size'] / 1024 / 1024:.1f} MB" if not item['is_folder'] else f"  [{kind}] {item['name']}/")
    else:
        print("Usage:")
        print("  python icedrive_client.py --test     # Test WebDAV connection")
        print("  python icedrive_client.py --list /    # List folder contents")
