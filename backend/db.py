from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

# Initialize Supabase client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_db():
    pass # In a real scenario we'd create the table if it didn't exist or rely on Supabase UI

def add_video(video_id, title):
    if not supabase: return
    data = {
        "video_id": video_id,
        "title": title,
        "status_dailymotion": "pending",
        "status_bitchute": "pending",
    }
    # Upsert to avoid duplicates
    supabase.table("videos").upsert(data).execute()

def update_status(video_id, platform, status):
    if not supabase: return
    data = {f"status_{platform}": status}
    supabase.table("videos").update(data).eq("video_id", video_id).execute()

def get_pending_videos(platform):
    if not supabase: return []
    response = supabase.table("videos").select("*").eq(f"status_{platform}", "pending").execute()
    return response.data
