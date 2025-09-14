import os
import sys
import json
import requests
import qrcode
import io
import time
import base64
import re
from flask import Flask, request, jsonify, Response, send_file, redirect
from flask_cors import CORS
from flask import session
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode, urlparse, parse_qs
import yt_dlp
import googleapiclient.discovery
import subprocess
import html
from threading import Lock, Thread
import threading
import secrets

app = Flask(__name__)
CORS(app)

# Load configuration from config.json
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
    
app = Flask(__name__)
app.secret_key = config.get('secretkey', '')
CORS(app)

# OAuth configuration from config
CLIENT_ID = config.get('oauth_client_id', '')
CLIENT_SECRET = config.get('oauth_client_secret', '')
REDIRECT_URI = "https://yt.legacyprojects.ru/oauth/callback"
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email'
]

# Global dictionary to store tokens by session ID
token_store = {}
token_store_lock = Lock()

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
        timeout=config['request_timeout']
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
            timeout=config['request_timeout']
        )
        if youtube_response.status_code == 200:
            youtube_data = youtube_response.json()
    except:
        youtube_data = None
    
    return {
        'profile': profile_data,
        'youtube': youtube_data
    }

def mark_stream_start():
    print(f"Stream started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def mark_stream_end():
    print(f"Stream ended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Helper functions
def get_channel_thumbnail(channel_id, api_key):
    """Get channel thumbnail with multiple fallback methods"""
    if not config['fetch_channel_thumbnails']:
        return ''
    
    print(f"DEBUG: Getting channel thumbnail for channel_id: {channel_id}")
    
    # Method 1: Try YouTube API to get channel thumbnail
    try:
        r = requests.get(
            f"https://www.googleapis.com/youtube/v3/channels?id={channel_id}&key={api_key}&part=snippet", 
            timeout=config['request_timeout']
        )
        r.raise_for_status()
        data = r.json()
        
        print(f"DEBUG: API response: {json.dumps(data, ensure_ascii=False)[:200]}...")
        
        if data.get('items') and data['items']:
            # Get channel thumbnail from channel data
            channel_snippet = data['items'][0]['snippet']
            thumbnail_url = channel_snippet['thumbnails']['default']['url']
            print(f"DEBUG: Found channel thumbnail: {thumbnail_url}")
            return thumbnail_url
        else:
            print("DEBUG: No items in API response")
                
    except Exception as e:
        print(f'Error getting channel thumbnail from API for {channel_id}: {e}')
    
    # Fallback
    return 'https://yt3.ggpht.com/a/default-user=s88-c-k-c0x00ffffff-no-rj'

def get_proxy_url(url, use_proxy):
    if not use_proxy:
        return url
    if url.startswith('https://i.ytimg.com'):
        return f"https://qqq.bccst.ru/youtube/image-proxy.php?url={url}"
    return url

def get_video_proxy_url(url, use_proxy):
    if not use_proxy:
        return url
    return f"https://qqq.bccst.ru/youtube/video-proxy.php?url={url}"

def get_final_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=config['request_timeout'])
        return r.url
    except Exception as e:
        print('get_final_url error:', e)
        return None

def url_exists(url):
    try:
        r = requests.head(url, timeout=config['request_timeout'])
        return r.status_code == 200
    except Exception as e:
        print('url_exists error:', e)
        return False

def get_direct_video_url(video_id, quality=None):
    ydl_opts = {
        'quiet': True,
        'format': 'best' if not quality else f'best[height<={quality}]',
        'noplaylist': True,
    }
    if config.get('use_cookies', True):
        ydl_opts['cookiefile'] = 'cookies.txt'
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            formats = info.get('formats', [])
            selected_format = info.get('url')
            print(f"Video ID: {video_id}, Quality requested: {quality}")
            print(f"Selected format URL: {selected_format}")
            print(f"Available formats: {[f.get('height', 'N/A') for f in formats if f.get('height')]}")
            if not selected_format:
                print(f"No URL found for video_id: {video_id}, quality: {quality}")
                return None
            return selected_format
    except yt_dlp.utils.DownloadError as de:
        print(f"DownloadError for video_id {video_id}, quality {quality}: {str(de)}")
        return None
    except Exception as e:
        print(f"Unexpected error in get_direct_video_url for video_id {video_id}, quality {quality}: {str(e)}")
        return None

def get_real_direct_video_url(video_id):
    """Возвращает прямую ссылку на видео через yt_dlp (без прокси и без /direct_url)."""
    ydl_opts = {
        'quiet': True,
        'format': 'best',
    }
    if config.get('use_cookies', True):
        ydl_opts['cookiesfrombrowser'] = None
        ydl_opts['cookiefile'] = 'cookies.txt'
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            return info.get('url')
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_video_info_dict(video_id, apikey, use_video_proxy=True):
    try:
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={apikey}&part=snippet,contentDetails,statistics", timeout=config['request_timeout'])
        resp.raise_for_status()
        data = resp.json()
        videoData = data['items'][0] if data.get('items') and data['items'] else None
        if not videoData:
            return None
        videoInfo = videoData['snippet']
        contentDetails = videoData['contentDetails']
        statistics = videoData['statistics']
        channelId = videoInfo['channelId']
        channelThumbnail = get_channel_thumbnail(channelId, apikey)
        finalVideoUrl = ''
        if not use_video_proxy:
            finalVideoUrlWithProxy = get_real_direct_video_url(video_id)
        else:
            if config['video_source'] == 'direct':
                finalVideoUrl = f"{config['mainurl']}direct_url?video_id={video_id}"
                finalVideoUrlWithProxy = finalVideoUrl
            else:
                finalVideoUrl = get_direct_video_url(video_id) if config['video_source'] == 'direct' else ''
                finalVideoUrlWithProxy = finalVideoUrl
                if config['use_video_proxy'] and finalVideoUrl:
                    finalVideoUrlWithProxy = f"{config['mainurl']}video.proxy?url={quote(finalVideoUrl)}"
        publishedAt = datetime.strptime(videoInfo['publishedAt'], '%Y-%m-%dT%H:%M:%SZ')
        publishedAtFormatted = publishedAt.strftime('%d.%m.%Y, %H:%M:%S')
        return {
            'title': videoInfo['title'],
            'author': videoInfo['channelTitle'],
            'description': videoInfo['description'],
            'video_id': video_id,
            'embed_url': f"https://www.youtube.com/embed/{video_id}",
            'duration': contentDetails['duration'],
            'published_at': publishedAtFormatted,
            'likes': statistics.get('likeCount'),
            'views': statistics.get('viewCount'),
            'comment_count': statistics.get('commentCount'),
            'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
            'thumbnail': get_proxy_url(f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg", config['use_thumbnail_proxy']),
            'video_url': finalVideoUrlWithProxy
        }
    except Exception as e:
        print('Error in get_video_info_dict:', e)
        return None

def get_video_info_ytdlp(video_id):
    try:
        ydl_opts = {
            'quiet': True,
            'format': 'best',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            return {
                'title': info.get('title', ''),
                'author': info.get('uploader', ''),
                'description': info.get('description', ''),
                'video_id': video_id,
                'duration': info.get('duration', 0),
                'published_at': info.get('upload_date', ''),
                'views': info.get('view_count', 0),
                'thumbnail': info.get('thumbnail', ''),
                'video_url': info.get('url', ''),
            }
    except Exception as e:
        print('Error in get_video_info_ytdlp:', e)
        return None

# Routes
@app.route('/')
def home():
    port = 2823
    return f'''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>YouTube Legacy API</title>
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: 'Segoe UI', sans-serif;
                    background: #1a1a1a;
                    color: #fff;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                }}
                .container {{
                    text-align: center;
                    padding: 20px;
                    max-width: 800px;
                }}
                .icon {{
                    width: 150px;
                    height: 150px;
                    margin-bottom: 20px;
                }}
                h1 {{
                    font-size: 2.5em;
                    margin: 0;
                    color: #fff;
                }}
                .subtitle {{
                    font-size: 1.2em;
                    color: #888;
                    margin: 10px 0 30px;
                }}
                .tile {{
                    background: #2d2d2d;
                    border-radius: 10px;
                    padding: 20px;
                    margin: 10px 0;
                    text-align: left;
                }}
                .tile h2 {{
                    margin: 0 0 10px;
                    color: #fff;
                }}
                .tile p {{
                    margin: 0;
                    color: #888;
                }}
                .endpoints {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-top: 30px;
                }}
                .endpoint {{
                    background: #333;
                    padding: 15px;
                    border-radius: 8px;
                    transition: transform 0.2s;
                }}
                .endpoint:hover {{
                    transform: translateY(-5px);
                }}
                .endpoint h3 {{
                    margin: 0 0 10px;
                    color: #fff;
                }}
                .endpoint p {{
                    margin: 0;
                    color: #888;
                    font-size: 0.9em;
                }}
                .footer {{
                    margin-top: 40px;
                    color: #666;
                    font-size: 0.9em;
                }}
                .legacy-badge {{
                    background: #0078D7;
                    color: white;
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-size: 0.8em;
                    margin-left: 10px;
                    vertical-align: middle;
                }}
            </style>
        </head> 
        <body>
            <div class="container">
                <img src="https://github.com/zemonkamin/ytapilegacy/raw/main/icon.png" alt="YouTube Legacy API" class="icon">
                <h1>YouTube Legacy API <span class="legacy-badge">LegacyProjects</span></h1>
                <div class="subtitle">A Windows Phone inspired YouTube API service</div>
                <div class="tile">
                    <h2>About</h2>
                    <p>This is a legacy YouTube API service that provides endpoints for fetching video information, channel data, and more. Built with Python and Flask.</p>
                    <p style="margin-top: 10px;">Part of the LegacyProjects initiative, bringing back the classic YouTube experience.</p>
                </div>
                <div class="endpoints">
                    <div class="endpoint">
                        <h3>Authentication</h3>
                        <p>/auth - OAuth authentication with QR code</p>
                        <p>/auth/status - Check auth status</p>
                        <p>/auth/simple - Simple auth (POST)</p>
                    </div>
                    <div class="endpoint">
                        <h3>Account Info</h3>
                        <p>/account_info?token=REFRESH_TOKEN - Get Google account information</p>
                    </div>
                    <div class="endpoint">
                        <h3>Recommendations</h3>
                        <p>/get_recommendations.php?token=TOKEN&count=N - InnerTube API (формат как /get_top_videos.php)</p>
                        <p style="font-size: 0.8em; color: #aaa;">Example: /get_recommendations_innertube?token=YOUR_TOKEN&count=10</p>
                    </div>
                    <div class="endpoint">
                        <h3>Video Information</h3>
                        <p>/get-ytvideo-info.php</p>
                    </div>
                    <div class="endpoint">
                        <h3>Channel Videos</h3>
                        <p>/get_author_videos.php</p>
                    </div>
                    <div class="endpoint">
                        <h3>Search Videos</h3>
                        <p>/get_search_videos.php</p>
                    </div>
                    <div class="endpoint">
                        <h3>Top Videos</h3>
                        <p>/get_top_videos.php</p>
                    </div>
                    <div class="endpoint">
                        <h3>Categories</h3>
                        <p>/get-categories.php</p>
                    </div>
                    <div class="endpoint">
                        <h3>Related Videos</h3>
                        <p>/get_related_videos.php</p>
                    </div>
                </div>
                <div class="footer">
                    Running on port {port} | LegacyProjects YouTube API Service
                </div>
            </div>
        </body>
        </html>
    '''

@app.route('/account_info')
def account_info():
    """Get Google account information using refresh token"""
    try:
        refresh_token = request.args.get('token')
        if not refresh_token:
            return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

        # Get access token from refresh token
        try:
            token_data = refresh_access_token(refresh_token)
            access_token = token_data['access_token']
        except Exception as e:
            return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

        # Get account information
        account_data = get_account_info(access_token)
        if not account_data:
            return jsonify({'error': 'Failed to get account information'}), 500

        # Format the response
        profile = account_data['profile']
        youtube = account_data['youtube']
        
        result = {
            'google_account': {
                'id': profile.get('id'),
                'name': profile.get('name'),
                'given_name': profile.get('given_name'),
                'family_name': profile.get('family_name'),
                'email': profile.get('email'),
                'verified_email': profile.get('verified_email'),
                'picture': profile.get('picture'),
                'locale': profile.get('locale')
            }
        }

        # Add YouTube channel info if available
        if youtube and youtube.get('items') and len(youtube['items']) > 0:
            channel = youtube['items'][0]
            snippet = channel.get('snippet', {})
            statistics = channel.get('statistics', {})
            
            result['youtube_channel'] = {
                'id': channel.get('id'),
                'title': snippet.get('title'),
                'description': snippet.get('description'),
                'custom_url': snippet.get('customUrl'),
                'published_at': snippet.get('publishedAt'),
                'thumbnails': snippet.get('thumbnails'),
                'country': snippet.get('country'),
                'subscriber_count': statistics.get('subscriberCount'),
                'video_count': statistics.get('videoCount'),
                'view_count': statistics.get('viewCount')
            }

        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        try:
            error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
        except:
            error_msg = "Request failed"
        return jsonify({
            'error': 'Failed to get account information',
            'details': error_msg
        }), 500

@app.route('/auth')
def auth():
    """
    Serves a page with a QR code or a token inside a <ytreq> element.
    """
    try:
        if 'session_id' not in session:
            session['session_id'] = str(time.time()) + secrets.token_hex(8)
        
        current_session_id = session['session_id']
        
        # Check the global token_store for the token.
        if current_session_id in token_store:
            token = token_store.get(current_session_id)
            if token and not token.startswith("Error"):
                session['refresh_token'] = token
                del token_store[current_session_id]

        # If a token is in the session, display the token.
        if 'refresh_token' in session and session['refresh_token']:
            token_display = f"Token: {html.escape(session['refresh_token'])}"
            return Response(f'''<ytreq>{token_display}</ytreq>''', mimetype='text/html')

        # If no token, generate and display the QR code.
        if 'auth_url' in session and time.time() - session.get('auth_url_timestamp', 0) < 300:
            auth_url = session['auth_url']
        else:
            auth_url = get_auth_url(current_session_id)
            session['auth_url'] = auth_url
            session['auth_url_timestamp'] = time.time()
        
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
        
        qr_display = qr_base64
        return Response(f'''<ytreq>{qr_display}</ytreq>''', mimetype='text/html')

    except Exception as e:
        return Response(f'''<ytreq>Ошибка: {html.escape(str(e))}</ytreq>''', 500)

@app.route('/auth/events')
def auth_events():
    """SSE endpoint to push token updates to the client"""
    session_id = request.args.get('session_id')
    if not session_id:
        return Response(
            'data: {"error": "Missing session_id"}\n\n',
            mimetype='text/event-stream'
        )

    def generate():
        start_time = time.time()
        timeout = 300  # 5 minutes timeout
        while time.time() - start_time < timeout:
            with token_store_lock:
                if session_id in token_store:
                    token = token_store[session_id]
                    yield f'data: {json.dumps({"token": token})}\n\n'
                    del token_store[session_id]  # Clean up
                    return
            time.sleep(1)
        yield f'data: {json.dumps({"error": "Authentication timed out"})}\n\n'

    return Response(generate(), mimetype='text/event-stream')

@app.route('/oauth/callback')
def oauth_callback():
    try:
        code = request.args.get('code')
        session_id = request.args.get('state')
        if not code or not session_id:
            return '''
                <html>
                    <body>
                        <h2>Authentication failed</h2>
                        <p>No authorization code or state received.</p>
                    </body>
                </html>
            ''', 400

        try:
            token_data = get_access_token(code)
            refresh_token = token_data.get('refresh_token')
            
            if not refresh_token:
                return '''
                    <html>
                        <body>
                            <h2>Authentication failed</h2>
                            <p>No refresh token received. Please try again.</p>
                        </body>
                    </html>
                ''', 400
            
            session['refresh_token'] = refresh_token
            
            with token_store_lock:
                token_store[session_id] = refresh_token
            
            session.pop('auth_url', None)
            session.pop('auth_url_timestamp', None)
            
            return '''
                <html>
                    <body>
                        <h2>Authentication successful</h2>
                        <p>You can close this window now and refresh the previous page.</p>
                        <script>
                            window.close();
                        </script>
                    </body>
                </html>
            '''
        except Exception as e:
            with token_store_lock:
                token_store[session_id] = f"Error getting token: {str(e)}"
            return f'''
                <html>
                    <body>
                        <h2>Error</h2>
                        <p>Error getting token: {html.escape(str(e))}</p>
                    </body>
                </html>
            ''', 400
    except Exception as e:
        return f'''
            <html>
                <body>
                    <h2>Internal server error</h2>
                    <p>{html.escape(str(e))}</p>
                </body>
                </html>
        ''', 500

@app.route('/get_recommendations.php', methods=['GET'])
def get_recommendations_innertube():
    """Get recommendations using InnerTube API like in recs.py"""
    try:
        count = config.get('default_count', 50)
        
        refresh_token = request.args.get('token')
        if not refresh_token:
            return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

        # Get access token from refresh token
        try:
            token_data = refresh_access_token(refresh_token)
            access_token = token_data['access_token']
        except Exception as e:
            return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

        endpoint = "https://www.youtube.com/youtubei/v1/browse"
        
        payload = {
            "context": {
                "client": {
                    "hl": "en",
                    "gl": "US",
                    "deviceMake": "Samsung",
                    'deviceModel': "SmartTV",
                    "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)",
                    "clientName": "TVHTML5",
                    "clientVersion": "7.20250209.19.00",
                    "osName": "Tizen",
                    "osVersion": "5.0",
                    "platform": "TV",
                    "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                    "screenPixelDensity": 1
                }
            },
            "browseId": "FEwhat_to_watch"
        }
        
        params = {
            "key": config.get('api_key'),
            'prettyPrint': 'false'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': 'https://www.youtube.com/',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive'
        }
        
        headers['Authorization'] = f'Bearer {access_token}'
        
        try:
            response = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            json_data = response.json()
        except Exception as e:
            error_msg = str(e)
            error_msg = error_msg.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
            try:
                error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
            except:
                error_msg = "Request failed"
            return jsonify({'error': 'InnerTube request failed', 'details': error_msg}), 500

        videos = extract_innertube_data(json_data, count)
        
        formatted_videos = []
        for video in videos:
            if video and video.get('video_id') and video.get('video_id') != 'unknown':
                formatted_video = {
                    'title': video.get('title', 'No Title'),
                    'author': video.get('author', 'Unknown'),
                    'video_id': video.get('video_id'),
                    'thumbnail': f"{config['mainurl']}thumbnail/{video.get('video_id')}",
                    'channel_thumbnail': ''
                }
                formatted_videos.append(formatted_video)
        
        return jsonify(formatted_videos)

    except Exception as e:
        error_msg = str(e)
        error_msg = error_msg.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        try:
            error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
        except:
            error_msg = "Request failed"
        return jsonify({
            'error': 'API request failed',
            'details': error_msg
        }), 500

def extract_innertube_data(json_data, max_videos):
    videos = []
    
    if not json_data:
        return videos
    
    try:
        contents = json_data.get('contents', {})
        
        if 'tvBrowseRenderer' in contents:
            tv_content = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
            sections = tv_content['sectionListRenderer']['contents']
            
            for section in sections:
                if len(videos) >= max_videos:
                    break
                if 'shelfRenderer' in section:
                    shelf = section['shelfRenderer']
                    content = shelf.get('content', {})
                    
                    if 'horizontalListRenderer' in content:
                        items = content['horizontalListRenderer'].get('items', [])
                        for item in items:
                            if len(videos) >= max_videos:
                                break
                            if 'tileRenderer' in item:
                                video_data = parse_tile_renderer(item['tileRenderer'])
                                if video_data:
                                    videos.append(video_data)
        
        elif 'twoColumnBrowseResultsRenderer' in contents:
            tabs = contents['twoColumnBrowseResultsRenderer']['tabs']
            for tab in tabs:
                if len(videos) >= max_videos:
                    break
                if 'tabRenderer' in tab:
                    tab_content = tab['tabRenderer'].get('content', {})
                    if 'sectionListRenderer' in tab_content:
                        sections = tab_content['sectionListRenderer']['contents']
                        for section in sections:
                            if len(videos) >= max_videos:
                                break
                            if 'itemSectionRenderer' in section:
                                items = section['itemSectionRenderer']['contents']
                                for item in items:
                                    if len(videos) >= max_videos:
                                        break
                                    if 'shelfRenderer' in item:
                                        shelf = item['shelfRenderer']
                                        shelf_content = shelf.get('content', {})
                                        if 'expandedShelfContentsRenderer' in shelf_content:
                                            video_items = shelf_content['expandedShelfContentsRenderer']['items']
                                            for video_item in video_items:
                                                if len(videos) >= max_videos:
                                                    break
                                                if 'videoRenderer' in video_item:
                                                    video_data = parse_video_renderer(video_item['videoRenderer'])
                                                    if video_data:
                                                        videos.append(video_data)
        
        return videos[:max_videos]
        
    except Exception as e:
        try:
            error_msg = str(e).replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
            error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
        except:
            error_msg = "Data extraction failed"
        return videos
        
@app.route('/get_history.php', methods=['GET'])
def get_history():
    """Get watch history using InnerTube API"""
    try:
        count = config.get('default_count', 50)
        
        refresh_token = request.args.get('token')
        if not refresh_token:
            return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

        # Get access token from refresh token
        try:
            token_data = refresh_access_token(refresh_token)
            access_token = token_data['access_token']
        except Exception as e:
            return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

        videos = []
        continuation_token = None
        
        # Получаем видео пока не наберем нужное количество или не закончатся страницы
        while len(videos) < count:
            json_data = fetch_history_page(access_token, continuation_token)  # Убрали await
            if not json_data:
                break
            
            # Извлекаем видео и токен продолжения
            page_videos, continuation_token = extract_history_data_with_continuation(json_data, count - len(videos))
            videos.extend(page_videos)
            
            if not continuation_token or len(page_videos) == 0:
                break
        
        formatted_videos = []
        for video in videos:
            if video and video.get('video_id') and video.get('video_id') != 'unknown':
                formatted_video = {
                    'title': video.get('title', 'No Title'),
                    'author': video.get('author', 'Unknown'),
                    'video_id': video.get('video_id'),
                    'thumbnail': f"{config['mainurl']}thumbnail/{video.get('video_id')}",
                    'channel_thumbnail': '',
                    'views': video.get('views', 0),
                    'duration': video.get('duration', '0:00'),
                    'watched_at': video.get('watched_at', '')
                }
                formatted_videos.append(formatted_video)
        
        return jsonify(formatted_videos)

    except Exception as e:
        error_msg = str(e)
        error_msg = error_msg.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        try:
            error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
        except:
            error_msg = "Request failed"
        return jsonify({
            'error': 'API request failed',
            'details': error_msg
        }), 500

def fetch_history_page(access_token, continuation_token=None):
    """Fetch a page of history data"""
    endpoint = "https://www.youtube.com/youtubei/v1/browse"
    
    payload = {
        "context": {
            "client": {
                "hl": "en",
                "gl": "US",
                "deviceMake": "Samsung",
                "deviceModel": "SmartTV",
                "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)",
                "clientName": "TVHTML5",
                "clientVersion": "7.20250209.19.00",
                "osName": "Tizen",
                "osVersion": "5.0",
                "platform": "TV",
                "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                "screenPixelDensity": 1
            }
        },
        "browseId": "FEhistory"
    }
    
    # Добавляем токен продолжения если есть
    if continuation_token:
        payload["continuation"] = continuation_token
    
    params = {
        "key": config.get('api_key'),
        "prettyPrint": "false"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.5',
        'Content-Type': 'application/json',
        'Origin': 'https://www.youtube.com',
        'Referer': 'https://www.youtube.com/',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Authorization': f'Bearer {access_token}'
    }
    
    try:
        response = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching history page: {e}")
        return None

# Остальные функции остаются без изменений
def extract_history_data_with_continuation(json_data, max_videos):
    """Extract videos and continuation token from history JSON response"""
    videos = []
    continuation_token = None
    
    if not json_data:
        return videos, continuation_token
    
    try:
        # Пытаемся найти токен продолжения
        continuation_token = find_continuation_token(json_data)
        
        # Извлекаем видео
        contents = json_data.get('contents', {})
        
        if 'tvBrowseRenderer' in contents:
            tv_content = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
            
            # Проверяем gridRenderer
            if 'gridRenderer' in tv_content:
                items = tv_content['gridRenderer'].get('items', [])
                for item in items:
                    if len(videos) >= max_videos:
                        break
                    if 'tileRenderer' in item:
                        video_data = parse_history_tile_renderer(item['tileRenderer'])
                        if video_data:
                            videos.append(video_data)
            
            # Проверяем sectionListRenderer
            elif 'sectionListRenderer' in tv_content:
                sections = tv_content['sectionListRenderer'].get('contents', [])
                for section in sections:
                    if len(videos) >= max_videos:
                        break
                    if 'itemSectionRenderer' in section:
                        items = section['itemSectionRenderer'].get('contents', [])
                        for item in items:
                            if len(videos) >= max_videos:
                                break
                            if 'tileRenderer' in item:
                                video_data = parse_history_tile_renderer(item['tileRenderer'])
                                if video_data:
                                    videos.append(video_data)
        
        # Альтернативный путь: проверяем onResponseReceivedActions
        if not videos and 'onResponseReceivedActions' in json_data:
            for action in json_data['onResponseReceivedActions']:
                if 'appendContinuationItemsAction' in action:
                    items = action['appendContinuationItemsAction'].get('items', [])
                    for item in items:
                        if len(videos) >= max_videos:
                            break
                        if 'tileRenderer' in item:
                            video_data = parse_history_tile_renderer(item['tileRenderer'])
                            if video_data:
                                videos.append(video_data)
                        elif 'continuationItemRenderer' in item and not continuation_token:
                            # Получаем токен продолжения
                            continuation_token = item['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        
        return videos, continuation_token
        
    except Exception as e:
        print(f"Error extracting history data: {e}")
        return videos, continuation_token

def find_continuation_token(json_data):
    """Find continuation token in JSON response"""
    try:
        # Ищем в различных местах где может быть токен продолжения
        if 'continuationContents' in json_data:
            continuation = json_data['continuationContents'].get('gridContinuation', {})
            return continuation.get('continuations', [{}])[0].get('nextContinuationData', {}).get('continuation')
        
        if 'onResponseReceivedActions' in json_data:
            for action in json_data['onResponseReceivedActions']:
                if 'appendContinuationItemsAction' in action:
                    items = action['appendContinuationItemsAction'].get('items', [])
                    for item in items:
                        if 'continuationItemRenderer' in item:
                            return item['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        
        # Проверяем в содержимом
        contents = json_data.get('contents', {})
        if 'tvBrowseRenderer' in contents:
            content = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
            if 'continuationItemRenderer' in content:
                return content['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        
        return None
        
    except Exception as e:
        print(f"Error finding continuation token: {e}")
        return None

def parse_history_tile_renderer(tile):
    """Parse tile renderer for history items"""
    try:
        # Extract video ID
        video_id = tile.get('onSelectCommand', {}).get('watchEndpoint', {}).get('videoId', 'unknown')
        if video_id == 'unknown':
            return None
        
        # Extract title
        title = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('title', {}).get('simpleText', 'No Title')
        
        # Extract author/channel name
        author = "Unknown"
        try:
            lines = tile['metadata']['tileMetadataRenderer'].get('lines', [])
            if lines and len(lines) > 0:
                line_renderer = lines[0].get('lineRenderer', {})
                items = line_renderer.get('items', [])
                if items:
                    line_item = items[0].get('lineItemRenderer', {})
                    text = line_item.get('text', {})
                    if 'runs' in text and text['runs']:
                        raw_author = text['runs'][0].get('text', 'Unknown')
                        author = raw_author.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
                        try:
                            author = author.encode('ascii', errors='ignore').decode('ascii')
                        except:
                            author = "Unknown"
        except:
            pass
        
        # Extract view count
        views = 0
        try:
            if tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('lines', []):
                lines = tile['metadata']['tileMetadataRenderer']['lines']
                if len(lines) > 1:
                    line_renderer = lines[1].get('lineRenderer', {})
                    items = line_renderer.get('items', [])
                    if items:
                        line_item = items[0].get('lineItemRenderer', {})
                        text = line_item.get('text', {})
                        if 'accessibility' in text:
                            accessibility_data = text['accessibility'].get('accessibilityData', {})
                            label = accessibility_data.get('label', '')
                            if label:
                                # Extract numeric part from view count text
                                numbers = re.findall(r'\d+', label)
                                if numbers:
                                    views = int(numbers[0])
        except:
            pass
        
        # Extract duration
        duration = "0:00"
        try:
            if tile.get('header', {}).get('tileHeaderRenderer', {}).get('thumbnailOverlays', []):
                overlays = tile['header']['tileHeaderRenderer']['thumbnailOverlays']
                if overlays:
                    time_status = overlays[0].get('thumbnailOverlayTimeStatusRenderer', {})
                    if time_status:
                        duration = time_status.get('text', {}).get('simpleText', '0:00')
        except:
            pass
        
        # Extract watched time (relative)
        watched_at = ""
        try:
            lines = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('lines', [])
            if lines and len(lines) > 1:
                line_renderer = lines[1].get('lineRenderer', {})
                items = line_renderer.get('items', [])
                if items and len(items) > 2:
                    line_item = items[2].get('lineItemRenderer', {})
                    text = line_item.get('text', {})
                    if 'simpleText' in text:
                        watched_at = text['simpleText']
        except:
            pass
        
        return {
            'video_id': video_id,
            'title': title,
            'author': author,
            'views': views,
            'duration': duration,
            'watched_at': watched_at
        }
        
    except Exception as e:
        print(f"Error parsing tile: {e}")
        return None

def parse_tile_renderer(tile):
    try:
        video_id = tile.get('onSelectCommand', {}).get('watchEndpoint', {}).get('videoId', 'unknown')
        if video_id == 'unknown':
            return None
        
        title = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('title', {}).get('simpleText', 'No Title')
        
        author = "Unknown"
        try:
            lines = tile['metadata']['tileMetadataRenderer'].get('lines', [])
            if lines and len(lines) > 0:
                line_renderer = lines[0].get('lineRenderer', {})
                items = line_renderer.get('items', [])
                if items:
                    line_item = items[0].get('lineItemRenderer', {})
                    text = line_item.get('text', {})
                    if 'runs' in text and text['runs']:
                        raw_author = text['runs'][0].get('text', 'Unknown')
                        author = raw_author.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
                        try:
                            author = author.encode('ascii', errors='ignore').decode('ascii')
                        except:
                            author = "Unknown"
        except Exception as e:
            pass
        
        return {
            'video_id': video_id,
            'title': title,
            'author': author
        }
        
    except Exception as e:
        return None

def parse_video_renderer(video):
    try:
        raw_title = video.get('title', {}).get('runs', [{}])[0].get('text', 'No Title')
        raw_author = video.get('ownerText', {}).get('runs', [{}])[0].get('text', 'Unknown')
        
        title = raw_title.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        author = raw_author.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        
        try:
            title = title.encode('ascii', errors='ignore').decode('ascii')
            author = author.encode('ascii', errors='ignore').decode('ascii')
        except:
            pass
        
        return {
            'video_id': video.get('videoId', 'unknown'),
            'title': title,
            'author': author
        }
    except Exception as e:
        return None

@app.route('/get_author_videos_by_id.php', methods=['GET'])
def get_author_videos_by_id():
    try:
        channel_id = request.args.get('channel_id')
        count = int(request.args.get('count', str(config.get('default_count', 50))))
        apikey = request.args.get('apikey', config['api_key'])

        if not channel_id:
            return jsonify({'error': 'Channel ID parameter is required'})

        channel_resp = requests.get(f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,brandingSettings&id={channel_id}&key={apikey}", timeout=config['request_timeout'])
        channel_resp.raise_for_status()
        channel_data = channel_resp.json()
        channel_info = channel_data['items'][0] if channel_data['items'] else None

        if not channel_info:
            return jsonify({'error': 'Channel not found'})

        videos = []
        nextPageToken = ''
        totalVideos = 0

        while totalVideos < count:
            videos_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={channel_id}&maxResults=50&type=video&order=date&key={apikey}"
            if nextPageToken:
                videos_url += f"&pageToken={nextPageToken}"
            videos_resp = requests.get(videos_url, timeout=config['request_timeout'])
            videos_resp.raise_for_status()
            videos_data = videos_resp.json()

            if videos_data.get('items'):
                for video in videos_data['items']:
                    if totalVideos >= count:
                        break
                    videoInfo = video['snippet']
                    videoId = video['id']['videoId']
                    channelThumbnail = get_channel_thumbnail(channel_id, apikey)
                    videos.append({
                        'title': videoInfo['title'],
                        'author': channel_info['snippet']['title'],
                        'video_id': videoId,
                        'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                        'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
                    })
                    totalVideos += 1
            nextPageToken = videos_data.get('nextPageToken', '')
            if not nextPageToken:
                break

        result = {
            'channel_info': {
                'title': channel_info['snippet']['title'],
                'description': channel_info['snippet']['description'],
                'thumbnail': get_proxy_url(channel_info['snippet']['thumbnails']['high']['url'], config['use_channel_thumbnail_proxy']),
                'banner': get_proxy_url(channel_info.get('brandingSettings', {}).get('image', {}).get('bannerExternalUrl', ''), config['use_thumbnail_proxy']),
                'subscriber_count': channel_info['statistics']['subscriberCount'],
                'video_count': channel_info['statistics']['videoCount']
            },
            'videos': videos
        }
        return jsonify(result)
    except Exception as e:
        print('Error in get_author_videos_by_id:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get_author_videos.php', methods=['GET'])
def get_author_videos():
    try:
        author = request.args.get('author')
        count = request.args.get('count', '50')
        apikey = request.args.get('apikey', config['api_key'])

        if not author:
            return jsonify({'error': 'Author parameter is required'})

        search_resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(author)}&type=channel&maxResults=1&key={apikey}")
        search_resp.raise_for_status()
        data = search_resp.json()
        channelId = data['items'][0]['id']['channelId'] if data.get('items') and data['items'] else None

        if not channelId:
            return jsonify({'error': 'Channel not found'})

        return redirect(f"/get_author_videos_by_id.php?channel_id={channelId}&count={count}&apikey={apikey}")
    except Exception as e:
        print('Error in get_author_videos:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get_channel_thumbnail.php', methods=['GET'])
def get_channel_thumbnail_api():
    try:
        video_id = request.args.get('video_id')
        apikey = request.args.get('apikey', config['api_key'])

        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})
        if not apikey:
            return jsonify({'channel_thumbnail': ''})

        video_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={apikey}&part=snippet")
        video_resp.raise_for_status()
        data = video_resp.json()
        channelId = data['items'][0]['snippet']['channelId'] if data.get('items') and data['items'] else None

        if not channelId:
            return jsonify({'error': 'Видео не найдено.'})

        channelThumbnail = get_channel_thumbnail(channelId, apikey)
        return jsonify({'channel_thumbnail': channelThumbnail})
    except Exception as e:
        print('Error in get_channel_thumbnail:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get_related_videos.php', methods=['GET'])
def get_related_videos():
    try:
        video_id = request.args.get('video_id')
        count = int(request.args.get('count', str(config.get('default_count', 50))))
        apikey = request.args.get('apikey', config['api_key'])
        refresh_token = request.args.get('token')  # Новый параметр для токена

        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})

        # Получаем информацию о текущем видео
        video_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={apikey}")
        video_resp.raise_for_status()
        video_data = video_resp.json()
        videoInfo = video_data['items'][0]['snippet'] if video_data.get('items') and video_data['items'] else None

        if not videoInfo:
            return jsonify({'error': 'Видео не найдено.'})

        relatedVideos = []

        # 1. Получаем связанные видео через поиск (оригинальный метод)
        # Используем обычный поиск вместо relatedToVideoId который требует авторизации
        search_query = videoInfo['title'].split(' ')[0]  # Берем первое слово из названия
        search_resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(search_query)}&type=video&maxResults={count}&key={apikey}")
        
        if search_resp.status_code != 200:
            print(f"Search API error: {search_resp.status_code}, using fallback")
            # Fallback: просто возвращаем пустой список для поисковых результатов
            search_data = {'items': []}
        else:
            search_data = search_resp.json()

        for video in search_data.get('items', []):
            if video['id']['videoId'] == video_id:
                continue
            vinfo = video['snippet']
            vid = video['id']['videoId']
            channelThumbnail = get_channel_thumbnail(vinfo['channelId'], apikey)
            
            # Получаем статистику видео
            try:
                stats_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={apikey}", timeout=5)
                if stats_resp.status_code == 200:
                    stats_data = stats_resp.json()
                    viewCount = stats_data['items'][0]['statistics']['viewCount'] if stats_data.get('items') and stats_data['items'] else '0'
                else:
                    viewCount = '0'
            except:
                viewCount = '0'
            
            relatedVideos.append({
                'title': vinfo['title'],
                'author': vinfo['channelTitle'],
                'video_id': vid,
                'views': viewCount,
                'thumbnail': f"{config['mainurl']}thumbnail/{vid}",
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
                'url': get_video_proxy_url(f"{config['mainurl']}get-ytvideo-info.php?video_id={vid}&quality={config['default_quality']}", config['use_video_proxy']),
                'source': 'search'
            })

        # 2. Если предоставлен токен, добавляем рекомендации из InnerTube
        if refresh_token and len(relatedVideos) < count:
            try:
                # Получаем access token из refresh token
                token_data = refresh_access_token(refresh_token)
                if 'access_token' not in token_data:
                    print('No access token in response from refresh:', token_data)
                else:
                    access_token = token_data['access_token']
                    print(f"Successfully got access token: {access_token[:20]}...")

                    # Получаем рекомендации через InnerTube
                    recommendations = get_innertube_recommendations(access_token, count - len(relatedVideos))
                    print(f"Got {len(recommendations)} recommendations from InnerTube")
                    
                    for rec_video in recommendations:
                        # Проверяем, нет ли уже этого видео в списке
                        if not any(v['video_id'] == rec_video['video_id'] for v in relatedVideos):
                            vid = rec_video['video_id']
                            
                            # Получаем дополнительную информацию о видео
                            try:
                                stats_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={apikey}", timeout=5)
                                if stats_resp.status_code == 200:
                                    stats_data = stats_resp.json()
                                    viewCount = stats_data['items'][0]['statistics']['viewCount'] if stats_data.get('items') and stats_data['items'] else '0'
                                else:
                                    viewCount = '0'
                            except:
                                viewCount = '0'
                            
                            # Получаем информацию о канале для миниатюры
                            try:
                                channel_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={vid}&key={apikey}", timeout=5)
                                if channel_resp.status_code == 200:
                                    channel_data = channel_resp.json()
                                    channel_id = channel_data['items'][0]['snippet']['channelId'] if channel_data.get('items') else None
                                    channel_thumb = get_channel_thumbnail(channel_id, apikey) if channel_id else ''
                                else:
                                    channel_thumb = ''
                            except:
                                channel_thumb = ''
                            
                            relatedVideos.append({
                                'title': rec_video.get('title', 'No Title'),
                                'author': rec_video.get('author', 'Unknown'),
                                'video_id': vid,
                                'views': viewCount,
                                'thumbnail': f"{config['mainurl']}thumbnail/{vid}",
                                'channel_thumbnail': get_proxy_url(channel_thumb, config['use_channel_thumbnail_proxy']),
                                'url': get_video_proxy_url(f"{config['mainurl']}get-ytvideo-info.php?video_id={vid}&quality={config['default_quality']}", config['use_video_proxy']),
                                'source': 'recommendations'
                            })

            except Exception as e:
                print('Error getting recommendations from InnerTube:', str(e))
                import traceback
                traceback.print_exc()

        # Ограничиваем количество видео до запрошенного
        relatedVideos = relatedVideos[:count]
        print(f"Returning {len(relatedVideos)} related videos")

        return jsonify(relatedVideos)

    except Exception as e:
        print('Error in get_related_videos:', str(e))
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'})

def get_innertube_recommendations(access_token, max_count):
    """Get recommendations from InnerTube API"""
    try:
        endpoint = "https://www.youtube.com/youtubei/v1/browse"
        
        payload = {
            "context": {
                "client": {
                    "hl": "en",
                    "gl": "US",
                    "deviceMake": "Samsung",
                    "deviceModel": "SmartTV",
                    "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)",
                    "clientName": "TVHTML5",
                    "clientVersion": "7.20250209.19.00",
                    "osName": "Tizen",
                    "osVersion": "5.0",
                    "platform": "TV",
                    "clientFormFactor": "UNKNOWN_FORM_FACTOR",
                    'screenPixelDensity': 1
                }
            },
            "browseId": "FEwhat_to_watch"
        }
        
        params = {
            "key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
            "prettyPrint": "false"
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/5.0 NativeTVAds Safari/538.1,gzip(gfe)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Content-Type': 'application/json',
            'Origin': 'https://www.youtube.com',
            'Referer': 'https://www.youtube.com/',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Authorization': f'Bearer {access_token}'
        }
        
        response = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        json_data = response.json()
        
        return extract_innertube_data(json_data, max_count)
        
    except Exception as e:
        print(f"Error getting InnerTube recommendations: {str(e)}")
        return []

def extract_innertube_data(json_data, max_videos):
    """Extract video data from InnerTube response"""
    videos = []
    
    if not json_data:
        return videos
    
    try:
        contents = json_data.get('contents', {})
        
        # Обработка различных форматов ответа InnerTube
        if 'tvBrowseRenderer' in contents:
            tv_content = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
            
            if 'sectionListRenderer' in tv_content:
                sections = tv_content['sectionListRenderer']['contents']
                
                for section in sections:
                    if len(videos) >= max_videos:
                        break
                    if 'shelfRenderer' in section:
                        shelf = section['shelfRenderer']
                        content = shelf.get('content', {})
                        
                        if 'horizontalListRenderer' in content:
                            items = content['horizontalListRenderer'].get('items', [])
                            for item in items:
                                if len(videos) >= max_videos:
                                    break
                                if 'tileRenderer' in item:
                                    video_data = parse_tile_renderer(item['tileRenderer'])
                                    if video_data:
                                        videos.append(video_data)
        
        elif 'twoColumnBrowseResultsRenderer' in contents:
            tabs = contents['twoColumnBrowseResultsRenderer']['tabs']
            for tab in tabs:
                if len(videos) >= max_videos:
                    break
                if 'tabRenderer' in tab:
                    tab_content = tab['tabRenderer'].get('content', {})
                    if 'sectionListRenderer' in tab_content:
                        sections = tab_content['sectionListRenderer']['contents']
                        for section in sections:
                            if len(videos) >= max_videos:
                                break
                            if 'itemSectionRenderer' in section:
                                items = section['itemSectionRenderer']['contents']
                                for item in items:
                                    if len(videos) >= max_videos:
                                        break
                                    if 'shelfRenderer' in item:
                                        shelf = item['shelfRenderer']
                                        shelf_content = shelf.get('content', {})
                                        if 'expandedShelfContentsRenderer' in shelf_content:
                                            video_items = shelf_content['expandedShelfContentsRenderer']['items']
                                            for video_item in video_items:
                                                if len(videos) >= max_videos:
                                                    break
                                                if 'videoRenderer' in video_item:
                                                    video_data = parse_video_renderer(video_item['videoRenderer'])
                                                    if video_data:
                                                        videos.append(video_data)
        
        return videos[:max_videos]
        
    except Exception as e:
        print(f"Error extracting InnerTube data: {str(e)}")
        return videos

def parse_tile_renderer(tile):
    """Parse tile renderer for video data"""
    try:
        video_id = tile.get('onSelectCommand', {}).get('watchEndpoint', {}).get('videoId', 'unknown')
        if video_id == 'unknown':
            return None
        
        title = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('title', {}).get('simpleText', 'No Title')
        
        author = "Unknown"
        try:
            lines = tile['metadata']['tileMetadataRenderer'].get('lines', [])
            if lines and len(lines) > 0:
                line_renderer = lines[0].get('lineRenderer', {})
                items = line_renderer.get('items', [])
                if items:
                    line_item = items[0].get('lineItemRenderer', {})
                    text = line_item.get('text', {})
                    if 'runs' in text and text['runs']:
                        raw_author = text['runs'][0].get('text', 'Unknown')
                        author = raw_author.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        except:
            pass
        
        return {
            'video_id': video_id,
            'title': title,
            'author': author
        }
        
    except Exception as e:
        print(f"Error parsing tile: {str(e)}")
        return None

def parse_video_renderer(video):
    """Parse video renderer for video data"""
    try:
        raw_title = video.get('title', {}).get('runs', [{}])[0].get('text', 'No Title')
        raw_author = video.get('ownerText', {}).get('runs', [{}])[0].get('text', 'Unknown')
        
        title = raw_title.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        author = raw_author.replace('\u2026', '...').replace('\u2019', "'").replace('\u201c', '"').replace('\u201d', '"')
        
        return {
            'video_id': video.get('videoId', 'unknown'),
            'title': title,
            'author': author
        }
    except Exception as e:
        print(f"Error parsing video: {str(e)}")
        return None

@app.route('/get_search_suggestions.php', methods=['GET'])
def get_search_suggestions():
    try:
        query = request.args.get('query')
        apikey = request.args.get('apikey', config['api_key'])
        if not query:
            return jsonify({'error': 'Query parameter is required'})
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(f"https://clients1.google.com/complete/search?client=youtube&hl=en&ds=yt&q={quote(query)}", headers=headers)
        data = resp.text.replace('window.google.ac.h(', '').rstrip(')')
        suggestions = json.loads(data)[1][:10]
        return jsonify({'query': query, 'suggestions': suggestions})
    except Exception as e:
        print('Error in get_search_suggestions:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get_search_videos.php', methods=['GET'])
def get_search_videos():
    try:
        query = request.args.get('query')
        count = int(request.args.get('count', str(config.get('default_count', 50))))
        apikey = request.args.get('apikey', config['api_key'])
        if not query:
            return jsonify({'error': 'Параметр query не указан'})
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(query)}&maxResults={count}&type=video&key={apikey}")
        resp.raise_for_status()
        data = resp.json()
        searchResults = []
        for video in data.get('items', []):
            if 'id' not in video or 'videoId' not in video['id']:
                continue
            videoInfo = video['snippet']
            videoId = video['id']['videoId']
            channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey)
            searchResults.append({
                'title': videoInfo['title'],
                'author': videoInfo['channelTitle'],
                'video_id': videoId,
                'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
            })
        return jsonify(searchResults)
    except Exception as e:
        print('Error in get_search_videos:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get_top_videos.php', methods=['GET'])
