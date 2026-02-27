"""
Upload all 1999 videos to Dailymotion.
Reads the playlist, downloads each video, uploads to Dailymotion,
updates Google Sheets, and sends Telegram progress notifications.
"""
import os
import sys
import time
import json
import yt_dlp

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import YOUTUBE_PLAYLIST_URL
from downloader import download_video
from uploader_dailymotion import upload_to_dailymotion
from notifier import send_telegram_message, update_google_sheet, notify_upload_success, notify_upload_failed

YEAR = "1999"
DM_ARCHIVE = f'dm_archive_{YEAR}.txt'
RATE_LIMIT_FILE = f'dm_ratelimit_state_{YEAR}.json'

def handle_existing_rate_limit():
    """Check if we previously hit a rate limit and resume the sleep timer if needed."""
    if os.path.exists(RATE_LIMIT_FILE):
        try:
            with open(RATE_LIMIT_FILE, 'r') as f:
                state = json.load(f)
            
            timestamp = state.get('timestamp', 0)
            elapsed = time.time() - timestamp
            remaining_sleep = (24 * 60 * 60) - elapsed
            
            if remaining_sleep > 0:
                print(f"Resuming from previous rate limit state.")
                msg = f"⏳ **Resuming Dailymotion Sleep Timer**\nStill have {int(remaining_sleep / 3600)}h {(int(remaining_sleep) % 3600) // 60}m left on rate-limit penalty."
                print(msg)
                send_telegram_message(msg)
                time.sleep(remaining_sleep)
                
            print("Rate limit penalty cleared. Removing state file.")
            os.remove(RATE_LIMIT_FILE)
        except Exception as e:
            print(f"Error handling rate limit state: {e}")
            if os.path.exists(RATE_LIMIT_FILE):
                os.remove(RATE_LIMIT_FILE)

def main():
    print(f"Starting {YEAR} → Dailymotion Transfer...")
    
    # Check if we woke up from a system reboot during a rate limit block
    handle_existing_rate_limit()
    
    # Extract playlist
    ydl_opts = {'extract_flat': True, 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_PLAYLIST_URL, download=False)
        entries = [e for e in info['entries'] if e]
    
    total = len(entries)
    print(f"Total videos: {total}")
    
    # Send start notification
    send_telegram_message(f"🔵 <b>Starting {YEAR} → Dailymotion</b>\n{total} videos to upload")
    
    # Read already uploaded
    if os.path.exists(DM_ARCHIVE):
        with open(DM_ARCHIVE) as f:
            done_ids = set(f.read().splitlines())
    else:
        done_ids = set()
    
    uploaded_count = len(done_ids)
    failed_count = 0
    
    for i, entry in enumerate(entries, 1):
        vid_id = entry['id']
        title = entry.get('title', vid_id)
        video_url = entry.get('url', f'https://www.youtube.com/watch?v={vid_id}')
        
        if vid_id in done_ids:
            print(f"[{i}/{total}] Already done: {title}")
            continue
        
        print(f"\n[{i}/{total}] Processing: {title}")
        
        # Download (with 1 retry)
        media_info = None
        for dl_attempt in range(2):
            media_info = download_video(video_url)
            if media_info and media_info.get('video_path'):
                break
            print(f"Download failed (Attempt {dl_attempt + 1}). Retrying...")
            time.sleep(10)
            
        if not media_info or not media_info.get('video_path'):
            print(f"  Download permanently failed after retries!")
            notify_upload_failed(title, "Dailymotion", "Download failed", i, total)
            failed_count += 1
            continue
        
        video_path = media_info['video_path']
        actual_title = media_info['title']  # Use exact YouTube title
        
        # Upload to Dailymotion
        while True:
            dm_id = upload_to_dailymotion(video_path, actual_title, "")
            
            if dm_id == "RATE_LIMITED":
                msg = f"⏳ **Dailymotion Daily Limit Reached**\nPaused at: {title}\nSleeping for 24 hours..."
                print(msg)
                send_telegram_message(msg)
                
                # Write state to disk so progress survives reboot
                state = {
                    "video_id": vid_id,
                    "title": title,
                    "timestamp": time.time()
                }
                with open(RATE_LIMIT_FILE, 'w') as f:
                    json.dump(state, f)
                
                time.sleep(24 * 60 * 60) # Sleep for 24 hours
                
                # Sleep finished successfully, clear state file
                if os.path.exists(RATE_LIMIT_FILE):
                    os.remove(RATE_LIMIT_FILE)
                    
                continue # Retry this same video
                
            break # Success or failure
        
        if dm_id:
            uploaded_count += 1
            dm_url = f"https://www.dailymotion.com/video/{dm_id}"
            
            # Mark as done
            with open(DM_ARCHIVE, 'a') as f:
                f.write(f"{vid_id}\n")
            
            # Update Google Sheet (update DM columns only)
            update_google_sheet(video_url, actual_title, "", "Uploaded", "", dm_url, year=YEAR)
            notify_upload_success(actual_title, "Dailymotion", uploaded_count, total)
        else:
            failed_count += 1
            update_google_sheet(video_url, actual_title, "", "Failed", "", "", year=YEAR)
            notify_upload_failed(actual_title, "Dailymotion", "Upload failed", i, total)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"  Cleaned up: {video_path}")
            
        # Clean up thumbnail if downloaded
        if media_info.get('thumb_path') and os.path.exists(media_info['thumb_path']):
            os.remove(media_info['thumb_path'])
    
    # Final summary
    summary = (
        f"🎉 <b>{YEAR} → Dailymotion Complete!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ Uploaded: {uploaded_count}/{total}\n"
        f"❌ Failed: {failed_count}\n"
    )
    send_telegram_message(summary)
    print(f"\nDone! Uploaded: {uploaded_count}, Failed: {failed_count}")

if __name__ == "__main__":
    main()
