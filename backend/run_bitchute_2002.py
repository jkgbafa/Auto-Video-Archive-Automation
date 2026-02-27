"""
Upload all 2002 videos to Bitchute.
Reads the playlist, downloads each video, uploads to Bitchute,
updates Google Sheets, and sends Telegram progress notifications.
"""
import os
import sys
import yt_dlp

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from downloader import download_video
from uploader_bitchute import upload_to_bitchute
from notifier import send_telegram_message, update_google_sheet, notify_upload_success, notify_upload_failed

# Configuration for 2002 Batch
YOUTUBE_PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLH2edYFEYwL88r3Vs5MDSSN3rwsqqQ18O"
BITCHUTE_USERNAME = "dhm2002archive@gmail.com"
BITCHUTE_PASSWORD = "SeeMe123!"
YEAR = "2002"
BC_ARCHIVE = f'bitchute_archive_{YEAR}.txt'

def main():
    print(f"Starting {YEAR} → Bitchute Transfer...")
    
    # Extract playlist
    ydl_opts = {'extract_flat': True, 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_PLAYLIST_URL, download=False)
        entries = [e for e in info['entries'] if e]
    
    total = len(entries)
    print(f"Total videos: {total}")
    
    # Send start notification
    send_telegram_message(f"🟠 <b>Starting {YEAR} → Bitchute</b>\n{total} videos to upload")
    
    # Read already uploaded
    if os.path.exists(BC_ARCHIVE):
        with open(BC_ARCHIVE) as f:
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
            notify_upload_failed(title, "Bitchute", "Download failed", i, total)
            failed_count += 1
            continue
        
        video_path = media_info['video_path']
        actual_title = media_info['title']  # Use exact YouTube title
        thumb_path = media_info.get('thumb_path')
        
        # Upload to Bitchute
        success = upload_to_bitchute(
            video_path=video_path,
            title=actual_title,
            description="",
            thumbnail_path=thumb_path,
            username=BITCHUTE_USERNAME,
            password=BITCHUTE_PASSWORD
        )
        
        if success:
            uploaded_count += 1
            
            # Mark as done
            with open(BC_ARCHIVE, 'a') as f:
                f.write(f"{vid_id}\n")
            
            # Update Google Sheet (update Bitchute columns only)
            update_google_sheet(video_url, actual_title, "", "Uploaded", "", "", year=YEAR)
            notify_upload_success(actual_title, "Bitchute", uploaded_count, total)
        else:
            failed_count += 1
            update_google_sheet(video_url, actual_title, "", "Failed", "", "", year=YEAR)
            notify_upload_failed(actual_title, "Bitchute", "Upload failed", i, total)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"  Cleaned up: {video_path}")
            
        # Also clean up the downloaded thumbnail regardless of success/fail
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
            
        # Clean up converted jpeg if it was created
        if thumb_path:
            jpeg_path = os.path.splitext(thumb_path)[0] + '.jpg'
            if os.path.exists(jpeg_path):
                os.remove(jpeg_path)
    
    # Final summary
    summary = (
        f"🎉 <b>{YEAR} → Bitchute Complete!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ Uploaded: {uploaded_count}/{total}\n"
        f"❌ Failed: {failed_count}\n"
    )
    send_telegram_message(summary)
    print(f"\nDone! Uploaded: {uploaded_count}, Failed: {failed_count}")

if __name__ == "__main__":
    main()