def get_top_videos():
    try:
        count = int(request.args.get('count', str(config.get('default_count', 50))))
        apikey = request.args.get('apikey', config['api_key'])
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults={count}&key={apikey}")
        resp.raise_for_status()
        data = resp.json()
        topVideos = []
        for video in data.get('items', []):
            videoInfo = video['snippet']
            videoId = video['id']
            channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey)
            topVideos.append({
                'title': videoInfo['title'],
                'author': videoInfo['channelTitle'],
                'video_id': videoId,
                'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
            })
        return jsonify(topVideos)
    except Exception as e:
        print('Error in get_top_videos:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get-categories_videos.php', methods=['GET'])
def get_categories_videos():
    try:
        count = int(request.args.get('count', str(config.get('default_count', 50))))
        categoryId = request.args.get('categoryId')
        apikey = request.args.get('apikey', config['api_key'])
        url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults={count}&key={apikey}"
        if categoryId:
            url += f"&videoCategoryId={categoryId}"
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        topVideos = []
        for video in data.get('items', []):
            videoInfo = video['snippet']
            videoId = video['id']
            channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey)
            topVideos.append({
                'title': videoInfo['title'],
                'author': videoInfo['channelTitle'],
                'video_id': videoId,
                'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
            })
        return jsonify(topVideos)
    except Exception as e:
        print('Error in get-categories_videos:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get-categories.php', methods=['GET'])
