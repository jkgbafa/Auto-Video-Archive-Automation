# Auto-Video-Archive-Automation

## What This Project Does
Archives YouTube playlists (years 1999–2004) to multiple video/cloud platforms automatically.

## VPS Info
- **Server**: `srv1437375` (root access)
- **Project path**: `/root/Auto-Video-Archive-Automation`
- **Backend**: `/root/Auto-Video-Archive-Automation/backend/`
- **Venv**: `/root/Auto-Video-Archive-Automation/backend/venv/`
- **Logs**: `/root/Auto-Video-Archive-Automation/logs/year_<YEAR>.log`
- **Old project** (legacy, ignore): `/root/archive_worker/`

## Architecture — The Flow
Each year downloads from YouTube and uploads to 2 assigned platforms:

| Year | Platform 1     | Platform 2       |
|------|----------------|------------------|
| 1999 | BitChute       | Dailymotion      |
| 2000 | Rumble         | Bilibili         |
| 2001 | Odysee         | Internet Archive |
| 2002 | BitChute       | pCloud           |
| 2003 | Rumble         | Dailymotion      |
| 2004 | Odysee         | Bilibili         |

Cloud-to-cloud watchers (Phase 2):
- **2020**: pCloud → Bilibili (72 videos, Darius)
- **2021**: Internxt → Icedrive (Eniola)

## Key Files
- `launch_all.sh` — Launches all year transfers, watchers, and Telegram bot
- `setup_vps.sh` — One-paste VPS deployment (venv, packages, .env, credentials, launch)
- `backend/run_year.py` — Main per-year orchestrator (downloads + uploads)
- `backend/config.py` — Loads .env, defines year→platform mappings
- `backend/downloader.py` — YouTube download via yt-dlp
- `backend/uploaders/` — One uploader per platform (rumble, bitchute, dailymotion, odysee, bilibili, internet_archive, pcloud, icedrive)
- `backend/tracker.py` — Google Sheets progress tracking
- `backend/telegram_bot.py` — Status bot (send "status" to get progress)
- `backend/.env` — All credentials and playlist URLs
- `backend/google_credentials.json` — Google service account for Sheets API

## Deployment — One Command
```bash
cd /root/Auto-Video-Archive-Automation && git pull && bash setup_vps.sh
```

## Troubleshooting Quick Reference
- **See what's running**: `ps aux | grep python | grep -v grep`
- **Check year logs**: `tail -50 /root/Auto-Video-Archive-Automation/logs/year_1999.log`
- **Kill everything**: `pkill -f 'run_year\|watcher_\|telegram_bot'`
- **Restart everything**: `bash launch_all.sh`
- **Check .env**: `cat /root/Auto-Video-Archive-Automation/backend/.env`

## Common Bugs (Fixed)
- **PYTHON set before venv activation** — nohup used system python, no packages. Fixed: venv activates first.
- **Duplicate processes** — Multiple launches created zombies. Fixed: launch_all.sh kills old processes first.
