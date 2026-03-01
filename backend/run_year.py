"""
Master runner: Upload a year's YouTube playlist to its assigned platforms.

THE CORRECT FLOW:
  1999: YouTube -> BitChute (C2) + Dailymotion (C3)
  2000: YouTube -> Rumble (C2) + Bilibili (C3)
  2001: YouTube -> Odysee (C2) + Internet Archive (C3)
  2002: YouTube -> BitChute (C2) + pCloud (C3)
  2003: YouTube -> Rumble (C2) + Dailymotion (C3)
  2004: YouTube -> Odysee (C2) + Bilibili (C3)

Usage:
  python run_year.py 1999
  python run_year.py 2000
  python run_year.py all     # Run all years sequentially
"""
import os
import sys
import json
import time
import re
import subprocess

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    YOUTUBE_PLAYLIST_URL_1999, YOUTUBE_PLAYLIST_URL_2000,
    YOUTUBE_PLAYLIST_URL_2001, YOUTUBE_PLAYLIST_URL_2002,
    YOUTUBE_PLAYLIST_URL_2003, YOUTUBE_PLAYLIST_URL_2004,
)
from downloader import download_video, YTDLP_VENV_PYTHON
from notifier import (
    send_telegram_message, update_sheet_platform,
    notify_upload_success, notify_upload_failed,
)

# ============================================================================
# THE FLOW: Year -> [C2, C3] platform assignments
# ============================================================================
YEAR_FLOW = {
    "1999": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_1999",
        "c2": "BitChute",
        "c3": "Dailymotion",
    },
    "2000": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2000",
        "c2": "Rumble",
        "c3": "Bilibili",
    },
    "2001": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2001",
        "c2": "Odysee",
        "c3": "InternetArchive",
    },
    "2002": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2002",
        "c2": "BitChute",
        "c3": "pCloud",
    },
    "2003": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2003",
        "c2": "Rumble",
        "c3": "Dailymotion",
    },
    "2004": {
        "playlist_env": "YOUTUBE_PLAYLIST_URL_2004",
        "c2": "Odysee",
        "c3": "Bilibili",
    },
}

MAX_DOWNLOAD_RETRIES = 2


# ============================================================================
# Platform upload dispatchers
# ============================================================================
def _upload_rumble(video_path, title, description, year):
    from uploader_rumble import upload_to_rumble
    import config as cfg
    cfg.RUMBLE_CHANNEL_NAME = year
    return upload_to_rumble(video_path, title, description, ['sermon', 'church', 'daghewardmills'])


def _upload_bitchute(video_path, title, description, year):
    from uploader_bitchute import upload_to_bitchute
    thumb_path = None
    base = os.path.splitext(video_path)[0]
    for ext in ['.jpg', '.webp', '.png']:
        if os.path.exists(base + ext):
            thumb_path = base + ext
            break
    return upload_to_bitchute(video_path, title, description, thumb_path)


def _upload_dailymotion(video_path, title, description, year):
    from uploader_dailymotion import upload_to_dailymotion
    dm_id = upload_to_dailymotion(video_path, title, description)
    if dm_id == "RATE_LIMITED":
        print(f"  [Dailymotion] Rate limited — sleeping 24h then retrying")
        send_telegram_message(f"<b>Dailymotion Daily Limit</b>\nSleeping 24h...")
        time.sleep(24 * 3600)
        dm_id = upload_to_dailymotion(video_path, title, description)
    return dm_id if dm_id and dm_id != "RATE_LIMITED" else None


def _upload_odysee(video_path, title, description, year):
    from uploader_odysee import upload_to_odysee
    channel = "2001archivedhmm2" if year == "2001" else None
    return upload_to_odysee(video_path, title, description, channel_name=channel)


def _upload_bilibili(video_path, title, description, year):
    from bilibili_client import upload_to_bilibili
    result = upload_to_bilibili(video_path, title, description)
    if result == "RATE_LIMITED":
        print(f"  [Bilibili] Rate limited — sleeping 24h then retrying")
        send_telegram_message(f"<b>Bilibili Daily Limit</b>\nSleeping 24h...")
        time.sleep(24 * 3600)
        result = upload_to_bilibili(video_path, title, description)
    return result if result and result != "RATE_LIMITED" else None


def _upload_internet_archive(video_path, title, description, year):
    from uploader_internet_archive import upload_to_internet_archive
    return upload_to_internet_archive(video_path, title, description, year)


def _upload_pcloud(video_path, title, description, year):
    from pcloud_client import upload_file, create_folder
    dest_folder = f"/Archive/{year}"
    create_folder(f"Archive", "/")
    create_folder(year, "/Archive")
    result = upload_file(video_path, dest_folder=dest_folder)
    return result


UPLOADERS = {
    "Rumble": _upload_rumble,
    "BitChute": _upload_bitchute,
    "Dailymotion": _upload_dailymotion,
    "Odysee": _upload_odysee,
    "Bilibili": _upload_bilibili,
    "InternetArchive": _upload_internet_archive,
    "pCloud": _upload_pcloud,
}


def _get_link(platform, result):
    """Extract a URL from the upload result if possible."""
    if platform == "Dailymotion" and isinstance(result, str):
        return f"https://www.dailymotion.com/video/{result}"
    if platform == "InternetArchive" and isinstance(result, str):
        return f"https://archive.org/details/{result}"
    if platform == "Bilibili" and isinstance(result, dict):
        bvid = result.get('data', {}).get('bvid', '')
        if bvid:
            return f"https://www.bilibili.com/video/{bvid}"
    return ""


