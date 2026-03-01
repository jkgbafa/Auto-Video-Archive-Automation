#!/bin/bash
# ============================================================================
# ONE-PASTE VPS SETUP — Run this on a fresh VPS to deploy everything
#
# Usage: Just paste this ONE line on your VPS:
#   curl -sL https://raw.githubusercontent.com/jkgbafa/Auto-Video-Archive-Automation/claude/review-video-uploaders-8RZj1/setup_vps.sh | bash
#
# Or if already cloned:
#   cd /root/Auto-Video-Archive-Automation && bash setup_vps.sh
# ============================================================================

echo ""
echo "============================================"
echo " VPS SETUP — Auto-Video-Archive-Automation"
echo "============================================"
echo ""

# --- 1. Clone repo if needed ---
REPO_DIR="/root/Auto-Video-Archive-Automation"
BRANCH="claude/review-video-uploaders-8RZj1"

if [ ! -d "$REPO_DIR" ]; then
    echo "[1/6] Cloning repository..."
    cd /root
    git clone https://github.com/jkgbafa/Auto-Video-Archive-Automation.git
    cd "$REPO_DIR"
    git checkout "$BRANCH"
else
    echo "[1/6] Repository exists, pulling latest..."
    cd "$REPO_DIR"
    git fetch origin "$BRANCH" 2>/dev/null || true
    git checkout "$BRANCH" 2>/dev/null || true
    git pull origin "$BRANCH" 2>/dev/null || true
fi

BACKEND="$REPO_DIR/backend"

# --- 2. Create Python venv ---
echo "[2/6] Setting up Python virtual environment..."
if [ ! -d "$BACKEND/venv" ]; then
    python3 -m venv "$BACKEND/venv"
    echo "  Created venv"
else
    echo "  Venv already exists"
fi

source "$BACKEND/venv/bin/activate"
echo "  Activated: $(which python3)"

# --- 3. Install all dependencies ---
echo "[3/6] Installing Python packages..."
pip install -q pytubefix yt-dlp gspread python-dotenv requests playwright biliup internetarchive 2>/dev/null
echo "  Done"

# --- 4. Create .env with all credentials ---
echo "[4/6] Writing .env configuration..."
cat > "$BACKEND/.env" << 'ENVEOF'
# YouTube Playlists
YOUTUBE_PLAYLIST_URL=https://www.youtube.com/playlist?list=PLuKQ4p-jV3VRRS6bqYqJRGOjboUna2htT
YOUTUBE_PLAYLIST_URL_1999=https://www.youtube.com/playlist?list=PLuKQ4p-jV3VRRS6bqYqJRGOjboUna2htT
YOUTUBE_PLAYLIST_URL_2000=https://www.youtube.com/playlist?list=PLjQbqqhMvirawEjL4204P98gM-b89wrlC
YOUTUBE_PLAYLIST_URL_2001=https://www.youtube.com/playlist?list=PLt1BGZxp9RXXBr6H0uBX7bw4y_ZKVew9W
YOUTUBE_PLAYLIST_URL_2002=https://www.youtube.com/playlist?list=PLH2edYFEYwL88r3Vs5MDSSN3rwsqqQ18O
YOUTUBE_PLAYLIST_URL_2003=https://www.youtube.com/playlist?list=PLbDLj9zYfu7p0qkL16Ii1swN7DtUfIU80
YOUTUBE_PLAYLIST_URL_2004=

# Rumble
RUMBLE_EMAIL=ytoffice2023@gmail.com
RUMBLE_PASSWORD=SeeMe123!
RUMBLE_CHANNEL_NAME=2000

# Dailymotion
DAILYMOTION_USERNAME=dhmmsocialpublishing@gmail.com
DAILYMOTION_PASSWORD=Fu11Pr00f!
DAILYMOTION_API_KEY=d08d5079899e7596697e
DAILYMOTION_API_SECRET=9c1e988249996711f4b28bff539bdbd7fdf9fdb2
DAILYMOTION_REFRESH_TOKEN=

