"""
Upload all Year 2000 videos to Rumble.
Reads the YouTube playlist, downloads each video, uploads to Rumble,
updates Google Sheets, and sends Telegram progress notifications.

Features:
  - Persistent archive file tracks completed uploads
  - Download retries (Cobalt API + yt-dlp fallback)
  - Upload retries (inside uploader_rumble.py)
  - Telegram notifications for progress/failures
  - Google Sheets tracking
"""
import os
import sys
import json
import time
import re
import subprocess

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (YOUTUBE_PLAYLIST_URL_1999, YOUTUBE_PLAYLIST_URL_2000,
                     YOUTUBE_PLAYLIST_URL_2001, YOUTUBE_PLAYLIST_URL_2002,
                     YOUTUBE_PLAYLIST_URL_2003, RUMBLE_CHANNEL_NAME)
from downloader import download_video, YTDLP_VENV_PYTHON
from uploader_rumble import upload_to_rumble
from notifier import send_telegram_message, update_google_sheet, update_sheet_platform, notify_upload_success, notify_upload_failed

# Can be overridden via command line: python run_rumble.py 2003
YEAR = "2000"

# Map years to playlist URLs and Rumble channel names
YEAR_CONFIG = {
    "1999": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_1999",
        "channel": "1999",
    },
    "2000": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2000",
        "channel": "2000",
    },
    "2001": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2001",
        "channel": "2001",
    },
    "2002": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2002",
        "channel": "2002",
    },
    "2003": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2003",
        "channel": "2003archivedhmm",
    },
}

RUMBLE_ARCHIVE = None  # Set in main() based on YEAR

# How many times to retry a failed download before giving up
MAX_DOWNLOAD_RETRIES = 2


def main():
    global YEAR, RUMBLE_ARCHIVE

    # Allow year override via command line
    if len(sys.argv) > 1 and sys.argv[1] in YEAR_CONFIG:
        YEAR = sys.argv[1]

    RUMBLE_ARCHIVE = f'rumble_archive_{YEAR}.txt'

    config = YEAR_CONFIG.get(YEAR)
    if not config:
        print(f"ERROR: No config for year {YEAR}. Available: {list(YEAR_CONFIG.keys())}")
        return

    print(f"Starting {YEAR} -> Rumble Transfer...")
    print(f"  Channel: {config['channel']}")

    # Override the Rumble channel name for this run
    import config as cfg
    cfg.RUMBLE_CHANNEL_NAME = config['channel']

    # --- Extract playlist via yt-dlp ---
    playlist_url = os.getenv(config['playlist_env'], '')
    if not playlist_url:
        print(f"ERROR: {config['playlist_env']} not configured in .env")
        return

    print(f"Fetching playlist: {playlist_url}")
    cmd = [
        YTDLP_VENV_PYTHON, "-m", "yt_dlp",
        "--flat-playlist",
        "--print-json",
        "--no-warnings",
        playlist_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"ERROR: Failed to extract playlist: {result.stderr[-300:]}")
        return

    entries = []
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            vid_id = data.get('id', 'unknown')
            title = data.get('title', vid_id)
            url = data.get('url') or data.get('webpage_url') or f'https://www.youtube.com/watch?v={vid_id}'
            entries.append({'id': vid_id, 'url': url, 'title': title})
        except json.JSONDecodeError:
            continue

    total = len(entries)
    print(f"Total videos: {total}")

    send_telegram_message(
        f"<b>Starting {YEAR} -> Rumble</b>\n"
        f"{total} videos to upload"
    )

    # --- Read already uploaded ---
    if os.path.exists(RUMBLE_ARCHIVE):
        with open(RUMBLE_ARCHIVE) as f:
            done_ids = set(f.read().splitlines())
    else:
        done_ids = set()

    uploaded_count = len(done_ids)
    failed_count = 0

    for i, entry in enumerate(entries, 1):
        vid_id = entry['id']
        title = entry.get('title', vid_id)
        video_url = entry.get('url', f'https://www.youtube.com/watch?v={vid_id}')

        if vid_id in done_ids:
            print(f"[{i}/{total}] Already done: {title}")
            continue

        print(f"\n[{i}/{total}] Processing: {title}")

        # --- Download (with retries) ---
        media_info = None
        for dl_attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
            media_info = download_video(video_url)
            if media_info and media_info.get('video_path'):
                break
            print(f"  Download attempt {dl_attempt}/{MAX_DOWNLOAD_RETRIES} failed")
            if dl_attempt < MAX_DOWNLOAD_RETRIES:
                time.sleep(10)

        if not media_info or not media_info.get('video_path'):
            print(f"  Download permanently failed!")
            notify_upload_failed(title, "Rumble", "Download failed (all methods)", i, total)
            failed_count += 1
            continue

        video_path = media_info['video_path']
        actual_title = media_info.get('title') or title
        description = media_info.get('description', '')

        # --- Upload to Rumble (retries are inside upload_to_rumble) ---
        tags = ['sermon', 'church', 'daghewardmills']
        success = upload_to_rumble(video_path, actual_title, description, tags)

        if success:
            uploaded_count += 1

            # Mark as done
            with open(RUMBLE_ARCHIVE, 'a') as f:
                f.write(f"{vid_id}\n")

            # Update Google Sheet
            update_sheet_platform(video_url, actual_title, "Rumble", "Uploaded", "", year=YEAR)
            notify_upload_success(actual_title, "Rumble", uploaded_count, total)
        else:
            failed_count += 1
            notify_upload_failed(actual_title, "Rumble", "Upload failed", i, total)

        # --- Clean up downloaded file ---
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"  Cleaned up: {video_path}")

        # Also clean up any metadata files
        base_path = os.path.splitext(video_path)[0]
        for ext in ['.info.json', '.jpg', '.webp', '.png']:
            meta_file = base_path + ext
            if os.path.exists(meta_file):
                os.remove(meta_file)

    # --- Final summary ---
    summary = (
        f"<b>{YEAR} -> Rumble Complete!</b>\n"
        f"Uploaded: {uploaded_count}/{total}\n"
        f"Failed: {failed_count}\n"
    )
    send_telegram_message(summary)
    print(f"\nDone! Uploaded: {uploaded_count}, Failed: {failed_count}")


if __name__ == "__main__":
    main()