def get_categories():
    try:
        region = request.args.get('region', 'US')
        apikey = request.args.get('apikey', config['api_key'])
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode={region}&key={apikey}")
        resp.raise_for_status()
        data = resp.json()
        categories = [{
            'id': item['id'],
            'title': item['snippet']['title']
        } for item in data.get('items', [])]
        return jsonify(categories)
    except Exception as e:
        print('Error in get-categories:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/get-direct-video-url.php', methods=['GET'])
def get_direct_video_url_api():
    try:
        video_id = request.args.get('video_id')
        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})
        video_url = get_direct_video_url(video_id)
        if video_url:
            return jsonify({'video_url': video_url})
        else:
            return jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
    except Exception as e:
        print('Error in get-direct-video-url:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/direct_url', methods=['GET', 'HEAD'])
def direct_url():
    try:
        video_id = request.args.get('video_id')
        quality = request.args.get('quality')
        
        if not video_id:
            response = jsonify({'error': 'ID видео не был передан.'})
            response.status_code = 400
            response.headers['Content-Length'] = str(len(response.get_data()))
            return response

        # Получаем информацию о длительности видео
        duration_value = None
        try:
            ydl_opts_info = {'quiet': True, 'no_warnings': True}
            if config.get('use_cookies', True):
                ydl_opts_info['cookiefile'] = 'cookies.txt'
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                duration_value = info.get('duration')
        except Exception as e:
            print(f"Error fetching duration for video_id {video_id}: {e}")

        # Обработка HEAD запроса
        if request.method == 'HEAD':
            response = Response(None, mimetype='video/mp4')
            if duration_value:
                duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                response.headers['X-Content-Duration'] = duration_str
                response.headers['Content-Duration'] = duration_str
                response.headers['X-Video-Duration'] = duration_str
                response.headers['X-Duration-Seconds'] = duration_str
            # Не устанавливаем Content-Length для HEAD запросов - Cloudflare сам его вычислит
            response.headers['Accept-Ranges'] = 'bytes'
            return response

        # Если указано качество, используем FFmpeg для комбинирования видео и аудио
        if quality:
            try:
                def parse_desired_height(qval):
                    if not qval:
                        return None
                    s = str(qval).strip().lower()
                    try:
                        return int(s)
                    except Exception:
                        pass
                    digits = ''.join(ch for ch in s if ch.isdigit())
                    if digits:
                        try:
                            return int(digits)
                        except Exception:
                            pass
                    aliases = {
                        'tiny': 144, 'small': 240, 'medium': 360, 'large': 480,
                        'hd': 720, 'hd720': 720, '720p': 720,
                        'hd1080': 1080, '1080p': 1080,
                        '144p': 144, '240p': 240, '360p': 360, '480p': 480,
                        '2160p': 2160, '1440p': 1440
                    }
                    return aliases.get(s)

                desired_height = parse_desired_height(quality)

                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': f'bestvideo[height<={desired_height}]+bestaudio/best[height<={desired_height}]' if desired_height else 'best',
                }
                if config.get('use_cookies', True):
                    ydl_opts['cookiefile'] = 'cookies.txt'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                    formats = info.get('formats', [])

                    # Пытаемся найти прогрессивный поток (видео+аудио)
                    progressive_candidates = [
                        f for f in formats
                        if (f.get('vcodec') and f.get('vcodec') != 'none') and (f.get('acodec') and f.get('acodec') != 'none')
                    ]
                    
                    def score_progressive(f):
                        height = f.get('height') or 0
                        ext_score = 1 if f.get('ext') == 'mp4' else 0
                        return (height, ext_score)
                    
                    selected_progressive = None
                    if progressive_candidates:
                        if desired_height is not None:
                            exact_p = [f for f in progressive_candidates if f.get('height') == desired_height]
                            exact_p.sort(key=score_progressive, reverse=True)
                            if exact_p:
                                selected_progressive = exact_p[0]
                            else:
                                selected_progressive = None
                        else:
                            progressive_candidates.sort(key=score_progressive, reverse=True)
                            selected_progressive = progressive_candidates[0]

                    # Если нашли прогрессивный поток, используем его
                    if selected_progressive and selected_progressive.get('url'):
                        prog_url = selected_progressive['url']
                        headers = {
                            'Range': request.headers.get('Range', 'bytes=0-'),
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        resp = requests.get(prog_url, headers=headers, stream=True, timeout=config['request_timeout'])
                        
                        def generate_prog():
                            mark_stream_start()
                            try:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        yield chunk
                            finally:
                                mark_stream_end()
                        
                        response = Response(generate_prog(), status=resp.status_code, mimetype='video/mp4')
                        response.headers['Accept-Ranges'] = 'bytes'
                        if 'content-range' in resp.headers:
                            response.headers['Content-Range'] = resp.headers['content-range']
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
                        return response

                    # Если прогрессивный поток не найден, комбинируем видео и аудио через FFmpeg
                    video_candidates = [
                        f for f in formats
                        if f.get('vcodec') and f.get('vcodec') != 'none' and (f.get('acodec') in (None, 'none'))
                    ]
                    
                    def score_video(f):
                        height = f.get('height') or 0
                        ext_score = 1 if f.get('ext') == 'mp4' else 0
                        return (height, ext_score)

                    selected_video = None
                    if desired_height:
                        exact = [f for f in video_candidates if f.get('height') == desired_height]
                        exact.sort(key=score_video, reverse=True)
                        if exact:
                            selected_video = exact[0]
                        else:
                            lower = [f for f in video_candidates if (f.get('height') or 0) <= desired_height]
                            lower.sort(key=score_video, reverse=True)
                            if lower:
                                selected_video = lower[0]
                    if not selected_video and video_candidates:
                        video_candidates.sort(key=score_video, reverse=True)
                        selected_video = video_candidates[0]

                    # Выбираем аудио поток
                    audio_candidates = [
                        f for f in formats
                        if f.get('acodec') and f.get('acodec') != 'none' and (f.get('vcodec') in (None, 'none'))
                    ]

                    def normalize_lang(lang_value):
                        if not lang_value:
                            return ''
                        lang = str(lang_value).strip().lower()
                        if lang in ('eng', 'en-us', 'en-gb', 'en_usa', 'english'):
                            return 'en'
                        if lang in ('rus', 'ru-ru', 'ru_ru', 'russian'):
                            return 'ru'
                        if lang.startswith('en'):
                            return 'en'
                        if lang.startswith('ru'):
                            return 'ru'
                        return lang

                    def get_lang_from_format(fmt):
                        for key in ('language', 'lang', 'language_code', 'audio_lang'):
                            if key in fmt and fmt.get(key):
                                return normalize_lang(fmt.get(key))
                        return ''

                    def score_audio(f):
                        abr = f.get('abr') or 0
                        ext_score = 1 if f.get('ext') in ('m4a', 'mp4') else 0
                        return (ext_score, abr)

                    selected_audio = None
                    if audio_candidates:
                        en_list = [f for f in audio_candidates if get_lang_from_format(f) == 'en']
                        ru_list = [f for f in audio_candidates if get_lang_from_format(f) == 'ru']
                        other_list = [f for f in audio_candidates if get_lang_from_format(f) not in ('en', 'ru')]
                        for lst in (en_list, ru_list, other_list):
                            if lst:
                                lst.sort(key=score_audio, reverse=True)
                                selected_audio = lst[0]
                                break

                    if not selected_video or not selected_audio:
                        response = jsonify({'error': 'Не удалось подобрать видео/аудио потоки для заданного качества.'})
                        response.status_code = 500
                        response.headers['Content-Length'] = str(len(response.get_data()))
                        return response

                    video_url = selected_video.get('url')
                    audio_url = selected_audio.get('url')
                    if not video_url or not audio_url:
                        response = jsonify({'error': 'Не удалось получить ссылки на потоки.'})
                        response.status_code = 500
                        response.headers['Content-Length'] = str(len(response.get_data()))
                        return response

                    # Комбинируем потоки через FFmpeg
                    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                    common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                    ffmpeg_cmd = [
                        'ffmpeg',
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-nostdin',
                        '-reconnect', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_at_eof', '1',
                        '-reconnect_delay_max', '10',
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', video_url,
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', audio_url,
                        '-map', '0:v:0',
                        '-map', '1:a:0',
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '160k',
                        '-movflags', 'frag_keyframe+empty_moov',
                        '-f', 'mp4',
                        '-'
                    ]

                    ffmpeg_process = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0
                    )

                    def _drain_stderr():
                        try:
                            while True:
                                line = ffmpeg_process.stderr.readline()
                                if not line:
                                    break
                        except Exception:
                            pass
                    threading.Thread(target=_drain_stderr, daemon=True).start()

                    def generate():
                        mark_stream_start()
                        try:
                            while True:
                                chunk = ffmpeg_process.stdout.read(65536)
                                if not chunk:
                                    break
                                yield chunk
                        finally:
                            try:
                                ffmpeg_process.terminate()
                            except Exception:
                                pass
                            mark_stream_end()

                    response = Response(generate(), mimetype='video/mp4')
                    if duration_value:
                        duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                        response.headers['X-Content-Duration'] = duration_str
                        response.headers['Content-Duration'] = duration_str
                        response.headers['X-Video-Duration'] = duration_str
                        response.headers['X-Duration-Seconds'] = duration_str
                    return response

            except Exception as e:
                print('Error in direct_url (ffmpeg mux):', e)
                response = jsonify({'error': 'Internal server error'})
                response.status_code = 500
                response.headers['Content-Length'] = str(len(response.get_data()))
                return response

        # Fallback: прямой прокси без FFmpeg
        video_url = get_direct_video_url(video_id)
        if not video_url:
            response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
            response.status_code = 500
            response.headers['Content-Length'] = str(len(response.get_data()))
            return response
            
        headers = {
            'Range': request.headers.get('Range', 'bytes=0-'),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
        
        def generate():
            mark_stream_start()
            try:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                mark_stream_end()
        
        response = Response(generate(), status=resp.status_code, mimetype='video/mp4')
        response.headers['Accept-Ranges'] = 'bytes'
        if 'content-range' in resp.headers:
            response.headers['Content-Range'] = resp.headers['content-range']
        if duration_value:
            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
            response.headers['X-Content-Duration'] = duration_str
            response.headers['Content-Duration'] = duration_str
            response.headers['X-Video-Duration'] = duration_str
            response.headers['X-Duration-Seconds'] = duration_str
        return response

    except Exception as e:
        print('Error in direct_url:', e)
        response = jsonify({'error': 'Internal server error'})
        response.status_code = 500
        response.headers['Content-Length'] = str(len(response.get_data()))
        return response

@app.route('/direct_audio_url', methods=['GET', 'HEAD'])
def direct_audio_url():
    try:
        video_id = request.args.get('video_id')
        
        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'}), 400
        
        duration_value = None
        try:
            ydl_opts_info = {'quiet': True, 'no_warnings': True}
            if config.get('use_cookies', True):
                ydl_opts_info['cookiefile'] = 'cookies.txt'
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                duration_value = info.get('duration')
        except Exception as e:
            print(f"Error fetching duration for video_id {video_id}: {e}")

        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'bestaudio',
            }
            if config.get('use_cookies', True):
                ydl_opts['cookiefile'] = 'cookies.txt'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                formats = info.get('formats', [])

                # Select audio-only stream
                audio_candidates = [
                    f for f in formats
                    if f.get('acodec') and f.get('acodec') != 'none' and (f.get('vcodec') in (None, 'none'))
                ]

                def normalize_lang(lang_value):
                    if not lang_value:
                        return ''
                    lang = str(lang_value).strip().lower()
                    if lang in ('eng', 'en-us', 'en-gb', 'en_usa', 'english'):
                        return 'en'
                    if lang in ('rus', 'ru-ru', 'ru_ru', 'russian'):
                        return 'ru'
                    if lang.startswith('en'):
                        return 'en'
                    if lang.startswith('ru'):
                        return 'ru'
                    return lang

                def get_lang_from_format(fmt):
                    for key in ('language', 'lang', 'language_code', 'audio_lang'):
                        if key in fmt and fmt.get(key):
                            return normalize_lang(fmt.get(key))
                    return ''

                def score_audio(f):
                    abr = f.get('abr') or 0
                    ext_score = 1 if f.get('ext') in ('m4a', 'mp4') else 0
                    return (ext_score, abr)

                selected_audio = None
                if audio_candidates:
                    en_list = [f for f in audio_candidates if get_lang_from_format(f) == 'en']
                    ru_list = [f for f in audio_candidates if get_lang_from_format(f) == 'ru']
                    other_list = [f for f in audio_candidates if get_lang_from_format(f) not in ('en', 'ru')]
                    for lst in (en_list, ru_list, other_list):
                        if lst:
                            lst.sort(key=score_audio, reverse=True)
                            selected_audio = lst[0]
                            break

                if not selected_audio:
                    return jsonify({'error': 'Не удалось подобрать аудио поток.'}), 500

                audio_url = selected_audio.get('url')
                if not audio_url:
                    return jsonify({'error': 'Не удалось получить ссылку на аудио поток.'}), 500

                # Proxy the audio stream
                headers = {
                    'Range': request.headers.get('Range', 'bytes=0-'),
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                resp = requests.get(audio_url, headers=headers, stream=True, timeout=config['request_timeout'])
                
                def generate():
                    mark_stream_start()
                    try:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                yield chunk
                    finally:
                        mark_stream_end()
                
                response = Response(None if request.method == 'HEAD' else generate(), status=resp.status_code)
                response.headers['Content-Type'] = resp.headers.get('content-type', 'audio/m4a')
                response.headers['Content-Length'] = resp.headers.get('content-length', '')
                response.headers['Accept-Ranges'] = 'bytes'
                if 'content-range' in resp.headers:
                    response.headers['Content-Range'] = resp.headers['content-range']
                if duration_value:
                    duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                    response.headers['X-Content-Duration'] = duration_str
                    response.headers['Content-Duration'] = duration_str
                    response.headers['X-Video-Duration'] = duration_str
                    response.headers['X-Duration-Seconds'] = duration_str
                return response

        except Exception as e:
            print('Error in direct_audio_url:', e)
            return jsonify({'error': 'Internal server error'}), 500

    except Exception as e:
        print('Error in direct_audio_url:', e)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/download', methods=['GET'])
def download_video():
    try:
        video_id = request.args.get('video_id')
        quality = request.args.get('quality')
        
        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'}), 400

        # Получаем информацию о видео для названия файла
        video_title = "video"
        try:
            ydl_opts_info = {'quiet': True, 'no_warnings': True}
            if config.get('use_cookies', True):
                ydl_opts_info['cookiefile'] = 'cookies.txt'
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                video_title = info.get('title', 'video')
                # Очищаем название файла от недопустимых символов
                video_title = re.sub(r'[<>:"/\\|?*]', '_', video_title)
        except Exception as e:
            print(f"Error fetching video info for video_id {video_id}: {e}")

        # Если указано качество, используем FFmpeg для комбинирования видео и аудио
        if quality:
            try:
                def parse_desired_height(qval):
                    if not qval:
                        return None
                    s = str(qval).strip().lower()
                    try:
                        return int(s)
                    except Exception:
                        pass
                    digits = ''.join(ch for ch in s if ch.isdigit())
                    if digits:
                        try:
                            return int(digits)
                        except Exception:
                            pass
                    aliases = {
                        'tiny': 144, 'small': 240, 'medium': 360, 'large': 480,
                        'hd': 720, 'hd720': 720, '720p': 720,
                        'hd1080': 1080, '1080p': 1080,
                        '144p': 144, '240p': 240, '360p': 360, '480p': 480,
                        '2160p': 2160, '1440p': 1440
                    }
                    return aliases.get(s)

                desired_height = parse_desired_height(quality)

                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'format': f'bestvideo[height<={desired_height}]+bestaudio/best[height<={desired_height}]' if desired_height else 'best',
                }
                if config.get('use_cookies', True):
                    ydl_opts['cookiefile'] = 'cookies.txt'

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
                    formats = info.get('formats', [])

                    # Пытаемся найти прогрессивный поток (видео+аудио)
                    progressive_candidates = [
                        f for f in formats
                        if (f.get('vcodec') and f.get('vcodec') != 'none') and (f.get('acodec') and f.get('acodec') != 'none')
                    ]
                    
                    def score_progressive(f):
                        height = f.get('height') or 0
                        ext_score = 1 if f.get('ext') == 'mp4' else 0
                        return (height, ext_score)
                    
                    selected_progressive = None
                    if progressive_candidates:
                        if desired_height is not None:
                            exact_p = [f for f in progressive_candidates if f.get('height') == desired_height]
                            exact_p.sort(key=score_progressive, reverse=True)
                            if exact_p:
                                selected_progressive = exact_p[0]
                            else:
                                selected_progressive = None
                        else:
                            progressive_candidates.sort(key=score_progressive, reverse=True)
                            selected_progressive = progressive_candidates[0]

                    # Если нашли прогрессивный поток, используем его
                    if selected_progressive and selected_progressive.get('url'):
                        prog_url = selected_progressive['url']
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        resp = requests.get(prog_url, headers=headers, stream=True, timeout=config['request_timeout'])
                        
                        def generate_prog():
                            mark_stream_start()
                            try:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        yield chunk
                            finally:
                                mark_stream_end()
                        
                        response = Response(generate_prog(), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        return response

                    # Если прогрессивный поток не найден, комбинируем видео и аудио через FFmpeg
                    video_candidates = [
                        f for f in formats
                        if f.get('vcodec') and f.get('vcodec') != 'none' and (f.get('acodec') in (None, 'none'))
                    ]
                    
                    def score_video(f):
                        height = f.get('height') or 0
                        ext_score = 1 if f.get('ext') == 'mp4' else 0
                        return (height, ext_score)

                    selected_video = None
                    if desired_height:
                        exact = [f for f in video_candidates if f.get('height') == desired_height]
                        exact.sort(key=score_video, reverse=True)
                        if exact:
                            selected_video = exact[0]
                        else:
                            lower = [f for f in video_candidates if (f.get('height') or 0) <= desired_height]
                            lower.sort(key=score_video, reverse=True)
                            if lower:
                                selected_video = lower[0]
                    if not selected_video and video_candidates:
                        video_candidates.sort(key=score_video, reverse=True)
                        selected_video = video_candidates[0]

                    # Выбираем аудио поток
                    audio_candidates = [
                        f for f in formats
                        if f.get('acodec') and f.get('acodec') != 'none' and (f.get('vcodec') in (None, 'none'))
                    ]

                    def normalize_lang(lang_value):
                        if not lang_value:
                            return ''
                        lang = str(lang_value).strip().lower()
                        if lang in ('eng', 'en-us', 'en-gb', 'en_usa', 'english'):
                            return 'en'
                        if lang in ('rus', 'ru-ru', 'ru_ru', 'russian'):
                            return 'ru'
                        if lang.startswith('en'):
                            return 'en'
                        if lang.startswith('ru'):
                            return 'ru'
                        return lang

                    def get_lang_from_format(fmt):
                        for key in ('language', 'lang', 'language_code', 'audio_lang'):
                            if key in fmt and fmt.get(key):
                                return normalize_lang(fmt.get(key))
                        return ''

                    def score_audio(f):
                        abr = f.get('abr') or 0
                        ext_score = 1 if f.get('ext') in ('m4a', 'mp4') else 0
                        return (ext_score, abr)

                    selected_audio = None
                    if audio_candidates:
                        en_list = [f for f in audio_candidates if get_lang_from_format(f) == 'en']
                        ru_list = [f for f in audio_candidates if get_lang_from_format(f) == 'ru']
                        other_list = [f for f in audio_candidates if get_lang_from_format(f) not in ('en', 'ru')]
                        for lst in (en_list, ru_list, other_list):
                            if lst:
                                lst.sort(key=score_audio, reverse=True)
                                selected_audio = lst[0]
                                break

                    if not selected_video or not selected_audio:
                        return jsonify({'error': 'Не удалось подобрать видео/аудио потоки для заданного качества.'}), 500

                    video_url = selected_video.get('url')
                    audio_url = selected_audio.get('url')
                    if not video_url or not audio_url:
                        return jsonify({'error': 'Не удалось получить ссылки на потоки.'}), 500

                    # Комбинируем потоки через FFmpeg
                    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                    common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                    ffmpeg_cmd = [
                        'ffmpeg',
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-nostdin',
                        '-reconnect', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_at_eof', '1',
                        '-reconnect_delay_max', '10',
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', video_url,
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', audio_url,
                        '-map', '0:v:0',
                        '-map', '1:a:0',
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '160k',
                        '-movflags', 'frag_keyframe+empty_moov',
                        '-f', 'mp4',
                        '-'
                    ]

                    ffmpeg_process = subprocess.Popen(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0
                    )

                    def _drain_stderr():
                        try:
                            while True:
                                line = ffmpeg_process.stderr.readline()
                                if not line:
                                    break
                        except Exception:
                            pass
                    threading.Thread(target=_drain_stderr, daemon=True).start()

                    def generate():
                        mark_stream_start()
                        try:
                            while True:
                                chunk = ffmpeg_process.stdout.read(65536)
                                if not chunk:
                                    break
                                yield chunk
                        finally:
                            try:
                                ffmpeg_process.terminate()
                            except Exception:
                                pass
                            mark_stream_end()

                    response = Response(generate(), mimetype='video/mp4')
                    response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                    return response

            except Exception as e:
                print('Error in download (ffmpeg mux):', e)
                return jsonify({'error': 'Internal server error'}), 500

        # Fallback: прямой прокси без FFmpeg
        video_url = get_direct_video_url(video_id)
        if not video_url:
            return jsonify({'error': 'Не удалось получить прямую ссылку на видео.'}), 500
            
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
        
        def generate():
            mark_stream_start()
            try:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                mark_stream_end()
        
        response = Response(generate(), mimetype='video/mp4')
        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
        return response

    except Exception as e:
        print('Error in download:', e)
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/thumbnail/<video_id>')
def thumbnail_proxy(video_id):
    try:
        url = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'
        resp = requests.get(url, stream=True, timeout=10)
        return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'image/jpeg'))
    except Exception as e:
        print('Error in /thumbnail:', e)
        return '', 404

