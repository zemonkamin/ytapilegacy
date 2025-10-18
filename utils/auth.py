import requests
import json
import qrcode
import io
import base64
import time
import secrets
import html
from urllib.parse import quote
from threading import Lock

# Global dictionary to store tokens by session ID
token_store = {}
token_store_lock = Lock()

# These will be set when the auth module is initialized
CLIENT_ID = ''
CLIENT_SECRET = ''
REDIRECT_URI = ''
SCOPES = []

def init_auth_config(client_id, client_secret, redirect_uri, scopes):
    """Initialize authentication configuration"""
    global CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPES
    CLIENT_ID = client_id
    CLIENT_SECRET = client_secret
    REDIRECT_URI = redirect_uri
    SCOPES = scopes

def get_auth_url(session_id):
    """Get authorization URL with session_id in state parameter"""
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'state': session_id
    }
    auth_request = requests.Request('GET', 'https://accounts.google.com/o/oauth2/auth', params=params)
    return auth_request.prepare().url

def get_access_token(auth_code):
    """Exchange code for access token and refresh token"""
    data = {
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }
    response = requests.post('https://oauth2.googleapis.com/token', data=data)
    response.raise_for_status()
    return response.json()

def refresh_access_token(refresh_token):
    """Get new access token using refresh token"""
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    response = requests.post('https://oauth2.googleapis.com/token', data=data)
    response.raise_for_status()
    return response.json()
    
def get_account_info(access_token):
    """Get Google account information using access token"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    # Get basic profile info
    profile_response = requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers=headers,
        timeout=30  # Assuming timeout from config
    )
    
    if profile_response.status_code != 200:
        return None
    
    profile_data = profile_response.json()
    
    # Get YouTube channel info if available
    youtube_data = None
    try:
        youtube_response = requests.get(
            'https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true',
            headers=headers,
            timeout=30  # Assuming timeout from config
        )
        if youtube_response.status_code == 200:
            youtube_data = youtube_response.json()
    except:
        youtube_data = None
    
    return {
        'profile': profile_data,
        'youtube': youtube_data
    }

def generate_qr_code(auth_url):
    """Generate QR code for authentication URL"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(auth_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)
    
    qr_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    return qr_base64