"""
Upload YouTube playlist videos to Dailymotion.
Downloads each video via pytubefix, uploads to Dailymotion API,
with rate-limit handling and Telegram notifications.

Usage:
  python run_dailymotion.py 2000
  python run_dailymotion.py 2003
"""
import os
import sys
import json
import time
import re
from pytubefix import Playlist

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import YOUTUBE_PLAYLIST_URL_2000, YOUTUBE_PLAYLIST_URL_2003
from downloader import download_video
from uploader_dailymotion import upload_to_dailymotion
from notifier import send_telegram_message, update_google_sheet, update_sheet_platform, notify_upload_success, notify_upload_failed

YEAR = "2000"

YEAR_CONFIG = {
    "2000": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2000",
    },
    "2003": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2003",
    },
}

DM_ARCHIVE = None
RATELIMIT_STATE_FILE = None

# How many times to retry a failed *download* before giving up on that video
MAX_DOWNLOAD_RETRIES = 2


def _save_ratelimit_state(video_id, title, index, paused_at):
    """Write rate-limit pause state to disk so we can resume after reboot."""
    state = {
        'video_id': video_id,
        'title': title,
        'index': index,
        'paused_at': paused_at,
        'resume_after': paused_at + 24 * 60 * 60,
    }
    with open(RATELIMIT_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    print(f"  Rate-limit state saved to {RATELIMIT_STATE_FILE}")


def _load_ratelimit_state():
    """Load rate-limit state. Returns dict or None."""
    if not os.path.exists(RATELIMIT_STATE_FILE):
        return None
    try:
        with open(RATELIMIT_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _clear_ratelimit_state():
    """Remove the rate-limit state file after successful resume."""
    if os.path.exists(RATELIMIT_STATE_FILE):
        os.remove(RATELIMIT_STATE_FILE)


def _handle_ratelimit_pause(video_id, title, index):
    """
    Save state, notify via Telegram, sleep until the 24h window resets,
    then clear state and return so the caller can retry the upload.
    """
    paused_at = time.time()
    _save_ratelimit_state(video_id, title, index, paused_at)

    msg = (
        f"<b>Dailymotion Daily Limit Reached</b>\n"
        f"Paused at: {title}\n"
        f"Sleeping for 24 hours ..."
    )
    print(msg)
    send_telegram_message(msg)

    time.sleep(24 * 60 * 60)
    _clear_ratelimit_state()
    send_telegram_message("Rate-limit sleep complete — resuming uploads")


def main():
    global YEAR, DM_ARCHIVE, RATELIMIT_STATE_FILE

    if len(sys.argv) > 1 and sys.argv[1] in YEAR_CONFIG:
        YEAR = sys.argv[1]

    DM_ARCHIVE = f'dm_archive_{YEAR}.txt'
    RATELIMIT_STATE_FILE = f'dm_ratelimit_state_{YEAR}.json'

    config = YEAR_CONFIG.get(YEAR)
    if not config:
        print(f"ERROR: No config for year {YEAR}")
        return

    print(f"Starting {YEAR} -> Dailymotion Transfer...")

    # --- Check for rate-limit resume ---
    rl_state = _load_ratelimit_state()
    if rl_state:
        remaining = rl_state['resume_after'] - time.time()
        if remaining > 0:
            print(f"Resuming from rate-limit pause. Sleeping {remaining / 3600:.1f}h more ...")
            send_telegram_message(
                f"Resuming from rate-limit pause. {remaining / 3600:.1f}h remaining ..."
            )
            time.sleep(remaining)
        _clear_ratelimit_state()
        print("Rate-limit cooldown finished, continuing batch.")

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

    send_telegram_message(f"<b>Starting {YEAR} -> Dailymotion</b>\n{total} videos to upload")

    # --- Read already uploaded ---
    if os.path.exists(DM_ARCHIVE):
        with open(DM_ARCHIVE) as f:
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
            notify_upload_failed(title, "Dailymotion", "Download failed (all methods)", i, total)
            failed_count += 1
            continue

        video_path = media_info['video_path']
        actual_title = media_info.get('title') or title  # Use exact YouTube title

        # --- Upload to Dailymotion (retries are inside upload_to_dailymotion) ---
        while True:
            dm_id = upload_to_dailymotion(video_path, actual_title, "")

            if dm_id == "RATE_LIMITED":
                _handle_ratelimit_pause(vid_id, actual_title, i)
                continue  # Retry this same video after sleeping

            break  # Success or permanent failure

        if dm_id and dm_id != "RATE_LIMITED":
            uploaded_count += 1
            dm_url = f"https://www.dailymotion.com/video/{dm_id}"

            # Mark as done
            with open(DM_ARCHIVE, 'a') as f:
                f.write(f"{vid_id}\n")

            # Update Google Sheet (DM columns only)
            update_sheet_platform(video_url, actual_title, "Dailymotion", "Uploaded", dm_url, year=YEAR)
            notify_upload_success(actual_title, "Dailymotion", uploaded_count, total)
        else:
            failed_count += 1
            update_sheet_platform(video_url, actual_title, "Dailymotion", "Failed", "", year=YEAR)
            notify_upload_failed(actual_title, "Dailymotion", "Upload failed", i, total)

        # --- Clean up downloaded file + metadata ---
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"  Cleaned up: {video_path}")

        base_path = os.path.splitext(video_path)[0]
        for ext in ['.info.json', '.jpg', '.webp', '.png']:
            meta_file = base_path + ext
            if os.path.exists(meta_file):
                os.remove(meta_file)

    # --- Final summary ---
    summary = (
        f"<b>{YEAR} -> Dailymotion Complete!</b>\n"
        f"Uploaded: {uploaded_count}/{total}\n"
        f"Failed: {failed_count}\n"
    )
    send_telegram_message(summary)
    print(f"\nDone! Uploaded: {uploaded_count}, Failed: {failed_count}")


if __name__ == "__main__":
    main()