@app.route('/get-ytvideo-info.php', methods=['GET'])
def get_ytvideo_info():
    try:
        video_id = request.args.get('video_id')
        quality = request.args.get('quality', config['default_quality'])
        apikey = request.args.get('apikey', config['api_key'])
        proxy_param = request.args.get('proxy', 'true').lower()
        use_video_proxy = proxy_param != 'false'
        
        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})
        
        # API call to YouTube Data API v3, including 'contentDetails' part
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={apikey}&part=snippet,contentDetails,statistics", timeout=config['request_timeout'])
        resp.raise_for_status()
        data = resp.json()
        videoData = data['items'][0] if data.get('items') and data['items'] else None
        
        if not videoData:
            return jsonify({'error': 'Видео не найдено.'})
        
        videoInfo = videoData['snippet']
        contentDetails = videoData['contentDetails'] # This is where duration is found
        statistics = videoData['statistics']
        channelId = videoInfo['channelId']
        
        
        r = requests.get(
            f"https://www.googleapis.com/youtube/v3/channels?id={channelId}&key={apikey}&part=snippet,statistics", 
            timeout=config['request_timeout']
        )
        r.raise_for_status()
        data = r.json()
        
        print(f"DEBUG: API response: {json.dumps(data, ensure_ascii=False)[:200]}...")
        
        if data.get('items') and data['items']:
            # Get channel thumbnail from channel data
            channel_snippet = data['items'][0]['snippet']
            thumbnail_url = channel_snippet['thumbnails']['default']['url']
            subscriberCount = data['items'][0]['statistics']['subscriberCount']
            channelThumbnail = thumbnail_url
            print(subscriberCount)
        
        # Rest of your code remains the same...
        finalVideoUrl = ''
        if not use_video_proxy:
            finalVideoUrlWithProxy = get_real_direct_video_url(video_id)
        else:
            if config['video_source'] == 'direct':
                finalVideoUrl = f"{config['mainurl']}direct_url?video_id={video_id}"
                finalVideoUrlWithProxy = finalVideoUrl
            else:
                finalVideoUrl = get_direct_video_url(video_id) if config['video_source'] == 'direct' else ''
                finalVideoUrlWithProxy = finalVideoUrl
                if config['use_video_proxy'] and finalVideoUrl:
                    finalVideoUrlWithProxy = f"{config['mainurl']}video.proxy?url={quote(finalVideoUrl)}"
        
        comments = []
        try:
            comments_resp = requests.get(f"https://www.googleapis.com/youtube/v3/commentThreads?key={apikey}&textFormat=plainText&part=snippet&videoId={video_id}&maxResults=25", timeout=config['request_timeout'])
            comments_resp.raise_for_status()
            comments_data = comments_resp.json()
            for item in comments_data.get('items', []):
                commentAuthorId = item['snippet']['topLevelComment']['snippet']['authorChannelId']['value']
                commentAuthorThumbnail = get_channel_thumbnail(commentAuthorId, apikey)
                comments.append({
                    'author': item['snippet']['topLevelComment']['snippet']['authorDisplayName'],
                    'text': item['snippet']['topLevelComment']['snippet']['textDisplay'],
                    'published_at': item['snippet']['topLevelComment']['snippet']['publishedAt'],
                    'author_thumbnail': get_proxy_url(commentAuthorThumbnail, config['use_channel_thumbnail_proxy'])
                })
        except Exception as e:
            print('Error loading comments:', e)
        
        publishedAt = datetime.strptime(videoInfo['publishedAt'], '%Y-%m-%dT%H:%M:%SZ')
        publishedAtFormatted = publishedAt.strftime('%d.%m.%Y, %H:%M:%S')
        
        result = {
            'title': videoInfo['title'],
            'author': videoInfo['channelTitle'],
            'subscriberCount': subscriberCount,
            'description': videoInfo['description'],
            'video_id': video_id,
            'embed_url': f"https://www.youtube.com/embed/{video_id}",
            'duration': contentDetails['duration'], # This line already includes duration
            'published_at': publishedAtFormatted,
            'likes': statistics.get('likeCount'),
            'views': statistics.get('viewCount'),
            'comment_count': statistics.get('commentCount'),
            'comments': comments,
            'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
            'thumbnail': f"{config['mainurl']}thumbnail/{video_id}",
            'video_url': finalVideoUrlWithProxy
        }
        
        return jsonify(result)
        
    except Exception as e:
        print('Error in get-ytvideo-info:', e)
        return jsonify({'error': 'Internal server error'})

@app.route('/video.proxy', methods=['GET'])
def video_proxy():
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({'error': 'URL parameter is required'}), 400
        try:
            _ = urlparse(url)
        except Exception:
            return jsonify({'error': 'Invalid URL format'}), 400
        headers = {
            'Range': request.headers.get('Range', 'bytes=0-'),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, stream=True, timeout=config['request_timeout'])
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                pass
        response = Response(generate(), status=resp.status_code)
        response.headers['Content-Type'] = resp.headers.get('content-type', 'application/octet-stream')
        response.headers['Content-Length'] = resp.headers.get('content-length', '')
        response.headers['Accept-Ranges'] = 'bytes'
        if 'content-range' in resp.headers:
            response.headers['Content-Range'] = resp.headers['content-range']
        return response
    except Exception as e:
        print('Error in video proxy:', e)
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Запуск сервера в многопоточном режиме
    app.run(host='0.0.0.0', port=2823, threaded=True)