"""
Test Cobalt API instances to find one that works for YouTube downloads.

Cobalt v10+ API format:
  POST /  (not /api/json)
  Body: {"url": "...", "videoQuality": "max"}
  Headers: Accept: application/json, Content-Type: application/json

Response on success:
  {"status": "tunnel"|"redirect", "url": "https://..."}
"""
import requests
import json

# Updated instance list — no-auth, high-score instances from instances.cobalt.best
instances = [
    'https://cobalt-backend.canine.tools',
    'https://cobalt-api.meowing.de',
    'https://kityune.imput.net',
    'https://nachos.imput.net',
    'https://capi.3kh0.net',
]

headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

# New v10+ payload format
data = {
    'url': 'https://www.youtube.com/watch?v=pnBUvlCyGfE',
    'videoQuality': 'max',
}

print("Testing Cobalt v10+ API instances...\n")

for instance in instances:
    api_url = instance.rstrip('/')
    print(f'Trying {api_url} ...')
    try:
        # v10+ uses POST to root, not /api/json
        response = requests.post(api_url, headers=headers, json=data, timeout=15)
        print(f'  Status: {response.status_code}')

        resp_data = response.json()
        print(f'  Response: {json.dumps(resp_data, indent=2)[:500]}')

        status = resp_data.get('status')
        download_url = resp_data.get('url')

        if response.status_code == 200 and download_url:
            print(f'\n  SUCCESS with {api_url}')
            print(f'  Status: {status}')
            print(f'  Download URL: {download_url[:120]}...')

            # Quick check that the download URL is actually reachable
            head = requests.head(download_url, timeout=10, allow_redirects=True)
            content_type = head.headers.get('Content-Type', '')
            content_length = head.headers.get('Content-Length', 'unknown')
            print(f'  Content-Type: {content_type}')
            print(f'  Content-Length: {content_length}')
            break
        else:
            print(f'  FAILED (no download URL or bad status)')

    except requests.exceptions.Timeout:
        print('  Timeout')
    except Exception as e:
        print(f'  Error: {e}')

    print()
