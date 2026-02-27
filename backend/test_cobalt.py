import requests
import json
import time

COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt.api.unbound.so",
    "https://co.wuk.sh",
    "https://cobalt.qwyx.icu",
    "https://cobalt-api.kwiatekit.com",
    "https://cobalt.canine.cloud",
    "https://api.cobalt.chat"
]

def test_cobalt(video_url):
    print(f"Testing Cobalt API for: {video_url}")
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "url": video_url,
        "videoQuality": "max"
    }
    
    working_instances = []
    
    for instance in COBALT_INSTANCES:
        print(f"\nTrying {instance} ...", end=" ")
        try:
            res = requests.post(
                f"{instance}/",
                headers=headers,
                json=payload,
                timeout=15
            )
            
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "redirect" or data.get("status") == "stream" or "url" in data:
                    dl_url = data.get("url")
                    if dl_url:
                        print("SUCCESS! Got URL.")
                        # Verify with HEAD request
                        try:
                            head_res = requests.head(dl_url, timeout=10, allow_redirects=True)
                            if head_res.status_code == 200:
                                print(f"  HEAD check passed! Size: {head_res.headers.get('content-length', 'unknown')} bytes")
                                working_instances.append(instance)
                            else:
                                print(f"  HEAD check failed with status: {head_res.status_code}")
                        except Exception as e:
                            print(f"  HEAD check error: {e}")
                    else:
                        print(f"FAILED (No URL in response: {data})")
                elif data.get("status") == "error":
                    print(f"FAILED (API Error: {data.get('text', 'unknown')})")
                else:
                    print(f"FAILED (Unknown status: {data})")
            else:
                print(f"FAILED (HTTP {res.status_code})")
        except requests.exceptions.Timeout:
            print("FAILED (Timeout)")
        except requests.exceptions.RequestException as e:
            print(f"FAILED (Connection Error: {type(e).__name__})")
            
    print("\n--- Summary ---")
    if working_instances:
        print(f"Found {len(working_instances)} working instances:")
        for w in working_instances:
            print(f" - {w}")
    else:
        print("No working instances found!")

if __name__ == "__main__":
    test_cobalt("https://www.youtube.com/watch?v=jNQXAC9IVRw")
