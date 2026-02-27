import requests
import json

instances = [
    'https://cobalt.q0.ooguy.com',
    'https://cobalt.kwiatektv.me',
    'https://co.wuk.sh',
    'https://api.cobalt.tools',
    'https://api.cobalt.beparanoid.de',
    'https://cobalt-api.kwiatektv.me'
]

headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}
data = {
    'url': 'https://www.youtube.com/watch?v=pnBUvlCyGfE'
}

for instance in instances:
    print(f'Trying {instance}...')
    try:
        response = requests.post(f'{instance}/api/json', headers=headers, json=data, timeout=10)
        print(response.status_code)
        print(response.json())
        if response.status_code == 200 and 'url' in response.json():
            print(f'SUCCESS with {instance}')
            break
    except Exception as e:
        print('Error:', e)
