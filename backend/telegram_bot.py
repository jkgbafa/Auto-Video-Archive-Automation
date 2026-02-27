"""
Intelligent Telegram Bot for Video Archive Status.

Runs as a separate process. Listens for messages and responds
with status updates from Google Sheets.

Usage:
    python3 telegram_bot.py

Commands the user can send:
    - "status" / "update" → Overall status across all platforms & years
    - "1999" / "2000" etc → Status for a specific year
    - "list" / "done" → List of completed videos
    - "dailymotion" / "bitchute" → Platform-specific status
    - Any natural text → Best-effort response
"""

import os
import sys
import re
import gspread
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GOOGLE_SHEET_URL

# Google Sheets client
CREDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_credentials.json")

def get_sheet():
    gc = gspread.service_account(filename=CREDS_PATH)
    return gc.open_by_url(GOOGLE_SHEET_URL)

def get_year_status(year_str):
    """Get status summary for a specific year."""
    try:
        sh = get_sheet()
        ws = sh.worksheet(year_str)
        records = ws.get_all_records()
        total = len(records)
        if total == 0:
            return f"📋 Year {year_str}: No videos found yet."
        
        yt_done = sum(1 for r in records if r.get("YouTube Status") == "Uploaded")
        bc_done = sum(1 for r in records if r.get("Bitchute Status") == "Uploaded")
        dm_done = sum(1 for r in records if r.get("Dailymotion Status") == "Uploaded")
        bc_fail = sum(1 for r in records if r.get("Bitchute Status") == "Failed")
        dm_fail = sum(1 for r in records if r.get("Dailymotion Status") == "Failed")
        
        msg = f"📊 <b>Year {year_str} Status</b>\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += f"📺 YouTube: <b>{yt_done}/{total}</b>\n"
        msg += f"🔴 Bitchute: <b>{bc_done}/{total}</b>"
        if bc_fail > 0:
            msg += f" ({bc_fail} failed)"
        msg += f"\n"
        msg += f"🔵 Dailymotion: <b>{dm_done}/{total}</b>"
        if dm_fail > 0:
            msg += f" ({dm_fail} failed)"
        msg += f"\n"
        
        # Calculate overall progress
        platforms_done = bc_done + dm_done
        platforms_total = total * 2  # 2 platforms
        if platforms_total > 0:
            pct = int((platforms_done / platforms_total) * 100)
            msg += f"\n🏆 Overall: <b>{pct}%</b> complete"
        
        return msg
    except gspread.exceptions.WorksheetNotFound:
        return f"❌ No data for year {year_str} yet."
    except Exception as e:
        return f"⚠️ Error reading sheet: {str(e)[:100]}"

def get_overall_status():
    """Get status across all years."""
    try:
        sh = get_sheet()
        worksheets = sh.worksheets()
        year_tabs = [ws for ws in worksheets if ws.title.isdigit() and len(ws.title) == 4]
        
        if not year_tabs:
            return "📋 No year tabs found yet."
        
        msg = "📊 <b>Archive Overview</b>\n━━━━━━━━━━━━━━━\n"
        total_all = 0
        bc_all = 0
        dm_all = 0
        
        for ws in sorted(year_tabs, key=lambda w: w.title):
            records = ws.get_all_records()
            total = len(records)
            if total == 0:
                continue
            total_all += total
            bc = sum(1 for r in records if r.get("Bitchute Status") == "Uploaded")
            dm = sum(1 for r in records if r.get("Dailymotion Status") == "Uploaded")
            bc_all += bc
            dm_all += dm
            msg += f"\n<b>{ws.title}</b>: 📺{total} | 🔴BC {bc}/{total} | 🔵DM {dm}/{total}"
        
        msg += f"\n\n━━━━━━━━━━━━━━━"
        msg += f"\n<b>TOTALS</b>: {total_all} videos"
        msg += f"\n🔴 Bitchute: {bc_all}/{total_all}"
        msg += f"\n🔵 Dailymotion: {dm_all}/{total_all}"
        
        return msg
    except Exception as e:
        return f"⚠️ Error: {str(e)[:100]}"

def get_completed_list(year_str=None, platform=None):
    """Get list of completed videos."""
    try:
        sh = get_sheet()
        if year_str:
            tabs = [sh.worksheet(year_str)]
        else:
            tabs = [ws for ws in sh.worksheets() if ws.title.isdigit() and len(ws.title) == 4]
        
        completed = []
        for ws in tabs:
            records = ws.get_all_records()
            for r in records:
                if platform == "bitchute" and r.get("Bitchute Status") == "Uploaded":
                    completed.append(f"✅ {r.get('Name', '?')}")
                elif platform == "dailymotion" and r.get("Dailymotion Status") == "Uploaded":
                    completed.append(f"✅ {r.get('Name', '?')}")
                elif not platform and (r.get("Bitchute Status") == "Uploaded" or r.get("Dailymotion Status") == "Uploaded"):
                    completed.append(f"✅ {r.get('Name', '?')}")
        
        if not completed:
            return "No completed uploads found."
        
        # Limit to last 20 to avoid huge messages
        if len(completed) > 20:
            msg = f"📋 <b>Last 20 of {len(completed)} completed:</b>\n"
            msg += "\n".join(completed[-20:])
        else:
            msg = f"📋 <b>{len(completed)} completed:</b>\n"
            msg += "\n".join(completed)
        return msg
    except Exception as e:
        return f"⚠️ Error: {str(e)[:100]}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages with natural language understanding."""
    text = update.message.text.lower().strip()
    
    # Check for year number
    year_match = re.search(r'\b(199\d|200\d|201\d|202[0-6])\b', text)
    
    if any(w in text for w in ['status', 'update', 'how', 'progress', 'overview', 'where']):
        if year_match:
            response = get_year_status(year_match.group(1))
        else:
            response = get_overall_status()
    elif any(w in text for w in ['list', 'done', 'completed', 'finished', 'which']):
        platform = None
        if 'bitchute' in text or 'bc' in text:
            platform = "bitchute"
        elif 'dailymotion' in text or 'dm' in text:
            platform = "dailymotion"
        year = year_match.group(1) if year_match else None
        response = get_completed_list(year, platform)
    elif 'bitchute' in text:
        if year_match:
            response = get_year_status(year_match.group(1))
        else:
            response = get_overall_status()
    elif 'dailymotion' in text or 'daily motion' in text:
        if year_match:
            response = get_year_status(year_match.group(1))
        else:
            response = get_overall_status()
    elif year_match:
        response = get_year_status(year_match.group(1))
    elif any(w in text for w in ['help', 'command', 'what can']):
        response = (
            "🤖 <b>I understand these:</b>\n"
            "• <b>status</b> — Overall progress\n"
            "• <b>1999</b> (any year) — Year-specific status\n"
            "• <b>list</b> — Completed videos\n"
            "• <b>list bitchute 1999</b> — Platform+year filter\n"
            "• <b>dailymotion status</b> — Platform status\n"
            "• <b>help</b> — This message"
        )
    else:
        # Default: show overall status
        response = get_overall_status()
    
    await update.message.reply_text(response, parse_mode="HTML")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Video Archive Bot</b>\n\n"
        "Ask me anything about the archive status!\n"
        "Try: <b>status</b>, <b>1999</b>, <b>list</b>, or <b>help</b>",
        parse_mode="HTML"
    )

def main():
    print("Starting Telegram bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot is listening for messages...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
