import os
import sys
import yt_dlp
import json
from config import DOWNLOAD_DIR

# Ensure Deno is on PATH so yt-dlp can solve YouTube's n-signature JS challenge
DENO_PATH = os.path.expanduser("~/.deno/bin")
if DENO_PATH not in os.environ.get("PATH", ""):
    os.environ["PATH"] = DENO_PATH + ":" + os.environ.get("PATH", "")

def get_video_info(video_url):
    """
    Extract video information without downloading.
    """
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['android', 'ios']}}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(video_url, download=False)

import subprocess

def download_video(video_url, output_prefix=None):
    """
    Download the highest quality video/audio from a YouTube URL.
    Saves the video, thumbnail, and info.json to DOWNLOAD_DIR.
    Returns the paths to the downloaded files.
    """
    if not output_prefix:
        info = get_video_info(video_url)
        if info:
            output_prefix = info.get('id', '%(id)s')
        else:
            output_prefix = '%(id)s'
            
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
        "--extractor-args", "youtube:player_client=tv,android,ios",
        video_url
    ]
    
    env = os.environ.copy()
    deno_path = os.path.expanduser("~/.deno/bin")
    if deno_path not in env.get("PATH", ""):
        env["PATH"] = deno_path + ":" + env.get("PATH", "")
        
    print(f"Running download command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    if result.returncode != 0 and not os.path.exists(os.path.join(DOWNLOAD_DIR, f"{output_prefix}.mp4")) and not os.path.exists(os.path.join(DOWNLOAD_DIR, f"{output_prefix}.mkv")):
        print(f"Download failed for {video_url}:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        return None
        
    video_id = output_prefix
    
    # Determine the actual paths
    base_path = os.path.join(DOWNLOAD_DIR, video_id)
    
    video_path = f"{base_path}.mp4"
    if not os.path.exists(video_path):
        video_path = f"{base_path}.mkv" # Fallback if mp4 wasn't available
        
    info_path = f"{base_path}.info.json"
    
    # Check thumbnail extensions
    thumb_path = None
    for ext in ['jpg', 'webp', 'png']:
        possible_thumb = f"{base_path}.{ext}"
        if os.path.exists(possible_thumb):
            thumb_path = possible_thumb
            break
            
    # Read title from info.json
    title = ''
    description = ''
    try:
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                info_data = json.load(f)
                title = info_data.get('title', '')
                description = info_data.get('description', '')
    except Exception as e:
        print(f"Could not read info.json: {e}")
            
    return {
        'video_id': video_id,
        'title': title,
        'description': description,
        'video_path': video_path if os.path.exists(video_path) else None,
        'info_path': info_path if os.path.exists(info_path) else None,
        'thumb_path': thumb_path
    }
if __name__ == "__main__":
    # Test block
    test_url = "https://youtu.be/XzUKVV2uWcI"
    print(f"Testing download for {test_url}")
    res = download_video(test_url)
    print("Download result:", json.dumps(res, indent=2))
