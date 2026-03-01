#!/usr/bin/env python3
"""
Watcher: pCloud -> Bilibili

Monitors pCloud for new video files uploaded by Darius (2020 videos).
When a new file is detected, downloads it and uploads to Bilibili.

NOTE: Bilibili uploader is ON HOLD — dev hasn't started loading yet.
This watcher is ready for when Bilibili credentials are available.
For now, it can run in monitoring-only mode to track what Darius uploads.

Designed to run as a systemd service on the VPS.

Flow:
  1. Poll pCloud every POLL_INTERVAL seconds
  2. Compare file list against archive (already-transferred files)
  3. For each new file: download from pCloud -> upload to Bilibili
  4. Update Google Sheet + send Telegram notification
  5. Add to archive file

Usage:
  python watcher_pcloud_to_bilibili.py               # Run watcher loop
  python watcher_pcloud_to_bilibili.py --once          # Run once and exit
  python watcher_pcloud_to_bilibili.py --monitor       # Monitor only (no upload)
  python watcher_pcloud_to_bilibili.py --test          # Test pCloud connection
"""

import os
import sys
import time
import json
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pcloud_client import authenticate as pcloud_auth, list_folder as pcloud_list, list_videos as pcloud_list_videos, download_file as pcloud_download
from bilibili_client import upload_to_bilibili, has_credentials as bilibili_has_creds
from notifier import send_telegram_message, update_sheet_platform
from config import DOWNLOAD_DIR

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL = 300  # 5 minutes
YEAR = "2020"
# Darius uploaded to: /2020 Messages/Encoded/ (34 videos, ~2.6-19.5 GB each)
# and /2020 Messages/REVIVAL SERVICES/ (2 videos)
PCLOUD_WATCH_FOLDER_ID = 30551569266  # "2020 Messages/Encoded" folder
PCLOUD_REVIVAL_FOLDER_ID = 30553303280  # "2020 Messages/REVIVAL SERVICES" folder

ARCHIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'transfer_pcloud_bilibili_{YEAR}.json')
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'watcher_state_pcloud_{YEAR}.json')

# Auto-detect if Bilibili upload is available (cookies configured)
BILIBILI_ENABLED = bilibili_has_creds()

