"""
Odysee Authentication Helper.

Obtains an auth token for the Odysee API and saves it to odysee_token.json.

Usage:
  python odysee_auth.py                    # Try API signin with .env credentials
  python odysee_auth.py --browser-token TOKEN  # Save a token extracted from browser
  python odysee_auth.py --verify           # Verify saved token is valid
"""
import os
import sys
import json
import time
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'odysee_token.json')
ODYSEE_API = "https://api.odysee.com"


def save_token(auth_token, email=""):
    """Save auth token to disk."""
    with open(TOKEN_FILE, 'w') as f:
        json.dump({
            'auth_token': auth_token,
            'email': email,
            'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }, f, indent=2)
    print(f"Token saved to {TOKEN_FILE}")


def verify_token(token=None):
    """Check if a token is valid."""
    if token is None:
        if not os.path.exists(TOKEN_FILE):
            print("No saved token found.")
            return False
        with open(TOKEN_FILE) as f:
            token = json.load(f).get('auth_token')

    r = requests.post(f'{ODYSEE_API}/user/me', data={'auth_token': token}, timeout=15)
    if r.status_code == 200:
        data = r.json()
        if data.get('success'):
            user = data.get('data', {})
            print(f"Token is VALID!")
            print(f"  User ID: {user.get('id')}")
            print(f"  Email verified: {user.get('has_verified_email')}")
            print(f"  Email: {user.get('primary_email', 'none')}")
            return user.get('has_verified_email', False)
    print(f"Token is INVALID or expired.")
    return False


def signin_api(email, password):
    """Try to sign in via the API."""
    # Step 1: Get anonymous token
    r = requests.post(f'{ODYSEE_API}/user/new', data={}, timeout=15)
    if r.status_code != 200 or not r.json().get('success'):
        print(f"Failed to create anonymous user: {r.text[:200]}")
        return None

    temp_token = r.json()['data']['auth_token']
    print(f"Anonymous token created: {temp_token[:15]}...")

    # Step 2: Sign in
    r = requests.post(f'{ODYSEE_API}/user/signin', data={
        'auth_token': temp_token,
        'email': email,
        'password': password,
    }, timeout=15)

    if r.status_code == 200 and r.json().get('success'):
        print(f"Signed in successfully!")
        save_token(temp_token, email)
        return temp_token

    error = r.json().get('error', r.text[:200])
    print(f"Signin failed: {error}")
    print()
    print("If the password is wrong, try one of these methods:")
    print("  1. Log into odysee.com in Chrome")
    print("  2. Open DevTools > Application > Cookies > odysee.com")
    print("  3. Copy the 'auth_token' cookie value")
    print(f"  4. Run: python odysee_auth.py --browser-token YOUR_TOKEN")
    return None


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass

    if len(sys.argv) > 1:
        if sys.argv[1] == '--verify':
            verify_token()
            return

        if sys.argv[1] == '--browser-token' and len(sys.argv) > 2:
            token = sys.argv[2]
            if verify_token(token):
                email = os.getenv('ODYSEE_EMAIL', '')
                save_token(token, email)
                print("Browser token saved and verified!")
            else:
                print("Token verification failed. Make sure you copied it correctly.")
            return

    # Try API signin
    email = os.getenv('ODYSEE_EMAIL', '')
    password = os.getenv('ODYSEE_PASSWORD', '')

    if not email:
        print("No ODYSEE_EMAIL in .env file")
        return

    print(f"Attempting to sign in as {email}...")
    signin_api(email, password)


if __name__ == "__main__":
    main()
