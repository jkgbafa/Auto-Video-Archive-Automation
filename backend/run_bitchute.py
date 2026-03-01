"""
Upload YouTube playlist videos to BitChute.
Downloads each video via pytubefix, uploads via Playwright browser automation.

Usage:
  python run_bitchute.py 2000
  python run_bitchute.py 2003
"""
import os
import sys
import json
import time
import re
from pytubefix import Playlist

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (YOUTUBE_PLAYLIST_URL_1999, YOUTUBE_PLAYLIST_URL_2000,
                     YOUTUBE_PLAYLIST_URL_2001, YOUTUBE_PLAYLIST_URL_2002,
                     YOUTUBE_PLAYLIST_URL_2003)
from downloader import download_video
from uploader_bitchute import upload_to_bitchute
from notifier import send_telegram_message, update_sheet_platform, notify_upload_success, notify_upload_failed

YEAR = "2000"

YEAR_CONFIG = {
    "1999": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_1999",
    },
    "2000": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2000",
    },
    "2001": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2001",
    },
    "2002": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2002",
    },
    "2003": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2003",
    },
}

MAX_DOWNLOAD_RETRIES = 2
BITCHUTE_ARCHIVE = None


def main():
    global YEAR, BITCHUTE_ARCHIVE

    if len(sys.argv) > 1 and sys.argv[1] in YEAR_CONFIG:
        YEAR = sys.argv[1]

    BITCHUTE_ARCHIVE = f'bitchute_archive_{YEAR}.txt'

    config = YEAR_CONFIG.get(YEAR)
    if not config:
        print(f"ERROR: No config for year {YEAR}")
        return

    print(f"Starting {YEAR} -> BitChute Transfer...")

    # --- Extract playlist ---
    playlist_url = os.getenv(config['playlist_env'], '')
    if not playlist_url:
        print(f"ERROR: {config['playlist_env']} not configured")
        return

    print(f"Fetching playlist: {playlist_url}")
    pl = Playlist(playlist_url)
    video_urls = list(pl.video_urls)

    entries = []
    for url in video_urls:
        match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
        vid_id = match.group(1) if match else 'unknown'
        entries.append({'id': vid_id, 'url': url, 'title': vid_id})

    total = len(entries)
    print(f"Total videos: {total}")

    send_telegram_message(
        f"<b>Starting {YEAR} -> BitChute</b>\n"
        f"{total} videos to upload"
    )

    # --- Read already uploaded ---
    if os.path.exists(BITCHUTE_ARCHIVE):
        with open(BITCHUTE_ARCHIVE) as f:
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

        # --- Download ---
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
            notify_upload_failed(title, "BitChute", "Download failed", i, total)
            failed_count += 1
            continue

        video_path = media_info['video_path']
        actual_title = media_info.get('title') or title
        description = media_info.get('description', '')
        thumb_path = media_info.get('thumb_path')

        # --- Upload to BitChute ---
        success = upload_to_bitchute(video_path, actual_title, description, thumb_path)

        if success:
            uploaded_count += 1
            with open(BITCHUTE_ARCHIVE, 'a') as f:
                f.write(f"{vid_id}\n")
            update_sheet_platform(video_url, actual_title, "BitChute", "Uploaded", "", year=YEAR)
            notify_upload_success(actual_title, "BitChute", uploaded_count, total)
        else:
            failed_count += 1
            update_sheet_platform(video_url, actual_title, "BitChute", "Failed", "", year=YEAR)
            notify_upload_failed(actual_title, "BitChute", "Upload failed", i, total)

        # --- Clean up ---
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"  Cleaned up: {video_path}")

        base_path = os.path.splitext(video_path)[0]
        for ext in ['.info.json', '.jpg', '.webp', '.png']:
            meta_file = base_path + ext
            if os.path.exists(meta_file):
                os.remove(meta_file)

    # --- Summary ---
    summary = (
        f"<b>{YEAR} -> BitChute Complete!</b>\n"
        f"Uploaded: {uploaded_count}/{total}\n"
        f"Failed: {failed_count}\n"
    )
    send_telegram_message(summary)
    print(f"\nDone! Uploaded: {uploaded_count}, Failed: {failed_count}")


if __name__ == "__main__":
    main()
