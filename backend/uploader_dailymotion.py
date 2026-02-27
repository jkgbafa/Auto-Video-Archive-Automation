import os
import requests
import time
from config import DAILYMOTION_USERNAME, DAILYMOTION_PASSWORD, DAILYMOTION_API_KEY, DAILYMOTION_API_SECRET, DAILYMOTION_REFRESH_TOKEN

def authenticate():
    """
    Authenticate with Dailymotion API to get an access token.
    Uses refresh_token (from authorization code flow) if available,
    otherwise falls back to password grant (deprecated).
    """
    auth_url = "https://api.dailymotion.com/oauth/token"
    
    # Prefer refresh token (from dm_authorize.py)
    if DAILYMOTION_REFRESH_TOKEN:
        payload = {
            'grant_type': 'refresh_token',
            'client_id': DAILYMOTION_API_KEY,
            'client_secret': DAILYMOTION_API_SECRET,
            'refresh_token': DAILYMOTION_REFRESH_TOKEN,
        }
        try:
            response = requests.post(auth_url, data=payload, timeout=30)
            if response.status_code == 200:
                token_data = response.json()
                token = token_data.get('access_token')
                if token:
                    print("✅ AUTH SUCCESS: Authenticated via OAuth refresh token.")
                    return token
            print(f"⚠️ AUTH WARNING: Refresh token failed (HTTP {response.status_code}): {response.text}.")
        except Exception as e:
            print(f"⚠️ AUTH WARNING: Refresh token network error: {e}")
            
    print("⚠️ AUTH WARNING: Falling back to deprecated password grant method!")
    
    # Fallback: password grant (deprecated, may not work)
    payload = {
        'grant_type': 'password',
        'client_id': DAILYMOTION_API_KEY,
        'client_secret': DAILYMOTION_API_SECRET,
        'username': DAILYMOTION_USERNAME,
        'password': DAILYMOTION_PASSWORD,
        'scope': 'manage_videos'
    }
    
    response = requests.post(auth_url, data=payload, timeout=30)
    response.raise_for_status()
    token_data = response.json()
    token = token_data.get('access_token')
    if token:
        print("✅ AUTH SUCCESS: Authenticated via deprecated password grant.")
        return token
    else:
        raise Exception("Auth failed: No access token in response.")

def get_upload_url(access_token):
    """
    Get the upload URL from Dailymotion.
    """
    url = "https://api.dailymotion.com/file/upload"
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json().get('upload_url')

def upload_file(upload_url, video_path):
    """
    Upload the video file to the given upload URL.
    Returns the uploaded file URL necessary for the next step.
    """
    with open(video_path, 'rb') as f:
        # 7200 seconds = 2 hours timeout for large files
        response = requests.post(upload_url, files={'file': f}, timeout=7200)
        response.raise_for_status()
        return response.json().get('url')

def create_video(access_token, file_url, title, description, tags=None, private=False):
    """
    Publish the uploaded file as a video with metadata.
    Title always comes directly from YouTube (the source of truth).
    """
    url = "https://api.dailymotion.com/me/videos"
    headers = {'Authorization': f'Bearer {access_token}'}
    payload = {
        'url': file_url,
        'title': title[:255],
        'description': description if description else title,
        'channel': 'news',
        'language': 'en',
        'published': 'true',
        'private': 'false',
        'tags': 'sermon,church,daghewardmills',
    }
    if tags:
        payload['tags'] = ','.join(tags[:10])
        
    response = requests.post(url, headers=headers, data=payload, timeout=60)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"HTTPError in create_video: {e.response.status_code} - {e.response.text}")
        try:
            error_data = e.response.json().get('error', {}).get('error_data', {})
            if error_data.get('reason') == 'upload_limit_exceeded':
                return {"_internal_status": "RATE_LIMITED"}
        except:
            pass
        raise
    return response.json()

def upload_to_dailymotion(video_path, title, description, tags=None):
    """
    Full pipeline to upload a video to Dailymotion.
    Gets a fresh token every time to avoid 403s from expired tokens.
    Implements exponential backoff retries for transient errors.
    """
    max_retries = 3
    delays = [30, 60, 120]
    
    for attempt in range(max_retries + 1):
        try:
            print(f"Authenticating Dailymotion (Attempt {attempt + 1})...")
            token = authenticate()  # Fresh token every upload
            
            print(f"Getting upload URL...")
            upload_url = get_upload_url(token)
            
            print(f"Uploading file {video_path}...")
            file_url = upload_file(upload_url, video_path)
            
            print(f"Publishing video...")
            video_data = create_video(token, file_url, title, description, tags)
            
            if video_data.get("_internal_status") == "RATE_LIMITED":
                print(f"Dailymotion daily limit reached!")
                return "RATE_LIMITED"
                
            print(f"Successfully uploaded to Dailymotion: {video_data.get('id')}")
            return video_data.get('id')
            
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            if 400 <= status_code < 500 and status_code != 429:
                print(f"Permanent HTTP Error {status_code} during Dailymotion upload: {e}. Skipping retries.")
                return None
            else:
                print(f"Transient HTTP Error {status_code} during upload: {e}")
        except Exception as e:
            print(f"Dailymotion upload error: {e}")
            
        if attempt < max_retries:
            delay = delays[attempt]
            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)
            
    print(f"Dailymotion upload failed after {max_retries + 1} attempts.")
    return None
