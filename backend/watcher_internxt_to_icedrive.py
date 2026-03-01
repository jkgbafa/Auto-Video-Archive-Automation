#!/usr/bin/env python3
"""
Watcher: Internxt -> Icedrive

Monitors Internxt for new video files uploaded by Eniola (2021 videos).
When a new file is detected, downloads it and uploads to Icedrive via WebDAV.

Designed to run as a systemd service on the VPS.

Flow:
  1. Poll Internxt every POLL_INTERVAL seconds
  2. Compare file list against archive (already-transferred files)
  3. For each new file: download from Internxt -> upload to Icedrive
  4. Update Google Sheet + send Telegram notification
  5. Add to archive file

Usage:
  python watcher_internxt_to_icedrive.py              # Run watcher loop
  python watcher_internxt_to_icedrive.py --once        # Run once and exit
  python watcher_internxt_to_icedrive.py --test        # Test connections only
"""

import os
import sys
import time
import json
import signal

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from internxt_client import authenticate as internxt_auth, list_folder as internxt_list, list_videos as internxt_list_videos, download_file as internxt_download
from icedrive_client import test_connection as icedrive_test, upload_file as icedrive_upload, create_folder as icedrive_mkdir, file_exists as icedrive_exists
from notifier import send_telegram_message, update_sheet_platform
from config import DOWNLOAD_DIR

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POLL_INTERVAL = 300  # 5 minutes between checks
YEAR = "2021"
DEST_FOLDER = f"/Archive/{YEAR}"  # Icedrive destination folder

ARCHIVE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'transfer_internxt_icedrive_{YEAR}.json')
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'watcher_state_internxt_{YEAR}.json')

# Graceful shutdown
_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    print(f"\n[Watcher] Received signal {sig}, shutting down gracefully...")
    _shutdown = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


