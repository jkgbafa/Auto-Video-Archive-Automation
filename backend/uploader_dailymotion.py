import os
import time
import requests
from config import DAILYMOTION_USERNAME, DAILYMOTION_PASSWORD, DAILYMOTION_API_KEY, DAILYMOTION_API_SECRET, DAILYMOTION_REFRESH_TOKEN

# Retry configuration
MAX_UPLOAD_RETRIES = 3
RETRY_BASE_DELAY = 30  # seconds — retries at 30s, 60s, 120s


def authenticate():
    """
    Authenticate with Dailymotion API to get an access token.
    Uses refresh_token (from authorization code flow) if available,
    otherwise falls back to password grant (deprecated).
    """
    auth_url = "https://api.dailymotion.com/oauth/token"

    # --- Attempt 1: Refresh token (preferred) ---
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
                    print("[AUTH] Authenticated via refresh_token (OK)")
                    return token
            print(f"[AUTH] Refresh token FAILED (HTTP {response.status_code}): {response.text[:200]}")
        except Exception as e:
            print(f"[AUTH] Refresh token request error: {e}")
    else:
        print("[AUTH] No DAILYMOTION_REFRESH_TOKEN configured, skipping refresh_token method")

    # --- Attempt 2: Password grant (deprecated fallback) ---
    print("[AUTH] WARNING: Falling back to password grant — this method is DEPRECATED by Dailymotion")
    print("[AUTH] If this fails, you need to re-run dm_authorize.py to get a fresh refresh_token")
    payload = {
        'grant_type': 'password',
        'client_id': DAILYMOTION_API_KEY,
        'client_secret': DAILYMOTION_API_SECRET,
        'username': DAILYMOTION_USERNAME,
        'password': DAILYMOTION_PASSWORD,
        'scope': 'manage_videos'
    }

    try:
        response = requests.post(auth_url, data=payload, timeout=30)
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get('access_token')
        if token:
            print("[AUTH] Authenticated via password grant (OK, but deprecated)")
            return token
        print(f"[AUTH] Password grant returned no token: {token_data}")
    except requests.exceptions.HTTPError as e:
        print(f"[AUTH] Password grant FAILED (HTTP {e.response.status_code}): {e.response.text[:200]}")
        raise
    except Exception as e:
        print(f"[AUTH] Password grant request error: {e}")
        raise

    raise RuntimeError("All Dailymotion authentication methods failed")


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
    Uses a longer timeout since video files can be very large.
    """
    file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"  Uploading {file_size_mb:.1f} MB ...")

    with open(video_path, 'rb') as f:
        # Allow up to 2 hours for very large files
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

    - Gets a fresh token every attempt to avoid 403s from expired tokens.
    - Retries up to MAX_UPLOAD_RETRIES times with exponential backoff on
      transient failures (network errors, timeouts, 5xx responses).
    - Returns the Dailymotion video ID on success, "RATE_LIMITED" if the
      daily upload cap is hit, or None on permanent failure.
    """
    last_error = None

    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            prefix = f"[Attempt {attempt}/{MAX_UPLOAD_RETRIES}]"

            print(f"{prefix} Authenticating Dailymotion ...")
            token = authenticate()  # Fresh token every attempt

            print(f"{prefix} Getting upload URL ...")
            upload_url = get_upload_url(token)

            print(f"{prefix} Uploading file {video_path} ...")
            file_url = upload_file(upload_url, video_path)

            print(f"{prefix} Publishing video ...")
            video_data = create_video(token, file_url, title, description, tags)

            if video_data.get("_internal_status") == "RATE_LIMITED":
                print(f"{prefix} Dailymotion daily limit reached!")
                return "RATE_LIMITED"

            dm_id = video_data.get('id')
            print(f"{prefix} Successfully uploaded to Dailymotion: {dm_id}")
            return dm_id

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError) as e:
            last_error = e
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)

            # Don't retry on 4xx errors (except 429 rate limit)
            if status_code and 400 <= status_code < 500 and status_code != 429:
                print(f"{prefix} Permanent HTTP error ({status_code}), not retrying: {e}")
                break

            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))  # 30s, 60s, 120s
            print(f"{prefix} Transient error: {e}")
            if attempt < MAX_UPLOAD_RETRIES:
                print(f"  Retrying in {delay}s ...")
                time.sleep(delay)

        except Exception as e:
            last_error = e
            print(f"{prefix} Unexpected error: {e}")
            if attempt < MAX_UPLOAD_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  Retrying in {delay}s ...")
                time.sleep(delay)

    print(f"Dailymotion upload permanently failed after {MAX_UPLOAD_RETRIES} attempts: {last_error}")
    return None
