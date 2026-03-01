import os
import sys
import json
import re
import time
import subprocess
import requests
from config import DOWNLOAD_DIR

# ---------------------------------------------------------------------------
# yt-dlp Python: prefer dedicated venv if it exists, otherwise use the
# project venv (which has yt-dlp installed via pip).
# ---------------------------------------------------------------------------
_YTDLP_VENV_PYTHON = os.path.expanduser("~/.local/share/yt-dlp-env/bin/python")
if os.path.isfile(_YTDLP_VENV_PYTHON):
    YTDLP_VENV_PYTHON = _YTDLP_VENV_PYTHON
else:
    YTDLP_VENV_PYTHON = sys.executable  # fallback: project venv python
FFMPEG_PATH = os.path.expanduser("~/.local/bin/ffmpeg")

# Cookies: use Chrome browser cookies locally, fall back to cookies.txt on VPS
COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")


def _has_chrome_browser():
    """Check if Chrome/Chromium is installed (means we're running locally)."""
    for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
        if subprocess.run(["which", name], capture_output=True).returncode == 0:
            return True
    # macOS
    if os.path.exists("/Applications/Google Chrome.app"):
        return True
    return False


def _add_cookie_args(cmd):
    """Add cookie authentication args to a yt-dlp command list (before the URL)."""
    if _has_chrome_browser():
        cmd.insert(-1, "--cookies-from-browser")
        cmd.insert(-1, "chrome")
    elif os.path.isfile(COOKIES_FILE):
        cmd.insert(-1, "--cookies")
        cmd.insert(-1, COOKIES_FILE)


# Ensure ffmpeg and local bin are on PATH
LOCAL_BIN = os.path.expanduser("~/.local/bin")
if LOCAL_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = LOCAL_BIN + ":" + os.environ.get("PATH", "")


def _extract_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else 'unknown'


def get_video_info(video_url):
    """
    Extract video information without downloading.
    Uses yt-dlp 2026 venv with EJS solver.
    """
    video_id = _extract_video_id(video_url)
    cmd = [
        YTDLP_VENV_PYTHON, "-m", "yt_dlp",
        "--skip-download",
        "--print-json",
        "--no-warnings",
        video_url,
    ]
    _add_cookie_args(cmd)
    if subprocess.run(["which", "node"], capture_output=True).returncode == 0:
        cmd[4:4] = ["--js-runtimes", "node"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                env=_get_env())
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip().split('\n')[0])
            return {
                'id': data.get('id', video_id),
                'title': data.get('title', ''),
                'description': data.get('description', ''),
            }
    except Exception as e:
        print(f"get_video_info failed: {e}")
    return None


def _get_env():
    """Build environment with ffmpeg and node on PATH."""
    env = os.environ.copy()
    extra_paths = [LOCAL_BIN, "/usr/local/bin"]
    current = env.get("PATH", "")
    for p in extra_paths:
        if p not in current:
            current = p + ":" + current
    env["PATH"] = current
    return env


def download_video(video_url, output_prefix=None):
    """
    Download the highest quality video from a YouTube URL.

    Uses yt-dlp 2026 (Python 3.13 venv) with:
      - EJS challenge solver (via Node.js) for SABR bypass
      - Chrome cookies for authentication
      - ffmpeg for merging video+audio streams

    Returns dict with video_id, title, description, video_path, info_path, thumb_path.
    """
    video_id = output_prefix or _extract_video_id(video_url)
    base_path = os.path.join(DOWNLOAD_DIR, video_id)
    video_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")

    # Skip if already downloaded
    if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
        print(f"  Already downloaded: {video_path}")
    else:
        print(f"Downloading {video_url} (id={video_id})")

        outtmpl = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")

        cmd = [
            YTDLP_VENV_PYTHON, "-m", "yt_dlp",
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--output", outtmpl,
            "--write-thumbnail",
            "--write-info-json",
            "--no-warnings",
            "--ignore-errors",
            "--merge-output-format", "mp4",
            video_url,
        ]
        _add_cookie_args(cmd)
        if subprocess.run(["which", "node"], capture_output=True).returncode == 0:
            cmd.insert(-1, "--js-runtimes")
            cmd.insert(-1, "node")

        env = _get_env()
        print(f"  [yt-dlp] Running with {YTDLP_VENV_PYTHON}...")
        result = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                timeout=7200)

        # Check for .mkv fallback if .mp4 not found
        if not os.path.exists(video_path):
            mkv_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mkv")
            if os.path.exists(mkv_path):
                video_path = mkv_path

        if result.returncode != 0 and not os.path.exists(video_path):
            stderr_tail = result.stderr[-500:] if result.stderr else ''
            stdout_tail = result.stdout[-500:] if result.stdout else ''
            print(f"  [yt-dlp] Download failed:\n    STDOUT: {stdout_tail}\n    STDERR: {stderr_tail}")
            return None

        if os.path.exists(video_path):
            size_mb = os.path.getsize(video_path) / 1024 / 1024
            print(f"  [yt-dlp] Download OK ({size_mb:.1f} MB)")

    if not os.path.exists(video_path):
        print(f"  All download methods failed for {video_url}")
        return None

    # --- Read title/description from info.json ---
    title = ''
    description = ''
    info_path = f"{base_path}.info.json"
    try:
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
                title = info_data.get('title', '')
                description = info_data.get('description', '')
    except Exception as e:
        print(f"  Could not read info.json: {e}")

    # If no title from info.json, fetch it
    if not title:
        info = get_video_info(video_url)
        if info:
            title = info.get('title', video_id)
            description = info.get('description', '')

    # --- Find thumbnail ---
    thumb_path = None
    for ext in ['jpg', 'webp', 'png']:
        possible_thumb = f"{base_path}.{ext}"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb
            break

    return {
        'video_id': video_id,
        'title': title,
        'description': description,
        'video_path': video_path if os.path.exists(video_path) else None,
        'info_path': info_path if os.path.exists(info_path) else None,
        'thumb_path': thumb_path,
    }


if __name__ == "__main__":
    # Test block
    test_url = "https://youtu.be/XzUKVV2uWcI"
    print(f"Testing download for {test_url}")
    res = download_video(test_url)
    print("Download result:", json.dumps(res, indent=2))
