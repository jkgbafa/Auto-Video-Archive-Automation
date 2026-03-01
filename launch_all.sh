#!/bin/bash
# ============================================================================
# LAUNCH ALL TRANSFERS
# Run this on the VPS: bash launch_all.sh
# ============================================================================

set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
BACKEND="$PROJECT_DIR/backend"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "============================================"
echo " Auto-Video-Archive-Automation — FULL LAUNCH"
echo "============================================"
echo ""
echo "Project dir: $PROJECT_DIR"
echo "Logs dir:    $LOG_DIR"
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
pip install -q pytubefix yt-dlp gspread python-dotenv requests playwright python-telegram-bot biliup 2>/dev/null || true

cd "$BACKEND"

echo ""
echo "============================================"
echo " PHASE 1: YouTube -> All Platforms (1999-2003)"
echo "============================================"

# Launch all Phase 1 transfers in background with nohup
for YEAR in 1999 2000 2001 2002 2003; do
    for PLATFORM in rumble bitchute dailymotion odysee; do
        SCRIPT="run_${PLATFORM}.py"
        if [ -f "$SCRIPT" ]; then
            LOGFILE="$LOG_DIR/${PLATFORM}_${YEAR}.log"
            echo "  Starting: $SCRIPT $YEAR -> $LOGFILE"
            nohup $PYTHON "$SCRIPT" "$YEAR" > "$LOGFILE" 2>&1 &
            sleep 2  # Small delay between launches to avoid rate limits
        fi
    done
done

# Special case: 2002 BitChute has a dedicated script with separate credentials
echo "  Starting: run_bitchute_2002.py -> $LOG_DIR/bitchute_2002_dedicated.log"
nohup $PYTHON run_bitchute_2002.py > "$LOG_DIR/bitchute_2002_dedicated.log" 2>&1 &

echo ""
echo "============================================"
echo " PHASE 2: Cloud-to-Cloud Transfers"
echo "============================================"

# pCloud -> Bilibili watcher (Darius 2020 videos)
echo "  Starting: pCloud -> Bilibili watcher"
nohup $PYTHON watcher_pcloud_to_bilibili.py > "$LOG_DIR/watcher_pcloud_bilibili.log" 2>&1 &

# Internxt -> Icedrive watcher (Eniola 2021 videos)
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
echo "Monitor progress:"
echo "  - Telegram bot: send 'status' to your bot"
echo "  - Logs: tail -f $LOG_DIR/<platform>_<year>.log"
echo "  - All processes: ps aux | grep python"
echo ""
echo "To stop everything:"
echo "  pkill -f 'run_rumble\|run_bitchute\|run_dailymotion\|run_odysee\|watcher_\|telegram_bot'"
echo ""

# List running processes
sleep 3
echo "Running processes:"
ps aux | grep -E "(run_|watcher_|telegram_bot)" | grep -v grep | awk '{print "  PID " $2 ": " $11 " " $12}'
