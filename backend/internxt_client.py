"""
Internxt client — uses the official Internxt CLI for file operations.

Internxt uses end-to-end encryption with OPAQUE protocol for auth,
making direct API calls impractical. The official CLI handles all
encryption/decryption transparently.

Requirements:
  npm install -g @internxt/cli
  npx internxt login-legacy --email EMAIL --password PASS

Used as the SOURCE platform for Eniola's 2021 uploads.
Automation monitors Internxt for new files and transfers to Icedrive.

CLI Commands used:
  internxt login-legacy  — authenticate with email/password
  internxt list          — list folder contents
  internxt download-file — download and decrypt a file
  internxt config        — show current user info
"""

import os
import json
import time
import subprocess
from config import INTERNXT_EMAIL, INTERNXT_PASSWORD, DOWNLOAD_DIR

# Check if logged in by running `internxt config`
_logged_in = None


def _run_cli(args, timeout=120):
    """Run an Internxt CLI command and return (success, stdout, stderr)."""
    cmd = ['npx', 'internxt'] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        print(f"[Internxt] CLI timeout ({timeout}s): {' '.join(args)}")
        return False, '', 'timeout'
    except FileNotFoundError:
        print("[Internxt] CLI not found. Install with: npm install -g @internxt/cli")
        return False, '', 'not found'
    except Exception as e:
        print(f"[Internxt] CLI error: {e}")
        return False, '', str(e)


def is_logged_in():
    """Check if we're currently logged into Internxt CLI."""
    global _logged_in
    if _logged_in is not None:
        return _logged_in

    ok, stdout, _ = _run_cli(['config'], timeout=15)
    if ok and 'email' in stdout.lower():
        _logged_in = True
        print(f"[Internxt] CLI logged in")
        return True
    _logged_in = False
    return False


def login(email=None, password=None):
    """
    Login to Internxt via CLI.
    Uses login-legacy (email + password) method.
    Returns True on success.
    """
    global _logged_in
    email = email or INTERNXT_EMAIL
    password = password or INTERNXT_PASSWORD

    if not email or not password:
        print("[Internxt] No credentials configured")
        return False

    if is_logged_in():
        return True

    print(f"[Internxt] Logging in as {email}...")
    ok, stdout, stderr = _run_cli([
        'login-legacy',
        '--email', email,
        '--password', password,
    ], timeout=60)

    if ok:
        _logged_in = True
        print(f"[Internxt] Login successful")
        return True

    print(f"[Internxt] Login failed: {stderr[:200]}")
    _logged_in = False
    return False


def list_folder(folder_id=None):
    """
    List contents of an Internxt folder.
    Returns list of dicts with name, is_folder, id, size info.
    """
    if not login():
        return []

    args = ['list']
    if folder_id:
        args.extend(['--id', str(folder_id)])

    ok, stdout, stderr = _run_cli(args, timeout=60)
    if not ok:
        print(f"[Internxt] list failed: {stderr[:200]}")
        return []

    # Parse CLI output (format varies by version)
    items = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith('─') or line.startswith('┌') or line.startswith('└'):
            continue

        # Try to parse structured output
        # The CLI outputs a table with: Type | Name | Size | Modified
        parts = [p.strip() for p in line.split('│') if p.strip()]
        if len(parts) >= 2:
            item_type = parts[0].lower() if len(parts) > 0 else ''
            name = parts[1] if len(parts) > 1 else ''
            size = parts[2] if len(parts) > 2 else '0'

            if 'folder' in item_type:
                items.append({
                    'name': name,
                    'is_folder': True,
                    'folder_id': None,  # CLI doesn't always show IDs
                })
            elif name and 'type' not in name.lower() and 'name' not in name.lower():
                items.append({
                    'name': name,
                    'is_folder': False,
                    'file_id': None,
                    'size': _parse_size(size),
                })

    # If table parsing didn't work, try line-by-line
    if not items:
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Simple heuristic: folders end with /
            if line.endswith('/'):
                items.append({'name': line.rstrip('/'), 'is_folder': True})
            elif '.' in line:
                items.append({'name': line, 'is_folder': False, 'size': 0})

    return items


