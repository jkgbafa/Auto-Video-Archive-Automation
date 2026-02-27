import time
import schedule
import yt_dlp
from config import YOUTUBE_PLAYLIST_URL
from downloader import download_video
from uploader_dailymotion import upload_to_dailymotion
from uploader_bitchute import upload_to_bitchute
from db import add_video, update_status, get_pending_videos
from notifier import notify_new_video, notify_upload_success, notify_upload_failed, notify_milestone, update_google_sheet

# In a real scenario, we'd track last_checked to only download new videos
# For now, yt-dlp's download archive can handle skipping already downloaded videos.
DL_ARCHIVE = 'download_archive.txt'

def check_for_new_videos():
    print("Checking YouTube playlist for new videos...")
    if not YOUTUBE_PLAYLIST_URL:
        print("No YOUTUBE_PLAYLIST_URL configured.")
        return

    # Use yt-dlp to extract playlist context without downloading everything again
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(YOUTUBE_PLAYLIST_URL, download=False)
        if not info or 'entries' not in info:
            return
            
        entries = [e for e in info['entries'] if e]
        total_videos = len(entries)
        print(f"Total videos in playlist: {total_videos}")
        
        # Process all videos in the playlist
        
        # Read downloaded
        with open(DL_ARCHIVE, 'a+') as f:
            f.seek(0)
            downloaded = set(f.read().splitlines())
            
        processed_count = len(downloaded)
        
        # Track which milestones we've hit in this run to avoid spamming
        milestones = [25, 50, 75, 100]
        hit_milestones = [m for m in milestones if processed_count >= (m / 100) * total_videos]
            
        for entry in entries:
            video_url = entry.get('url')
            if entry['id'] in downloaded:
                continue
            
            # Found new video!
            print(f"New video found: {entry['title']}")
            
            # 1. Download it
            media_info = download_video(video_url)
            if not media_info or not media_info['video_path']:
                print(f"Failed to download {video_url}")
                continue
                
            # Update DL archive
            with open(DL_ARCHIVE, 'a') as f:
                f.write(f"{entry['id']}\n")
                
            title = media_info['title']
            desc = media_info['description']
            video_path = media_info['video_path']
            thumb_path = media_info['thumb_path']
            
            # 2. Add to Database
            add_video(entry['id'], title)
            
            # 3. Notify
            notify_new_video(title)
            
            # 4. Upload Bitchute
            update_status(entry['id'], "bitchute", "uploading")
            success = upload_to_bitchute(video_path, title, "", thumb_path)
            bc_status = "Pending"
            bc_url = ""
            if success:
                update_status(entry['id'], "bitchute", "completed")
                notify_upload_success(title, "Bitchute")
                bc_status = "Uploaded"
            else:
                update_status(entry['id'], "bitchute", "failed")
                notify_upload_failed(title, "Bitchute")
                bc_status = "Failed"

            # 5. Skip Dailymotion for now (auth flow needs fixing)
            dm_status = "Skipped"
            dm_url = ""

            # 6. Update Google Sheets
            update_google_sheet(video_url, title, bc_status, dm_status, bc_url, dm_url)

            # 7. Clean up downloaded video to save disk space
            import os
            if os.path.exists(video_path):
                os.remove(video_path)
                print(f"Cleaned up: {video_path}")
                
            # Update counts and check milestones
            processed_count += 1
            downloaded.add(entry['id'])
            
            if total_videos > 0:
                current_percent = (processed_count / total_videos) * 100
                for m in milestones:
                    if current_percent >= m and m not in hit_milestones:
                        notify_milestone(m, total_videos, processed_count)
                        hit_milestones.append(m)

def run_scheduler():
    print("Starting video archiving worker — Full 1999 Bitchute Transfer...")
    check_for_new_videos()
    print("Transfer complete.")

if __name__ == "__main__":
    # Ensure archive file exists
    open(DL_ARCHIVE, 'a').close()
    run_scheduler()