# ---------------------------------------------------------------------------
# Archive management — tracks what's already been transferred
# ---------------------------------------------------------------------------
def _load_archive():
    """Load set of already-transferred file identifiers."""
    if not os.path.exists(ARCHIVE_FILE):
        return {}
    try:
        with open(ARCHIVE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_archive(archive):
    """Save archive to disk."""
    with open(ARCHIVE_FILE, 'w') as f:
        json.dump(archive, f, indent=2)


def _save_state(state):
    """Save watcher state for monitoring."""
    state['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Transfer logic
# ---------------------------------------------------------------------------
def transfer_file(file_info, archive):
    """
    Download a file from Internxt and upload to Icedrive.
    Returns True on success.
    """
    file_id = file_info.get('file_id')
    file_name = file_info.get('name', f'unknown_{file_id}')
    file_size = file_info.get('size', 0)

    print(f"\n[Transfer] Starting: {file_name} ({file_size / 1024 / 1024:.1f} MB)")

    # Local temp path
    local_path = os.path.join(DOWNLOAD_DIR, file_name)
    remote_path = f"{DEST_FOLDER}/{file_name}"

    try:
        # Step 1: Download from Internxt
        print(f"[Transfer] Step 1: Downloading from Internxt...")
        result = internxt_download(file_id, local_path, file_name)
        if not result:
            print(f"[Transfer] Download failed: {file_name}")
            send_telegram_message(
                f"❌ <b>Transfer Failed (Download)</b>\n"
                f"Internxt → Icedrive\n"
                f"{file_name}\n"
                f"Could not download from Internxt"
            )
            return False

        actual_size = os.path.getsize(local_path)
        print(f"[Transfer] Downloaded: {actual_size / 1024 / 1024:.1f} MB")

        # Step 2: Upload to Icedrive
        print(f"[Transfer] Step 2: Uploading to Icedrive...")
        success = icedrive_upload(local_path, remote_path)
        if not success:
            print(f"[Transfer] Upload failed: {file_name}")
            send_telegram_message(
                f"❌ <b>Transfer Failed (Upload)</b>\n"
                f"Internxt → Icedrive\n"
                f"{file_name}\n"
                f"Could not upload to Icedrive"
            )
            return False

        # Step 3: Update tracking
        archive[file_id] = {
            'name': file_name,
            'size': actual_size,
            'transferred_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        _save_archive(archive)

        # Step 4: Notify
        total_transferred = len(archive)
        send_telegram_message(
            f"✅ <b>Transfer Complete</b>\n"
            f"Internxt → Icedrive ({YEAR})\n"
            f"📁 {file_name}\n"
            f"📊 Total transferred: {total_transferred}"
        )

        print(f"[Transfer] SUCCESS: {file_name}")
        return True

    except Exception as e:
        print(f"[Transfer] Error: {e}")
        send_telegram_message(
            f"❌ <b>Transfer Error</b>\n"
            f"Internxt → Icedrive\n"
            f"{file_name}\n"
            f"{str(e)[:100]}"
        )
        return False

    finally:
        # Clean up temp file
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                print(f"[Transfer] Cleaned up: {local_path}")
            except Exception:
                pass


def check_and_transfer():
    """
    Check Internxt for new files and transfer any found.
    Returns (new_count, success_count, fail_count).
    """
    print(f"\n[Watcher] Checking Internxt for new files ({YEAR})...")

    archive = _load_archive()
    transferred_ids = set(archive.keys())

    # List all files in Internxt (root folder for now, can be changed to specific folder)
    all_items = internxt_list()
    if not all_items:
        print("[Watcher] No items found or auth failed")
        return 0, 0, 0

    # Filter to videos not yet transferred
    video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v'}
    new_videos = []
    for item in all_items:
        if item.get('is_folder'):
            continue
        file_id = str(item.get('file_id', ''))
        if file_id in transferred_ids:
            continue
        ext = os.path.splitext(item.get('name', ''))[1].lower()
        if ext in video_exts:
            new_videos.append(item)

    if not new_videos:
        print(f"[Watcher] No new videos found ({len(transferred_ids)} already transferred)")
        return 0, 0, 0

    print(f"[Watcher] Found {len(new_videos)} new videos to transfer")

    # Ensure destination folder exists on Icedrive
    icedrive_mkdir(DEST_FOLDER)

    success_count = 0
    fail_count = 0

    for i, video in enumerate(new_videos, 1):
        if _shutdown:
            print("[Watcher] Shutdown requested, stopping transfers")
            break

        print(f"\n{'='*60}")
        print(f"[Watcher] Processing {i}/{len(new_videos)}: {video['name']}")
        print(f"{'='*60}")

        if transfer_file(video, archive):
            success_count += 1
        else:
            fail_count += 1

    return len(new_videos), success_count, fail_count


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run_watcher():
    """Main watcher loop — runs until killed."""
    print(f"[Watcher] Starting Internxt -> Icedrive watcher for {YEAR}")
    print(f"[Watcher] Poll interval: {POLL_INTERVAL}s")
    print(f"[Watcher] Destination: Icedrive:{DEST_FOLDER}")

    send_telegram_message(
        f"🔄 <b>Watcher Started</b>\n"
        f"Internxt → Icedrive ({YEAR})\n"
        f"Polling every {POLL_INTERVAL // 60} min"
    )

    cycle = 0
    while not _shutdown:
        cycle += 1
        state = {'cycle': cycle, 'status': 'checking'}
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

        print(f"\n[Watcher] Sleeping {POLL_INTERVAL}s until next check...")
        # Sleep in small increments so we can respond to shutdown signal
        for _ in range(POLL_INTERVAL):
            if _shutdown:
                break
            time.sleep(1)

    print("[Watcher] Shut down cleanly")
    send_telegram_message(f"⏹ <b>Watcher Stopped</b>\nInternxt → Icedrive ({YEAR})")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        print("Testing connections...")
        print("\n--- Internxt ---")
        token, user = internxt_auth()
        if token:
            print(f"  Auth OK (token: {token[:20]}...)")
            items = internxt_list()
            print(f"  Root folder: {len(items)} items")
        else:
            print("  Auth FAILED")

        print("\n--- Icedrive ---")
        if icedrive_test():
            print("  WebDAV connection OK")
        else:
            print("  WebDAV connection FAILED")

    elif len(sys.argv) > 1 and sys.argv[1] == '--once':
        print("Running single check...")
        new, success, fails = check_and_transfer()
        print(f"\nResult: {new} new, {success} success, {fails} failed")

    else:
        run_watcher()
