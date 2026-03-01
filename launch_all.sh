#!/bin/bash
# ============================================================================
# LAUNCH ALL TRANSFERS — Correct Flow
# Run on VPS: bash launch_all.sh
# ============================================================================
#
# THE FLOW:
#   1999: YouTube -> BitChute + Dailymotion
#   2000: YouTube -> Rumble + Bilibili
#   2001: YouTube -> Odysee + Internet Archive
#   2002: YouTube -> BitChute + pCloud
#   2003: YouTube -> Rumble + Dailymotion
#   2004: YouTube -> Odysee + Bilibili (needs playlist URL)
#
#   2020: pCloud -> Bilibili (Darius)
#   2021: Internxt -> Icedrive (Eniola)
#
# ============================================================================

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
BACKEND="$PROJECT_DIR/backend"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "============================================"
echo " Auto-Video-Archive — FULL LAUNCH"
echo "============================================"
echo ""

# Check Python
PYTHON=$(which python3 || which python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: Python not found!"
    exit 1
fi
echo "Python: $PYTHON"

# Check venv
if [ -d "$BACKEND/venv" ]; then
    source "$BACKEND/venv/bin/activate"
    echo "Activated venv"
elif [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
    echo "Activated venv"
fi

# Install dependencies if needed
pip install -q pytubefix yt-dlp gspread python-dotenv requests playwright python-telegram-bot biliup internetarchive 2>/dev/null || true

cd "$BACKEND"

echo ""
echo "============================================"
echo " PHASE 1: YouTube -> Platforms (1999-2004)"
echo " Each year goes to its 2 assigned platforms"
echo "============================================"

# Launch each year with the correct flow using run_year.py
for YEAR in 1999 2000 2001 2002 2003; do
    LOGFILE="$LOG_DIR/year_${YEAR}.log"
    echo "  Starting: run_year.py $YEAR -> $LOGFILE"
    nohup $PYTHON run_year.py "$YEAR" > "$LOGFILE" 2>&1 &
    sleep 3  # Stagger launches
done

# 2004 — only if playlist URL is configured
if grep -q "YOUTUBE_PLAYLIST_URL_2004=http" "$BACKEND/.env" 2>/dev/null; then
    LOGFILE="$LOG_DIR/year_2004.log"
    echo "  Starting: run_year.py 2004 -> $LOGFILE"
    nohup $PYTHON run_year.py 2004 > "$LOGFILE" 2>&1 &
else
    echo "  Skipping 2004: No playlist URL configured yet"
fi

echo ""
echo "============================================"
echo " PHASE 2: Cloud-to-Cloud Transfers"
echo "============================================"

# pCloud -> Bilibili watcher (Darius 2020 — 72 videos found)
echo "  Starting: pCloud -> Bilibili watcher (72 videos)"
nohup $PYTHON watcher_pcloud_to_bilibili.py > "$LOG_DIR/watcher_pcloud_bilibili.log" 2>&1 &

# Internxt -> Icedrive watcher (Eniola 2021)
echo "  Starting: Internxt -> Icedrive watcher"
nohup $PYTHON watcher_internxt_to_icedrive.py > "$LOG_DIR/watcher_internxt_icedrive.log" 2>&1 &

echo ""
echo "============================================"
echo " TELEGRAM BOT"
echo "============================================"

# Start Telegram bot for status monitoring
echo "  Starting: Telegram bot"
nohup $PYTHON telegram_bot.py > "$LOG_DIR/telegram_bot.log" 2>&1 &

# Update the logins sheet
echo "  Updating logins sheet..."
$PYTHON update_logins_sheet.py 2>/dev/null || echo "  (logins sheet update skipped)"

echo ""
echo "============================================"
echo " ALL TRANSFERS LAUNCHED!"
echo "============================================"
echo ""
echo "The flow:"
echo "  1999: YouTube -> BitChute + Dailymotion"
echo "  2000: YouTube -> Rumble + Bilibili"
echo "  2001: YouTube -> Odysee + Internet Archive"
echo "  2002: YouTube -> BitChute + pCloud"
echo "  2003: YouTube -> Rumble + Dailymotion"
echo "  2020: pCloud -> Bilibili (72 videos)"
echo "  2021: Internxt -> Icedrive"
echo ""
echo "Monitor progress:"
echo "  - Telegram: send 'status' to your bot"
echo "  - Logs: tail -f $LOG_DIR/year_<YEAR>.log"
echo "  - All processes: ps aux | grep python"
echo ""
echo "To stop everything:"
echo "  pkill -f 'run_year\|watcher_\|telegram_bot'"
echo ""

# List running processes
sleep 3
echo "Running processes:"
ps aux | grep -E "(run_year|watcher_|telegram_bot)" | grep -v grep | awk '{print "  PID " $2 ": " $11 " " $12}'
