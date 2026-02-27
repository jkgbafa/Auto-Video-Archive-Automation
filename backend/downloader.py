import os
import sys
import json
import re
import time
import subprocess
import requests
import yt_dlp
from typing import Optional, Dict

from config import DOWNLOAD_DIR

# Ensure Deno is on PATH so yt-dlp can solve YouTube's n-signature JS challenge
DENO_PATH = os.path.expanduser("~/.deno/bin")
if DENO_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = DENO_PATH + ":" + os.environ.get("PATH", "")

COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.api.unbound.so",
    "https://co.wuk.sh",
    "https://cobalt.qwyx.icu",
    "https://cobalt-api.kwiatekit.com",
    "https://cobalt.canine.cloud",
    "https://api.cobalt.chat"
]

def extract_video_id(url: str) -> Optional[str]:
    """Fallback to regex if yt-dlp cannot extract the video ID."""
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
    return match.group(1) if match else None

def get_video_info(video_url: str) -> Optional[Dict]:
    """
    Extract video information without downloading.
    """
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
    except Exception as e:
        print(f"Error extracting video info: {e}")
        return None

def _fetch_metadata(video_url: str, video_id: str):
    """
    Use yt-dlp to fetch the info.json and thumbnail, bypassing the main video download.
    This works even heavily IP-blocked servers because it's just grabbing metadata.
    """
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s")
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-thumbnail",
        "--write-info-json",
        "--no-warnings",
        "--ignore-errors",
        "--output", outtmpl,
        "--cookies", cookie_path, # Fixed cookie bug!
        video_url
    ]
    
    print(f"Fetching metadata for {video_id} using yt-dlp...")
    subprocess.run(cmd, capture_output=True, text=True)
    
    base_path = os.path.join(DOWNLOAD_DIR, video_id)
    info_path = f"{base_path}.info.json"
    
    thumb_path = None
    for ext in ['jpg', 'webp', 'png']:
        possible_thumb = f"{base_path}.{ext}"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb
            break
            
    title = video_id
    description = ""
    
    if os.path.exists(info_path):
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                info_dict = json.load(f)
                title = info_dict.get('title', title)
                description = info_dict.get('description', '')
        except Exception as e:
            print(f"Could not read parsed info.json: {e}")
            
    return title, description, thumb_path, info_path

def download_video_cobalt(video_url: str, output_path: str) -> bool:
    """Attempt downloading the video chunk via Cobalt's v10+ API."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": video_url,
        "videoQuality": "max" # Get highest quality possible
    }
    
    for instance in COBALT_INSTANCES:
        print(f"Attempting Cobalt download via {instance}...")
        try:
            res = requests.post(f"{instance}/", headers=headers, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                dl_url = data.get("url")
                
                if dl_url:
                    print("Received Cobalt delivery URL. Starting stream...")
                    with requests.get(dl_url, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(output_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                    print("Cobalt download complete!")
                    return True
        except Exception as e:
            print(f"Cobalt {instance} failed: {e}")
            
    return False

def download_video_ytdlp(video_url: str, output_prefix: str) -> bool:
    """Fallback raw yt-dlp download if Cobalt fails entirely."""
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{output_prefix}.%(ext)s")
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    
    cmd = [
        "yt-dlp",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--output", outtmpl,
        "--write-thumbnail",
        "--write-info-json",
        "--no-warnings",
        "--ignore-errors",
        "--cookies", cookie_path, # Fixed cookie bug!
        video_url
    ]
    
    env = os.environ.copy()
    deno_path = os.path.expanduser("~/.deno/bin")
    if deno_path not in env.get("PATH", ""):
        env["PATH"] = deno_path + ":" + env.get("PATH", "")
        
    print(f"Running yt-dlp fallback command...")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    if result.returncode != 0 and not os.path.exists(os.path.join(DOWNLOAD_DIR, f"{output_prefix}.mp4")) and not os.path.exists(os.path.join(DOWNLOAD_DIR, f"{output_prefix}.mkv")):
        print(f"yt-dlp fallback failed for {video_url}:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        return False
        
    return True

def download_video(video_url, output_prefix=None):
    """
    Downloads video using Cobalt primary, yt-dlp fallback.
    Fetches proper metadata. Returns the payload dictionary.
    """
    info = get_video_info(video_url)
    if info:
        video_id = info.get('id')
    else:
        video_id = extract_video_id(video_url)
        
    if not output_prefix:
        output_prefix = video_id if video_id else "unknown_video"
            
    base_path = os.path.join(DOWNLOAD_DIR, output_prefix)
    target_mp4 = f"{base_path}.mp4"
    
    # 1. Grab Metadata (thumbnail, info.json, descriptions)
    title, description, thumb_path, info_path = _fetch_metadata(video_url, output_prefix)
    
    # 2. Try Cobalt Network First
    download_success = False
    
    if not os.path.exists(target_mp4):
        download_success = download_video_cobalt(video_url, target_mp4)
        
        # 3. Yt-Dlp Fallback if Cobalt fails
        if not download_success:
            print("Cobalt exhausted. Falling back to native yt-dlp...")
            download_success = download_video_ytdlp(video_url, output_prefix)
    else:
        print(f"Video {target_mp4} already exists on disk. Skipping download.")
        download_success = True
        
    if not download_success:
        return None
        
    # Check what extension yt-dlp saved it as if Cobalt didn't do it
    video_path = target_mp4
    if not os.path.exists(video_path):
        video_path = f"{base_path}.mkv"
        if not os.path.exists(video_path):
             video_path = f"{base_path}.webm"

    # Secondary check for thumbnail if yt-dlp grabbed it during fallback
    if not thumb_path:
        for ext in ['jpg', 'webp', 'png']:
            possible_thumb = f"{base_path}.{ext}"
            if os.path.exists(possible_thumb):
                thumb_path = possible_thumb
                break

    return {
        'video_id': output_prefix,
        'title': title,
        'description': description,
        'video_path': video_path,
        'info_path': info_path,
        'thumb_path': thumb_path
    }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = "https://www.youtube.com/watch?v=XzUKVV2uWcI"
        
    print(f"Testing download for {test_url}")
    res = download_video(test_url)
    print(f"Download result:\n{json.dumps(res, indent=2)}")