# BitChute
BITCHUTE_USERNAME=ytoffice2023@gmail.com
BITCHUTE_PASSWORD=SeeMe123!

# Telegram
TELEGRAM_BOT_TOKEN=8316483220:AAFpLhhYJ6P7n2QLIdaWG9x1fNbG9u9HMEk
TELEGRAM_CHAT_ID=816709817

# Google Sheet
GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/1-1-X44qe7e6bqpvMGCP8hnHyTOru0YbF0EE0Is7dcTM/

# Odysee
ODYSEE_EMAIL=ytoffice2023@gmail.com
ODYSEE_PASSWORD=SeeMe123!SeeMe123!

# Supabase
SUPABASE_URL=
SUPABASE_KEY=

# pCloud (Switzerland) — 10TB paid
PCLOUD_EMAIL=ytoffice2023@gmail.com
PCLOUD_PASSWORD=SeeMe26!

# Internxt (Spain) — 5TB lifetime
INTERNXT_EMAIL=ytoffice2023@gmail.com
INTERNXT_PASSWORD=SeeMe123!

# Icedrive (UK) — 1TB lifetime
ICEDRIVE_EMAIL=ytoffice2023@gmail.com
ICEDRIVE_PASSWORD=SeeMe123!
ICEDRIVE_WEBDAV_URL=https://webdav.icedrive.io/
ICEDRIVE_ACCESS_KEY=8f21H1fGFg2D7meh68

# Koofr (Slovenia)
KOOFR_EMAIL=ytoffice2023@gmail.com
KOOFR_PASSWORD=SeeMe123!

# Internet Archive
IA_ACCESS_KEY=
IA_SECRET_KEY=

# Bilibili (China)
BILIBILI_EMAIL=ytoffice2023@gmail.com
BILIBILI_PASSWORD=SeeMe123!
ENVEOF
echo "  .env written with all credentials"

# --- 5. Write Google credentials ---
echo "[5/6] Writing Google service account credentials..."
if [ ! -f "$BACKEND/google_credentials.json" ]; then
    # Try to copy from old project first
    if [ -f "/root/archive_worker/google_credentials.json" ]; then
        cp /root/archive_worker/google_credentials.json "$BACKEND/google_credentials.json"
        echo "  Copied from archive_worker"
    else
        echo "  WARNING: google_credentials.json not found!"
        echo "  You need to copy it manually to $BACKEND/google_credentials.json"
    fi
else
    echo "  Already exists"
fi

# --- 6. Kill old processes and launch ---
echo "[6/6] Launching all transfers..."
echo ""

# Kill any old python processes from previous runs
pkill -f 'run_year\|watcher_pcloud\|watcher_internxt\|telegram_bot' 2>/dev/null || true
sleep 2

# Launch everything
cd "$REPO_DIR"
bash launch_all.sh

# Verify processes are running
echo ""
echo "============================================"
echo " VERIFICATION"
echo "============================================"
sleep 5

YEAR_PROCS=$(ps aux | grep run_year | grep -v grep | wc -l)
WATCHER_PROCS=$(ps aux | grep watcher_ | grep -v grep | wc -l)
BOT_PROCS=$(ps aux | grep telegram_bot | grep -v grep | wc -l)

echo "  run_year.py processes: $YEAR_PROCS (expected: 5)"
echo "  watcher processes:     $WATCHER_PROCS (expected: 2)"
echo "  telegram bot:          $BOT_PROCS (expected: 1)"
echo ""

if [ "$YEAR_PROCS" -ge 1 ]; then
    echo "  TRANSFERS ARE RUNNING!"
else
    echo "  WARNING: Year transfers not running. Check logs:"
    echo "    cat $REPO_DIR/logs/year_1999.log"
fi

echo ""
echo "============================================"
echo " SETUP COMPLETE"
echo "============================================"
echo ""
echo "To redeploy in future, just run:"
echo "  cd /root/Auto-Video-Archive-Automation && bash setup_vps.sh"
echo ""
