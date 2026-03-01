"""
Internet Archive (archive.org) video uploader.

Uses the `internetarchive` Python library with S3-like API keys.

Authentication:
  - Go to https://archive.org/account/s3.php
  - Get your Access Key and Secret Key
  - Set IA_ACCESS_KEY and IA_SECRET_KEY in .env

Upload creates an "item" on archive.org with the video file.
Each item gets a permanent URL: https://archive.org/details/{identifier}

Rate limits: Generally generous, but large uploads may be throttled.
"""

import os
import re
import time
from config import DOWNLOAD_DIR

IA_ACCESS_KEY = os.getenv("IA_ACCESS_KEY", "")
IA_SECRET_KEY = os.getenv("IA_SECRET_KEY", "")

MAX_RETRIES = 2
RETRY_DELAY = 60


def has_credentials():
    """Check if Internet Archive credentials are configured."""
    return bool(IA_ACCESS_KEY and IA_SECRET_KEY)


def _make_identifier(title, year="2001"):
    """Create a valid archive.org identifier from a video title."""
    # Identifiers must be: alphanumeric, hyphens, underscores, periods
    # Max 100 chars, must be unique
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', title)
    slug = re.sub(r'\s+', '-', slug.strip())
    slug = slug[:80].rstrip('-')
    return f"dhm-{year}-{slug}"


def upload_to_internet_archive(video_path, title, description="", year="2001"):
    """
    Upload a video to Internet Archive.

    Returns the item identifier on success, None on failure.
    """
    if not os.path.exists(video_path):
        print(f"[IA] File not found: {video_path}")
        return None

    if not has_credentials():
        print("[IA] No credentials configured.")
        print("  1. Go to https://archive.org/account/s3.php")
        print("  2. Get Access Key and Secret Key")
        print("  3. Set IA_ACCESS_KEY and IA_SECRET_KEY in .env")
        return None

    identifier = _make_identifier(title, year)
    file_size = os.path.getsize(video_path)

    metadata = {
        'title': title,
        'description': description or title,
        'mediatype': 'movies',
        'collection': 'opensource_movies',
        'creator': 'Dag Heward-Mills',
        'subject': ['sermon', 'church', 'daghewardmills', f'{year}'],
        'date': year,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        prefix = f"[IA {attempt}/{MAX_RETRIES}]"
        print(f"{prefix} Uploading: {title[:50]} ({file_size / 1024 / 1024:.1f} MB)")
        print(f"{prefix} Identifier: {identifier}")

        try:
            import internetarchive

            r = internetarchive.upload(
                identifier,
                files=[video_path],
                metadata=metadata,
                access_key=IA_ACCESS_KEY,
                secret_key=IA_SECRET_KEY,
                retries=3,
                verbose=True,
            )

            # Check results
            success = all(resp.status_code == 200 for resp in r)
            if success:
                url = f"https://archive.org/details/{identifier}"
                print(f"[IA] Upload SUCCESS: {url}")
                return identifier
            else:
                statuses = [resp.status_code for resp in r]
                print(f"{prefix} Upload returned non-200 statuses: {statuses}")

        except Exception as e:
            print(f"{prefix} Upload error: {e}")

        if attempt < MAX_RETRIES:
            print(f"  Retrying in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    print(f"[IA] Upload failed after {MAX_RETRIES} attempts")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        if has_credentials():
            print(f"[IA] Credentials configured")
            print(f"  Access Key: {IA_ACCESS_KEY[:8]}...")
        else:
            print("[IA] No credentials configured")
            print("  Get keys at: https://archive.org/account/s3.php")

    elif len(sys.argv) > 2:
        video_path = sys.argv[1]
        title = sys.argv[2]
        result = upload_to_internet_archive(video_path, title)
        print(f"Result: {result}")

    else:
        print("Usage:")
        print("  python uploader_internet_archive.py --check")
        print("  python uploader_internet_archive.py <video> <title>")