def _parse_size(size_str):
    """Parse human-readable size like '1.5 GB' to bytes."""
    try:
        size_str = size_str.strip().upper()
        if 'GB' in size_str:
            return float(size_str.replace('GB', '').strip()) * 1024 ** 3
        elif 'MB' in size_str:
            return float(size_str.replace('MB', '').strip()) * 1024 ** 2
        elif 'KB' in size_str:
            return float(size_str.replace('KB', '').strip()) * 1024
        elif 'B' in size_str:
            return float(size_str.replace('B', '').strip())
        return float(size_str) if size_str else 0
    except (ValueError, AttributeError):
        return 0


def list_videos(folder_id=None):
    """List only video files in a folder."""
    items = list_folder(folder_id)
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v'}
    return [
        item for item in items
        if not item.get('is_folder')
        and os.path.splitext(item.get('name', ''))[1].lower() in video_exts
    ]


def download_file(file_id, dest_path, file_name=None):
    """
    Download a file from Internxt using the CLI.
    The CLI handles decryption automatically.

    Args:
        file_id: The file ID (from list output) or None if downloading by name
        dest_path: Local path to save to
        file_name: Optional filename for logging

    Returns local file path on success, or None.
    """
    if not login():
        return None

    dest_dir = os.path.dirname(dest_path) or DOWNLOAD_DIR
    os.makedirs(dest_dir, exist_ok=True)

    args = ['download-file']
    if file_id:
        args.extend(['--id', str(file_id)])

    args.extend(['--directory', dest_dir])

    display_name = file_name or file_id or 'unknown'
    print(f"[Internxt] Downloading: {display_name}")

    ok, stdout, stderr = _run_cli(args, timeout=7200)  # 2 hour timeout for large files

    if ok:
        # Check if file appeared in dest_dir
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
            size_mb = os.path.getsize(dest_path) / 1024 / 1024
            print(f"[Internxt] Downloaded: {size_mb:.1f} MB -> {dest_path}")
            return dest_path

        # Try to find the downloaded file (CLI uses original filename)
        if file_name:
            alt_path = os.path.join(dest_dir, file_name)
            if os.path.exists(alt_path) and os.path.getsize(alt_path) > 0:
                size_mb = os.path.getsize(alt_path) / 1024 / 1024
                print(f"[Internxt] Downloaded: {size_mb:.1f} MB -> {alt_path}")
                return alt_path

        print(f"[Internxt] Download appeared to succeed but file not found at {dest_path}")
        print(f"  stdout: {stdout[:200]}")
        return None

    print(f"[Internxt] Download failed: {stderr[:200]}")
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        print("Testing Internxt CLI...")
        if login():
            ok, stdout, _ = _run_cli(['config'])
            print(f"Config:\n{stdout}")
            print()
            items = list_folder()
            print(f"Root folder ({len(items)} items):")
            for item in items:
                kind = "DIR" if item.get('is_folder') else "FILE"
                name = item.get('name', '?')
                if item.get('is_folder'):
                    print(f"  [{kind}] {name}/")
                else:
                    size_mb = item.get('size', 0) / 1024 / 1024
                    print(f"  [{kind}] {name} ({size_mb:.1f} MB)")
        else:
            print("Login failed")

    elif len(sys.argv) > 1 and sys.argv[1] == '--videos':
        videos = list_videos()
        print(f"Videos ({len(videos)}):")
        for v in videos:
            print(f"  {v['name']} ({v.get('size', 0) / 1024 / 1024:.1f} MB)")

    elif len(sys.argv) > 1 and sys.argv[1] == '--login':
        login()

    else:
        print("Usage:")
        print("  python internxt_client.py --test     # Test CLI + list root")
        print("  python internxt_client.py --videos   # List video files")
        print("  python internxt_client.py --login    # Login to CLI")
        print()
        print("Prerequisites:")
        print("  npm install -g @internxt/cli")