_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    print(f"\n[Watcher] Received signal {sig}, shutting down gracefully...")
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# ---------------------------------------------------------------------------
# Archive management
# ---------------------------------------------------------------------------
def _load_archive():
    if not os.path.exists(ARCHIVE_FILE):
        return {}
    try:
        with open(ARCHIVE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_archive(archive):
    with open(ARCHIVE_FILE, 'w') as f:
        json.dump(archive, f, indent=2)


def _save_state(state):
    state['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Transfer logic
# ---------------------------------------------------------------------------
def transfer_file(file_info, archive):
    """Download from pCloud and upload to Bilibili."""
    file_id = str(file_info.get('fileid', file_info.get('file_id', '')))
    file_name = file_info.get('name', f'unknown_{file_id}')
    file_size = file_info.get('size', 0)

    print(f"\n[Transfer] Starting: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

    local_path = os.path.join(DOWNLOAD_DIR, file_name)

    try:
        # Step 1: Download from pCloud
        print(f"[Transfer] Step 1: Downloading from pCloud...")
        result = pcloud_download(file_id=int(file_id), dest_path=local_path)
        if not result:
            print(f"[Transfer] Download failed: {file_name}")
            send_telegram_message(
                f"❌ <b>Transfer Failed (Download)</b>\n"
                f"pCloud → Bilibili\n"
                f"{file_name}\n"
                f"Could not download from pCloud"
            )
            return False

        actual_size = os.path.getsize(local_path)
        print(f"[Transfer] Downloaded: {actual_size / 1024 / 1024:.1f} MB")

        # Step 2: Upload to Bilibili (when enabled)
        title = os.path.splitext(file_name)[0]  # Use filename as title
        if BILIBILI_ENABLED:
            print(f"[Transfer] Step 2: Uploading to Bilibili...")
            result = upload_to_bilibili(local_path, title, description=title)
            if result == "RATE_LIMITED":
                print(f"[Transfer] Daily upload limit reached, will retry tomorrow")
                send_telegram_message(
                    f"⏸ <b>Bilibili Daily Limit</b>\n"
                    f"Reached {3}/day limit. Resuming tomorrow.\n"
                    f"Queued: {file_name}"
                )
                return False  # Don't mark as done, retry next cycle
            success = bool(result)
            if success:
                update_sheet_platform("", title, "Bilibili", "Uploaded", "", year=YEAR)
            else:
                update_sheet_platform("", title, "Bilibili", "Failed", "", year=YEAR)
        else:
            print(f"[Transfer] Step 2: Bilibili upload DISABLED — monitoring only")
            print(f"  To enable: run 'biliup login' or add cookies to bilibili_cookies.json")
            success = True  # Mark as "seen" in monitor mode

        # Step 3: Update archive
        archive[file_id] = {
            'name': file_name,
            'size': actual_size,
            'detected_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'bilibili_uploaded': BILIBILI_ENABLED and success,
        }
        _save_archive(archive)

        # Step 4: Notify
        if BILIBILI_ENABLED and success:
            send_telegram_message(
                f"✅ <b>Transfer Complete</b>\n"
                f"pCloud → Bilibili ({YEAR})\n"
                f"📁 {file_name}"
            )
        else:
            send_telegram_message(
                f"👁 <b>New File Detected</b>\n"
                f"pCloud ({YEAR})\n"
                f"📁 {file_name}\n"
                f"📦 {actual_size / 1024 / 1024:.1f} MB\n"
                f"⏳ Bilibili upload pending"
            )

        return True

    except Exception as e:
        print(f"[Transfer] Error: {e}")
        return False

    finally:
        # Only clean up if upload succeeded or we're in monitor mode
        if os.path.exists(local_path) and (not BILIBILI_ENABLED or success):
            try:
                os.remove(local_path)
            except Exception:
                pass


def check_and_transfer():
    """Check pCloud for new files and process them."""
    print(f"\n[Watcher] Checking pCloud for new files ({YEAR})...")

    archive = _load_archive()
    known_ids = set(archive.keys())

    # List videos in both pCloud watch folders
    from pcloud_client import list_folder as pcloud_list_raw
    videos = []
    for fid in [PCLOUD_WATCH_FOLDER_ID, PCLOUD_REVIVAL_FOLDER_ID]:
        items = pcloud_list_raw(folder_id=fid)
        video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v'}
        for item in items:
            if not item.get('isfolder') and os.path.splitext(item.get('name', ''))[1].lower() in video_exts:
                videos.append(item)

    if not videos:
        print("[Watcher] No videos found or auth failed")
        return 0, 0, 0

    # Find new ones
    new_videos = [
        v for v in videos
        if str(v.get('fileid', '')) not in known_ids
    ]

    if not new_videos:
        print(f"[Watcher] No new videos ({len(known_ids)} already tracked)")
        return 0, 0, 0

    print(f"[Watcher] Found {len(new_videos)} new videos")

    success = 0
    fails = 0

    for i, video in enumerate(new_videos, 1):
        if _shutdown:
            break

        print(f"\n{'='*60}")
        print(f"[Watcher] Processing {i}/{len(new_videos)}: {video['name']}")
        print(f"{'='*60}")

        if transfer_file(video, archive):
            success += 1
        else:
            fails += 1

    return len(new_videos), success, fails


def scan_subfolders():
    """
    Recursively scan pCloud for video files across all folders.
    Useful for initial discovery when we don't know Darius's folder structure.
    """
    print("[Watcher] Scanning pCloud folder structure...")
    token = pcloud_auth()
    if not token:
        return

    from pcloud_client import list_folder

    def _scan(path, depth=0):
        indent = "  " * depth
        items = list_folder(path)
        for item in items:
            if item.get('isfolder'):
                print(f"{indent}📁 {item['name']}/")
                if depth < 3:  # Don't go too deep
                    _scan(f"{path.rstrip('/')}/{item['name']}", depth + 1)
            else:
                size_mb = item.get('size', 0) / 1024 / 1024
                print(f"{indent}📄 {item['name']} ({size_mb:.1f} MB)")

    _scan("/")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_watcher():
    mode = "MONITOR ONLY" if not BILIBILI_ENABLED else "FULL TRANSFER"
    print(f"[Watcher] Starting pCloud -> Bilibili watcher for {YEAR}")
    print(f"[Watcher] Mode: {mode}")
    print(f"[Watcher] Poll interval: {POLL_INTERVAL}s")

    send_telegram_message(
        f"🔄 <b>Watcher Started</b>\n"
        f"pCloud → Bilibili ({YEAR})\n"
        f"Mode: {mode}\n"
        f"Polling every {POLL_INTERVAL // 60} min"
    )

    cycle = 0
    while not _shutdown:
        cycle += 1
        state = {'cycle': cycle, 'status': 'checking', 'mode': mode}
        _save_state(state)

        try:
            new_count, success, fails = check_and_transfer()
            state.update({
                'status': 'idle',
                'last_check': time.strftime('%Y-%m-%d %H:%M:%S'),
                'new_found': new_count,
                'success': success,
                'fails': fails,
            })
            _save_state(state)
        except Exception as e:
            print(f"[Watcher] Cycle error: {e}")
            state.update({'status': 'error', 'error': str(e)[:200]})
            _save_state(state)

        if _shutdown:
            break

        for _ in range(POLL_INTERVAL):
            if _shutdown:
                break
            time.sleep(1)

    print("[Watcher] Shut down cleanly")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        print("Testing pCloud connection...")
        token = pcloud_auth()
        if token:
            print(f"  Auth OK")
            videos = pcloud_list_videos("/")
            print(f"  Root videos: {len(videos)}")
            for v in videos[:5]:
                print(f"    {v['name']} ({v.get('size', 0) / 1024 / 1024:.1f} MB)")
        else:
            print("  Auth FAILED")

    elif len(sys.argv) > 1 and sys.argv[1] == '--scan':
        scan_subfolders()

    elif len(sys.argv) > 1 and sys.argv[1] == '--once':
        new, success, fails = check_and_transfer()
        print(f"\nResult: {new} new, {success} success, {fails} failed")

    elif len(sys.argv) > 1 and sys.argv[1] == '--monitor':
        BILIBILI_ENABLED = False
        run_watcher()

    else:
        run_watcher()
