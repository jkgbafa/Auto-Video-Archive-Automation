import time
import os
from playwright.sync_api import sync_playwright
from config import BITCHUTE_USERNAME, BITCHUTE_PASSWORD

def _convert_thumbnail_to_jpeg(thumb_path):
    """Convert a WebP thumbnail to JPEG for Bitchute compatibility."""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    if thumb_path.lower().endswith(('.jpg', '.jpeg', '.png')):
        return thumb_path  # Already compatible
    try:
        from PIL import Image
        jpeg_path = os.path.splitext(thumb_path)[0] + '.jpg'
        img = Image.open(thumb_path).convert('RGB')
        img.save(jpeg_path, 'JPEG', quality=90)
        print(f"Converted thumbnail to JPEG: {jpeg_path}")
        return jpeg_path
    except Exception as e:
        print(f"Could not convert thumbnail: {e}")
        return None

def upload_to_bitchute(video_path, title, description, thumbnail_path=None):
    """
    Upload a video to Bitchute using Playwright.
    Since Bitchute has no API, we must automate the browser.
    """
    try:
        # Convert thumbnail to JPEG if needed
        thumb_to_use = _convert_thumbnail_to_jpeg(thumbnail_path)
        
        with sync_playwright() as p:
            # Launch headless chromium
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Navigate to login page
            print("Navigating to Bitchute login...")
            page.goto("https://old.bitchute.com/accounts/login/")
            
            # Fill login credentials
            page.fill("input[name='username']", BITCHUTE_USERNAME)
            page.fill("input[name='password']", BITCHUTE_PASSWORD)
            page.click("#submit")
            page.wait_for_load_state("networkidle")

            # Check if login was successful
            if "login" in page.url:
                print("Failed to login to Bitchute. Check credentials.")
                browser.close()
                return False

            print("Logged in successfully. Navigating to upload page...")
            # Navigate to upload page (Bitchute redirects to /channel/new/ if you have no channel)
            page.goto("https://old.bitchute.com/myupload/")
            page.wait_for_load_state("networkidle")

            if "channel/new" in page.url:
                print("Error: You must create a Bitchute channel first in your account before uploading!")
                browser.close()
                return False

            # Fill in Title
            page.fill("#title", title)
            
            # Fill description if provided
            if description:
                page.fill("#description", description)

            # Upload video file (FilePond is asynchronous)
            with page.expect_response("**/process_video", timeout=3600000) as response_info:
                page.set_input_files("input[name='videoInput']", video_path)
            print("Video file processed by Bitchute.")

            # Upload thumbnail if available and in a compatible format
            if thumb_to_use:
                try:
                    with page.expect_response("**/process_thumbnail", timeout=60000) as response_info:
                        page.set_input_files("input[name='thumbnailInput']", thumb_to_use)
                    print("Thumbnail processed by Bitchute.")
                except Exception as e:
                    print(f"Thumbnail upload failed (non-fatal): {e}")

            # Click Upload/Publish button
            page.click("button:has-text('Proceed')")
            
            print("Upload started. Waiting for completion...")
            # Wait for upload to complete or modal error
            # Bitchute redirects to /content/ on success, or shows #modal on error
            try:
                # Wait for either URL change or modal using JS
                page.wait_for_function("window.location.href.includes('/content') || (document.getElementById('modal') && document.getElementById('modal').style.display === 'block')", timeout=600000)
                
                if "content" not in page.url:
                    error_msg = page.locator("#errorMessage").text_content()
                    print(f"Bitchute Form Error: {error_msg}")
                    browser.close()
                    return False
            except Exception as e:
                print(f"Timeout waiting for Bitchute upload confirmation: {e}")
                browser.close()
                return False
            
            print(f"Successfully uploaded to Bitchute: {title}")
            browser.close()
            return True
            
    except Exception as e:
        print(f"Bitchute upload failed: {e}")
        return False
