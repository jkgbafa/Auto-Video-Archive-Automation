import json
import requests
import gspread
import os
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_SHEET_URL

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram_message(message):
    """Send a message to the specified Telegram group or channel."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")


# ---------------------------------------------------------------------------
# Google Sheets — Column mapping for year tabs
# ---------------------------------------------------------------------------
# New structure:
#   A: Number, B: Name, C: YouTube Status, D: YouTube Link,
#   E: Rumble Status, F: Rumble Link,
#   G: Bitchute Status, H: Bitchute Link,
#   I: Dailymotion Status, J: Dailymotion Link,
#   K: Odysee Status, L: Odysee Link
PLATFORM_COLUMNS = {
    # Phase 1: YouTube -> platforms
    "Rumble":      {"status_col": 5, "link_col": 6},
    "BitChute":    {"status_col": 7, "link_col": 8},
    "Dailymotion": {"status_col": 9, "link_col": 10},
    "Odysee":      {"status_col": 11, "link_col": 12},
    # Phase 2: Archive backup platforms
    "pCloud":      {"status_col": 13, "link_col": 14},
    "Internxt":    {"status_col": 15, "link_col": 16},
    "Icedrive":    {"status_col": 17, "link_col": 18},
    "Bilibili":    {"status_col": 19, "link_col": 20},
    "Koofr":              {"status_col": 21, "link_col": 22},
    "InternetArchive":    {"status_col": 23, "link_col": 24},
}

HEADERS = [
    "Number", "Name", "YouTube Status", "YouTube Link",
    "Rumble Status", "Rumble Link",
    "Bitchute Status", "Bitchute Link",
    "Dailymotion Status", "Dailymotion Link",
    "Odysee Status", "Odysee Link",
    "pCloud Status", "pCloud Link",
    "Internxt Status", "Internxt Link",
    "Icedrive Status", "Icedrive Link",
    "Bilibili Status", "Bilibili Link",
    "Koofr Status", "Koofr Link",
    "Internet Archive Status", "Internet Archive Link",
]

_gc_cache = None

def _get_gspread_client():
    """Return cached gspread client."""
    global _gc_cache
    if _gc_cache is None:
        creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_credentials.json")
        _gc_cache = gspread.service_account(filename=creds_path)
    return _gc_cache


def update_google_sheet(video_url, title, bc_status="", dm_status="", bc_url="", dm_url="", year="1999"):
    """Legacy wrapper — update BitChute & Dailymotion columns."""
    update_sheet_platform(video_url, title, "BitChute", bc_status, bc_url, year)
    update_sheet_platform(video_url, title, "Dailymotion", dm_status, dm_url, year)


def update_sheet_platform(video_url, title, platform, status, link="", year="2000"):
    """
    Update a single platform's status in the Google Sheet for a specific video.

    Args:
        video_url: YouTube video URL (used as row key)
        title: Video title
        platform: One of 'Rumble', 'BitChute', 'Dailymotion', 'Odysee'
        status: Status string like 'Uploaded' or 'Failed'
        link: URL of the uploaded video on that platform
        year: Year tab to update (e.g. '2000', '2003')
    """
    if not GOOGLE_SHEET_URL or not status:
        return

    cols = PLATFORM_COLUMNS.get(platform)
    if not cols:
        print(f"Unknown platform: {platform}")
        return

    try:
        gc = _get_gspread_client()
        sh = gc.open_by_url(GOOGLE_SHEET_URL)

        # Get or create the year's worksheet
        try:
            worksheet = sh.worksheet(year)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=year, rows=200, cols=len(HEADERS))
            worksheet.append_row(HEADERS)

        # Find the row by YouTube URL (column D = 4)
        try:
            cell = worksheet.find(video_url, in_column=4)
            row_index = cell.row
        except gspread.exceptions.CellNotFound:
            # Row doesn't exist — append new row
            all_vals = worksheet.col_values(1)
            number = len(all_vals)  # Next number
            row = [""] * len(HEADERS)  # 24 columns to cover all platforms
            row[0] = number
            row[1] = title
            row[2] = "Uploaded"
            row[3] = video_url
            row[cols["status_col"] - 1] = status
            row[cols["link_col"] - 1] = link
            worksheet.append_row(row)
            print(f"  Sheet: Added new row for {title[:50]} [{platform}={status}]")
            return

        # Update the platform columns
        worksheet.update_cell(row_index, cols["status_col"], status)
        if link:
            worksheet.update_cell(row_index, cols["link_col"], link)

        # Also update the title if it's just a video ID
        current_name = worksheet.cell(row_index, 2).value
        if current_name and len(current_name) <= 12 and title and len(title) > 12:
            worksheet.update_cell(row_index, 2, title[:200])

        print(f"  Sheet: {title[:50]} [{platform}={status}]")
    except Exception as e:
        print(f"Failed to update Google Sheet: {e}")


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------
def notify_new_video(title):
    msg = f"🚀 <b>New Video Downloaded</b>\n<i>{title}</i>\nStarting uploads..."
    send_telegram_message(msg)

def notify_upload_success(title, platform, current=0, total=0):
    progress = f" ({current}/{total})" if total > 0 else ""
    icons = {
        "Rumble": "🟢", "BitChute": "🔴", "Dailymotion": "🔵",
        "Odysee": "🟣", "Bilibili": "🔷", "InternetArchive": "🏛",
        "pCloud": "☁️", "Icedrive": "❄️",
    }
    icon = icons.get(platform, "⬜")
    msg = f"{icon} <b>{platform}{progress}</b>\n✅ {title}"
    send_telegram_message(msg)

def notify_upload_failed(title, platform, error="", current=0, total=0):
    progress = f" ({current}/{total})" if total > 0 else ""
    icons = {
        "Rumble": "🟢",
        "BitChute": "🔴",
        "Dailymotion": "🔵",
        "Odysee": "🟣",
    }
    icon = icons.get(platform, "⬜")
    msg = f"{icon} <b>{platform}{progress}</b>\n❌ {title}\n{error[:100]}"
    send_telegram_message(msg)

def notify_milestone(percent, total_videos, processed_count):
    if percent >= 100:
        msg = f"🎉 <b>TRANSFER FULLY COMPLETE!</b>\nSuccessfully archived {processed_count}/{total_videos} videos across platforms."
    else:
        msg = f"🏆 <b>Milestone Reached: {percent}%</b>\nTransferred {processed_count}/{total_videos} videos from the archive."
    send_telegram_message(msg)
