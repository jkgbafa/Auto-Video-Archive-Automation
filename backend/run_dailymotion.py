"""
Upload all 1999 videos to Dailymotion.
Reads the playlist, downloads each video, uploads to Dailymotion,
updates Google Sheets, and sends Telegram progress notifications.
"""
import os
import sys
import yt_dlp

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import YOUTUBE_PLAYLIST_URL
from downloader import download_video
from uploader_dailymotion import upload_to_dailymotion
from notifier import send_telegram_message, update_google_sheet, notify_upload_success, notify_upload_failed

YEAR = "1999"
DM_ARCHIVE = f'dm_archive_{YEAR}.txt'

def main():
    print(f"Starting {YEAR} → Dailymotion Transfer...")
    
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
        
        # Download
        media_info = download_video(video_url)
        if not media_info or not media_info['video_path']:
            print(f"  Download failed!")
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
                import time
                time.sleep(24 * 60 * 60) # Sleep for 24 hours
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
