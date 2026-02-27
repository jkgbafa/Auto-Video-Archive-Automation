import json
import requests
import gspread
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_SHEET_URL

def send_telegram_message(message):
    """
    Send a message to the specified Telegram group or channel.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def update_google_sheet(video_url, title, bc_status, dm_status, bc_url="", dm_url="", year="1999"):
    """
    Update Google sheet via Google Sheets API.
    Creates year-specific tab dynamically.
    Columns: [Number, Name, YouTube Status, YouTube Link, Bitchute Status, Bitchute Link, Dailymotion Status, Dailymotion Link]
    """
    if not GOOGLE_SHEET_URL:
        return
        
    try:
        # Authenticate using generated JSON
        import os
        creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_credentials.json")
        gc = gspread.service_account(filename=creds_path)
        sh = gc.open_by_url(GOOGLE_SHEET_URL)
        
        # Get or create the year's worksheet
        try:
            worksheet = sh.worksheet(year)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title=year, rows=100, cols=20)
            headers = ["Number", "Name", "YouTube Status", "YouTube Link", "Bitchute Status", "Bitchute Link", "Dailymotion Status", "Dailymotion Link"]
            worksheet.append_row(headers)
            
        records = worksheet.get_all_records()
        row_index = None
        for i, record in enumerate(records):
            if record.get("YouTube Link") == video_url:
                row_index = i + 2 # headers + 0-index
                break
                
        if row_index is None:
            # New row
            number = len(records) + 1
            row = [number, title, "Uploaded", video_url, bc_status, bc_url, dm_status, dm_url]
            worksheet.append_row(row)
        else:
            # Update existing row cells
            worksheet.update_cell(row_index, 5, bc_status)
            worksheet.update_cell(row_index, 6, bc_url)
            worksheet.update_cell(row_index, 7, dm_status)
            worksheet.update_cell(row_index, 8, dm_url)
            
        print(f"Updated Google Sheet: {title}")
    except Exception as e:
        print(f"Failed to update Google Sheet: {e}")

def notify_new_video(title):
    msg = f"🚀 <b>New Video Downloaded</b>\n<i>{title}</i>\nStarting uploads..."
    send_telegram_message(msg)

def notify_upload_success(title, platform, current=0, total=0):
    progress = f" ({current}/{total})" if total > 0 else ""
    icon = "🔴" if platform == "Bitchute" else "🔵"
    msg = f"{icon} <b>{platform}{progress}</b>\n✅ {title}"
    send_telegram_message(msg)

def notify_upload_failed(title, platform, error="", current=0, total=0):
    progress = f" ({current}/{total})" if total > 0 else ""
    icon = "🔴" if platform == "Bitchute" else "🔵"
    msg = f"{icon} <b>{platform}{progress}</b>\n❌ {title}\n{error[:100]}"
    send_telegram_message(msg)

def notify_milestone(percent, total_videos, processed_count):
    if percent >= 100:
        msg = f"🎉 <b>TRANSFER FULLY COMPLETE!</b>\nSuccessfully archived {processed_count}/{total_videos} videos across platforms."
    else:
        msg = f"🏆 <b>Milestone Reached: {percent}%</b>\nTransferred {processed_count}/{total_videos} videos from the 1999 archive."
    send_telegram_message(msg)