# ============================================================================
# Main
# ============================================================================
def run_year(year):
    flow = YEAR_FLOW.get(year)
    if not flow:
        print(f"ERROR: No flow config for year {year}. Available: {list(YEAR_FLOW.keys())}")
        return

    c2_name = flow["c2"]
    c3_name = flow["c3"]

    print(f"\n{'='*60}")
    print(f"  YEAR {year}: YouTube -> {c2_name} (C2) + {c3_name} (C3)")
    print(f"{'='*60}\n")

    # --- Extract playlist ---
    playlist_url = os.getenv(flow['playlist_env'], '')
    if not playlist_url:
        print(f"ERROR: {flow['playlist_env']} not configured in .env")
        return

    print(f"Fetching playlist: {playlist_url}")
    try:
        from downloader import COOKIES_FILE
        cmd = [
            YTDLP_VENV_PYTHON, "-m", "yt_dlp",
            "--flat-playlist", "--print-json", "--no-warnings",
            playlist_url,
        ]
        if os.path.isfile(COOKIES_FILE):
            cmd.insert(-1, "--cookies")
            cmd.insert(-1, COOKIES_FILE)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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
    except Exception as e:
        print(f"ERROR extracting playlist: {e}")
        # Fallback to pytubefix
        try:
            from pytubefix import Playlist
            pl = Playlist(playlist_url)
            entries = []
            for url in pl.video_urls:
                match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
                vid_id = match.group(1) if match else 'unknown'
                entries.append({'id': vid_id, 'url': url, 'title': vid_id})
        except Exception as e2:
            print(f"ERROR: Both yt-dlp and pytubefix failed: {e2}")
            return

    total = len(entries)
    print(f"Total videos: {total}")

    send_telegram_message(
        f"<b>Starting {year}</b>\n"
        f"YouTube -> {c2_name} + {c3_name}\n"
        f"{total} videos to process"
    )

    # --- Archive files ---
    c2_archive = f'archive_{year}_{c2_name.lower()}.txt'
    c3_archive = f'archive_{year}_{c3_name.lower()}.txt'

    def _load_archive(path):
        if os.path.exists(path):
            with open(path) as f:
                return set(f.read().splitlines())
        return set()

    c2_done = _load_archive(c2_archive)
    c3_done = _load_archive(c3_archive)

    c2_count = len(c2_done)
    c3_count = len(c3_done)
    failed_count = 0

    for i, entry in enumerate(entries, 1):
        vid_id = entry['id']
        title = entry.get('title', vid_id)
        video_url = entry.get('url', f'https://www.youtube.com/watch?v={vid_id}')

        c2_already = vid_id in c2_done
        c3_already = vid_id in c3_done

        if c2_already and c3_already:
            print(f"[{i}/{total}] Both done: {title}")
            continue

        print(f"\n[{i}/{total}] Processing: {title}")
        if c2_already:
            print(f"  {c2_name}: already done")
        if c3_already:
            print(f"  {c3_name}: already done")

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
            failed_count += 1
            continue

        video_path = media_info['video_path']
        actual_title = media_info.get('title') or title
        description = media_info.get('description', '')

        # --- Upload to C2 ---
        if not c2_already:
            print(f"  Uploading to {c2_name}...")
            c2_uploader = UPLOADERS.get(c2_name)
            if c2_uploader:
                c2_result = c2_uploader(video_path, actual_title, description, year)
                if c2_result:
                    c2_count += 1
                    with open(c2_archive, 'a') as f:
                        f.write(f"{vid_id}\n")
                    c2_done.add(vid_id)
                    link = _get_link(c2_name, c2_result)
                    update_sheet_platform(video_url, actual_title, c2_name, "Uploaded", link, year=year)
                    notify_upload_success(actual_title, c2_name, c2_count, total)
                else:
                    update_sheet_platform(video_url, actual_title, c2_name, "Failed", "", year=year)
                    notify_upload_failed(actual_title, c2_name, "Upload failed", i, total)

        # --- Upload to C3 ---
        if not c3_already:
            print(f"  Uploading to {c3_name}...")
            c3_uploader = UPLOADERS.get(c3_name)
            if c3_uploader:
                c3_result = c3_uploader(video_path, actual_title, description, year)
                if c3_result:
                    c3_count += 1
                    with open(c3_archive, 'a') as f:
                        f.write(f"{vid_id}\n")
                    c3_done.add(vid_id)
                    link = _get_link(c3_name, c3_result)
                    update_sheet_platform(video_url, actual_title, c3_name, "Uploaded", link, year=year)
                    notify_upload_success(actual_title, c3_name, c3_count, total)
                else:
                    update_sheet_platform(video_url, actual_title, c3_name, "Failed", "", year=year)
                    notify_upload_failed(actual_title, c3_name, "Upload failed", i, total)

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
        f"<b>{year} Complete!</b>\n"
        f"{c2_name}: {c2_count}/{total}\n"
        f"{c3_name}: {c3_count}/{total}\n"
        f"Failed downloads: {failed_count}"
    )
    send_telegram_message(summary)
    print(f"\nDone! {c2_name}: {c2_count}, {c3_name}: {c3_count}, Failed: {failed_count}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run_year.py 1999        # Run single year")
        print("  python run_year.py all          # Run all years")
        print()
        print("Flow:")
        for y, f in sorted(YEAR_FLOW.items()):
            print(f"  {y}: YouTube -> {f['c2']} + {f['c3']}")
        sys.exit(1)

    target = sys.argv[1]

    if target == "all":
        for year in sorted(YEAR_FLOW.keys()):
            run_year(year)
    elif target in YEAR_FLOW:
        run_year(target)
    else:
        print(f"Unknown year: {target}")
        print(f"Available: {list(YEAR_FLOW.keys())} or 'all'")
