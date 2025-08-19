import os
import sys
import json
import requests
from flask import Flask, request, jsonify, redirect, send_from_directory, Response
from flask_cors import CORS
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode, urlparse
import yt_dlp
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import googleapiclient.discovery
import uuid
import subprocess
import threading
import time

app = Flask(__name__)
CORS(app)

# Load configuration from config.json
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# OAuth configuration from config
CLIENT_ID = config.get('oauth_client_id', '')
CLIENT_SECRET = config.get('oauth_client_secret', '')
REDIRECT_URI = config.get('oauth_redirect_uri', 'http://localhost:2823/oauth-callback')
SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Session storage
sessions = {}
tokens_file = 'tokens.json'

# Load saved tokens
if os.path.exists(tokens_file):
    with open(tokens_file, 'r') as f:
        saved_tokens = json.load(f)
else:
    saved_tokens = {}

def save_tokens():
    with open(tokens_file, 'w') as f:
        json.dump(saved_tokens, f)

# Helper functions

# Streaming activity tracking for auto-restart
active_streams_lock = threading.Lock()
active_streams = 0
last_stream_activity = time.time()

def mark_stream_start():
    global active_streams, last_stream_activity
    with active_streams_lock:
        active_streams += 1
        last_stream_activity = time.time()

def mark_stream_end():
    global active_streams, last_stream_activity
    with active_streams_lock:
        if active_streams > 0:
            active_streams -= 1
        last_stream_activity = time.time()

def get_channel_thumbnail(channel_id, api_key):
    if not config['fetch_channel_thumbnails']:
        return ''
    try:
        r = requests.get(f"https://www.googleapis.com/youtube/v3/channels?id={channel_id}&key={api_key}&part=snippet", timeout=config['request_timeout'])
        r.raise_for_status()
        data = r.json()
        return data['items'][0]['snippet']['thumbnails']['default']['url'] if data['items'] else ''
    except Exception as e:
        print('Error getting channel thumbnail:', e)
        return ''

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
        # Получение прямой ссылки на видео
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

@app.route('/auth')
def auth():
    session_id = str(uuid.uuid4())
    flow = Flow.from_client_config(
        client_config={
            'web': {
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token'
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    
    flow.redirect_uri = REDIRECT_URI
    
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=session_id
    )
    
    return jsonify({
        'auth_url': auth_url,
        'session_id': session_id
    })

@app.route('/oauth-callback')
def oauth_callback():
    try:
        code = request.args.get('code')
        session_id = request.args.get('state')
        
        if not code or not session_id:
            return jsonify({'error': 'Missing code or session_id'}), 400
        
        flow = Flow.from_client_config(
            client_config={
                'web': {
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                    'token_uri': 'https://oauth2.googleapis.com/token',
                    'redirect_uris': [REDIRECT_URI]
                }
            },
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        # Получаем информацию о пользователе
        youtube = googleapiclient.discovery.build(
            'oauth2', 'v2', credentials=credentials)
        user_info = youtube.userinfo().get().execute()
        
        # Сохраняем сессию
        sessions[session_id] = {
            'tokens': {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'scopes': credentials.scopes,
                'expiry': credentials.expiry.isoformat() if credentials.expiry else None
            },
            'user_info': user_info,
            'created_at': datetime.now().isoformat()
        }
        
        # Сохраняем refresh token
        if credentials.refresh_token:
            saved_tokens[user_info['id']] = {
                'refresh_token': credentials.refresh_token,
                'user_info': user_info
            }
            save_tokens()
        
        # Безопасный редирект с проверкой frontend_url
        frontend_url = config.get('frontend_url', 'http://localhost:3000')
        safe_redirect_url = f"{frontend_url}/auth-success?session_id={session_id}"
        
        return redirect(safe_redirect_url)
    
    except Exception as e:
        print('OAuth callback error:', str(e))
        return jsonify({'error': 'Authentication failed', 'details': str(e)}), 500

@app.route('/get_recommendations', methods=['GET'])
def get_yt_recommendations():
    try:
        # 1. Проверяем аутентификацию
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'Missing user_id parameter'}), 400
            
        user_data = saved_tokens.get(user_id)
        if not user_data or not user_data.get('refresh_token'):
            return jsonify({'error': 'User not authenticated or token missing'}), 401

        # 2. Создаем авторизованный клиент YouTube
        creds = Credentials(
            token=None,
            refresh_token=user_data['refresh_token'],
            token_uri='https://oauth2.googleapis.com/token',
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=SCOPES
        )
        creds.refresh(Request())

        youtube = googleapiclient.discovery.build(
            'youtube', 'v3', 
            credentials=creds,
            cache_discovery=False
        )

        # 3. Получаем рекомендации через несколько методов
        all_recommendations = []
        
        # Метод 1: Популярные видео
        try:
            popular_request = youtube.videos().list(
                part="snippet",
                chart="mostPopular",
                maxResults=15,
                regionCode="US"
            )
            popular_response = popular_request.execute()
            for item in popular_response.get('items', []):
                all_recommendations.append({
                    'type': 'popular',
                    'video_id': item['id'],
                    'title': item['snippet']['title'],
                    'channel': item['snippet']['channelTitle'],
                    'thumbnail': item['snippet']['thumbnails']['high']['url']
                })
        except Exception as e:
            print(f"Error fetching popular videos: {str(e)}")

        # Метод 2: Персональные рекомендации
        try:
            activities_request = youtube.activities().list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=15
            )
            activities_response = activities_request.execute()
            for item in activities_response.get('items', []):
                if 'upload' in item['contentDetails']:
                    vid = item['contentDetails']['upload']['videoId']
                    all_recommendations.append({
                        'type': 'personalized',
                        'video_id': vid,
                        'title': item['snippet']['title'],
                        'channel': item['snippet']['channelTitle'],
                        'thumbnail': f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    })
        except Exception as e:
            print(f"Error fetching activities: {str(e)}")

        # 4. Удаляем дубликаты
        unique_recommendations = []
        seen_videos = set()
        for rec in all_recommendations:
            if rec['video_id'] not in seen_videos:
                seen_videos.add(rec['video_id'])
                unique_recommendations.append(rec)

        return jsonify({
            'status': 'success',
            'count': len(unique_recommendations),
            'recommendations': unique_recommendations
        })

    except Exception as e:
        print(f"API request failed: {str(e)}")
        return jsonify({
            'error': 'API request failed',
            'details': str(e)
        }), 500

@app.route('/get_author_videos_by_id.php', methods=['GET'])
def get_author_videos_by_id():
    try:
        channel_id = request.args.get('channel_id')
        count = int(request.args.get('count', '50'))
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

        # Redirect to get_author_videos_by_id.php with the found channel ID
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
        count = int(request.args.get('count', '50'))
        apikey = request.args.get('apikey', config['api_key'])

        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})

        video_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={apikey}")
        video_resp.raise_for_status()
        video_data = video_resp.json()
        videoInfo = video_data['items'][0]['snippet'] if video_data.get('items') and video_data['items'] else None

        if not videoInfo:
            return jsonify({'error': 'Видео не найдено.'})

        search_resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(videoInfo['title'])}&type=video&maxResults={count}&key={apikey}")
        search_resp.raise_for_status()
        search_data = search_resp.json()
        relatedVideos = []

        for video in search_data.get('items', []):
            if video['id']['videoId'] == video_id:
                continue
            vinfo = video['snippet']
            vid = video['id']['videoId']
            channelThumbnail = get_channel_thumbnail(vinfo['channelId'], apikey)
            # Get video statistics
            stats_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={apikey}")
            stats_resp.raise_for_status()
            stats_data = stats_resp.json()
            viewCount = stats_data['items'][0]['statistics']['viewCount'] if stats_data.get('items') and stats_data['items'] else '0'
            relatedVideos.append({
                'title': vinfo['title'],
                'author': vinfo['channelTitle'],
                'video_id': vid,
                'views': viewCount,
                'thumbnail': f"{config['mainurl']}thumbnail/{vid}",
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
                'url': get_video_proxy_url(f"{config['url']}/get-ytvideo-info.php?video_id={vid}&quality={config['default_quality']}", config['use_video_proxy'])
            })
        return jsonify(relatedVideos)
    except Exception as e:
        print('Error in get_related_videos:', e)
        return jsonify({'error': 'Internal server error'})

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
        count = int(request.args.get('count', '50'))
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
        count = int(request.args.get('count', '50'))
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
        count = int(request.args.get('count', '50'))
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
            return jsonify({'error': 'ID видео не был передан.'}), 400

        # Fetch video duration upfront using yt_dlp
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

        # If a quality is provided, combine video+audio using FFmpeg
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

                    # Try to use a progressive (audio+video) stream first
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
                                selected_progressive = None  # Force FFmpeg mux path
                        else:
                            progressive_candidates.sort(key=score_progressive, reverse=True)
                            selected_progressive = progressive_candidates[0]

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
                        response = Response(None if request.method == 'HEAD' else generate_prog(), status=resp.status_code)
                        response.headers['Content-Type'] = resp.headers.get('content-type', 'video/mp4')
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

                    # Select video-only stream
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

                    if not selected_video or not selected_audio:
                        return jsonify({'error': 'Не удалось подобрать видео/аудио потоки для заданного качества.'}), 500

                    video_url = selected_video.get('url')
                    audio_url = selected_audio.get('url')
                    if not video_url or not audio_url:
                        return jsonify({'error': 'Не удалось получить ссылки на потоки.'}), 500

                    # Build FFmpeg command to mux and stream fragmented MP4
                    # If only headers requested, avoid spawning FFmpeg
                    if request.method == 'HEAD':
                        response = Response(None, mimetype='video/mp4')
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
                        return response

                    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                    common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                    ffmpeg_cmd = [
                        'ffmpeg',
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-nostdin',
                        # Reconnect options for HTTP inputs
                        '-reconnect', '1',
                        '-reconnect_streamed', '1',
                        '-reconnect_at_eof', '1',
                        '-reconnect_delay_max', '10',
                        # Input 0 (video)
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', video_url,
                        # Input 1 (audio)
                        '-user_agent', user_agent,
                        '-headers', common_headers,
                        '-i', audio_url,
                        # Mapping
                        '-map', '0:v:0',
                        '-map', '1:a:0',
                        # Codecs
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '160k',
                        # Container/streaming flags
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
                return jsonify({'error': 'Internal server error'}), 500

        # Fallback: proxy a single direct URL (progressive)
        video_url = get_direct_video_url(video_id)
        if not video_url:
            return jsonify({'error': 'Не удалось получить прямую ссылку на видео.'}), 500
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
        response = Response(generate(), status=resp.status_code)
        response.headers['Content-Type'] = resp.headers.get('content-type', 'video/mp4')
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
        print('Error in direct_url:', e)
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

@app.route('/embed', methods=['GET'])
def embed():
    video_id = request.args.get('video_id')
    if not video_id:
        return '<h2>Не передан video_id</h2>', 400
    try:
        # Получаем данные о видео только через yt-dlp
        video_info = get_video_info_ytdlp(video_id)
        if not video_info:
            return '<h2>Видео не найдено или не удалось получить данные</h2>', 404
        # Форматируем дату публикации
        published_at = video_info['published_at']
        if published_at and len(published_at) == 8:
            published_at = f"{published_at[6:8]}.{published_at[4:6]}.{published_at[0:4]}"
        else:
            published_at = ''
        # Форматируем длительность и готовим числовое значение для встраивания в JS
        duration = video_info['duration']
        if duration:
            duration_str = str(timedelta(seconds=duration))
            duration_seconds = int(duration)
        else:
            duration_str = ''
            duration_seconds = 0
        return '''
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link href="https://fonts.googleapis.com/css?family=Roboto:400,500,700&display=swap" rel="stylesheet">
            <title>{title} — YouTube Legacy Embed</title>
            <style>
                html, body {{
                    height: 100%;
                    margin: 0;
                    padding: 0;
                    background: #000;
                    overflow: hidden;
                    font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
                }}
                body {{
                    width: 100vw;
                    height: 100vh;
                    font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
                }}
                .video-bg {{
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    width: 100vw;
                    height: 100vh;
                    background: #000;
                    z-index: 0;
                }}
                .video-title-bar {{
                    position: absolute;
                    top: 0; left: 0; right: 0;
                    width: 100vw;
                    background: linear-gradient(180deg, rgba(0,0,0,0.85) 80%, rgba(0,0,0,0.0) 100%);
                    color: #fff;
                    padding: 32px 40px 24px 40px;
                    font-size: 1.5em;
                    font-weight: 600;
                    letter-spacing: 0.01em;
                    z-index: 10;
                    display: flex;
                    align-items: flex-end;
                    min-height: 90px;
                    box-sizing: border-box;
                    opacity: 1;
                    transition: opacity 0.5s;
                    pointer-events: auto;
                    font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
                }}
                .video-title-bar.hide {{
                    opacity: 0;
                    pointer-events: none;
                }}
                .player-wrapper {{
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    width: 100vw;
                    height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 1;
                }}
                video {{
                    width: 100vw;
                    height: 100vh;
                    object-fit: contain;
                    background: #000;
                    display: block;
                }}
                .custom-controls {{
                    position: absolute;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    width: 100vw;
                    background: linear-gradient(0deg, rgba(0,0,0,0.85) 80%, rgba(0,0,0,0.0) 100%);
                    z-index: 20;
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    padding: 0 24px 18px 24px;
                    user-select: none;
                    opacity: 1;
                    transition: opacity 0.4s;
                    flex-wrap: wrap;
                    min-width: 0;
                    box-sizing: border-box;
                }}
                .custom-controls.hide {{
                    opacity: 0;
                    pointer-events: none;
                }}
                .play-btn, .fullscreen-btn {{
                    background: none;
                    border: none;
                    color: #fff;
                    border-radius: 50%;
                    width: 44px;
                    height: 44px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    font-size: 1.5em;
                    transition: background 0.2s;
                    outline: none;
                    min-width: 44px;
                    min-height: 44px;
                }}
                .play-btn img {{
                    width: 28px;
                    height: 28px;
                    display: block;
                }}
                .play-btn:hover, .fullscreen-btn:hover {{
                    background: rgba(60,60,60,0.35);
                }}
                .progress-container {{
                    flex: 1;
                    display: flex;
                    align-items: center;
                    height: 32px;
                    margin: 0 12px;
                    min-width: 40px;
                    max-width: 100%;
                }}
                .progress-bar-bg {{
                    width: 100%;
                    height: 6px;
                    background: #333;
                    border-radius: 3px;
                    cursor: pointer;
                    position: relative;
                }}
                .progress-bar-fill {{
                    height: 100%;
                    background: #f00;
                    border-radius: 3px;
                    width: 0%;
                    position: absolute;
                    left: 0; top: 0;
                }}
                .progress-bar-knob {{
                    position: absolute;
                    top: 50%;
                    transform: translateY(-50%);
                    width: 14px;
                    height: 14px;
                    background: #fff;
                    border-radius: 50%;
                    left: 0%;
                    margin-left: -7px;
                    box-shadow: 0 2px 8px #0006;
                    pointer-events: none;
                }}
                .time-label {{
                    color: #fff;
                    font-size: 1em;
                    min-width: 70px;
                    text-align: center;
                    font-variant-numeric: tabular-nums;
                    font-family: 'Roboto', 'Segoe UI', Arial, sans-serif;
                }}
                .fullscreen-btn {{
                    margin-left: 10px;
                    margin-right: 0;
                    flex-shrink: 0;
                }}
                @media (max-width: 600px) {{
                    .video-title-bar {{
                        font-size: 1em;
                        padding: 18px 12px 12px 12px;
                        min-height: 48px;
                    }}
                    .custom-controls {{
                        padding: 0 2vw 8px 2vw;
                        gap: 6px;
                        flex-wrap: wrap;
                        box-sizing: border-box;
                    }}
                    .play-btn, .fullscreen-btn {{
                        width: 36px;
                        height: 36px;
                        font-size: 1.1em;
                        min-width: 36px;
                        min-height: 36px;
                    }}
                    .play-btn img {{
                        width: 20px;
                        height: 20px;
                    }}
                    .progress-container {{
                        min-width: 20px;
                        max-width: 100%;
                    }}
                    .time-label {{
                        min-width: 38px;
                        font-size: 0.85em;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="video-bg"></div>
            <div class="player-wrapper">
                <video id="yt-embed-video" preload="auto" src="{video_url}"></video>
                <!-- Пример использования превью -->
                <img src="/thumbnail/{video_id}" alt="thumbnail" style="display:none;" id="videoThumbnail">
                <div class="custom-controls" id="controlsBar">
                    <button class="play-btn" id="playBtn" title="Воспроизвести/Пауза"><img id="playPauseIcon" src="https://cdn-icons-png.flaticon.com/512/9974/9974136.png" alt="play"></button>
                    <div class="progress-container">
                        <div class="progress-bar-bg" id="progressBarBg">
                            <div class="progress-bar-fill" id="progressBarFill"></div>
                            <div class="progress-bar-knob" id="progressBarKnob"></div>
                        </div>
                    </div>
                    <span class="time-label" id="timeLabel">0:00 / 0:00</span>
                    <button class="fullscreen-btn" id="fullscreenBtn" title="На весь экран">⛶</button>
                </div>
            </div>
            <div class="video-title-bar" id="titleBar">{title}</div>
            <script>
                const video = document.getElementById('yt-embed-video');
                const playBtn = document.getElementById('playBtn');
                const playPauseIcon = document.getElementById('playPauseIcon');
                const controlsBar = document.getElementById('controlsBar');
                const progressBarBg = document.getElementById('progressBarBg');
                const progressBarFill = document.getElementById('progressBarFill');
                const progressBarKnob = document.getElementById('progressBarKnob');
                const timeLabel = document.getElementById('timeLabel');
                const titleBar = document.getElementById('titleBar');
                let hideUITimeout = null;
                const TOTAL_DURATION = {duration_seconds};
                function formatTime(sec) {{
                    if (isNaN(sec) || sec === Infinity) return '0:00';
                    sec = Math.floor(sec);
                    const m = Math.floor(sec / 60);
                    const s = sec % 60;
                    return `${{m}}:${{s.toString().padStart(2, '0')}}`;
                }}
                function updatePlayIcon() {{
                    if (video.paused) {{
                        playPauseIcon.src = 'https://cdn-icons-png.flaticon.com/512/9974/9974136.png';
                        playPauseIcon.alt = 'play';
                    }} else {{
                        playPauseIcon.src = 'https://cdn-icons-png.flaticon.com/512/13077/13077337.png';
                        playPauseIcon.alt = 'pause';
                    }}
                }}
                function updateTime() {{
                    timeLabel.textContent = `${{formatTime(video.currentTime)}} / ${{formatTime(TOTAL_DURATION)}}`;
                }}
                function updateProgress() {{
                    const percent = TOTAL_DURATION ? (video.currentTime / TOTAL_DURATION) * 100 : 0;
                    progressBarFill.style.width = percent + '%';
                    progressBarKnob.style.left = percent + '%';
                }}
                playBtn.addEventListener('click', () => {{
                    if (video.paused) video.play(); else video.pause();
                }});
                video.addEventListener('play', updatePlayIcon);
                video.addEventListener('pause', updatePlayIcon);
                video.addEventListener('timeupdate', () => {{
                    updateTime();
                    updateProgress();
                }});
                video.addEventListener('loadedmetadata', () => {{
                    updateTime();
                    updateProgress();
                }});
                // Seek
                progressBarBg.addEventListener('click', (e) => {{
                    const rect = progressBarBg.getBoundingClientRect();
                    const x = e.clientX - rect.left;
                    const percent = x / rect.width;
                    video.currentTime = percent * (TOTAL_DURATION || video.duration || 0);
                }});
                // Drag seek
                let isSeeking = false;
                progressBarBg.addEventListener('mousedown', (e) => {{
                    isSeeking = true;
                    seek(e);
                }});
                document.addEventListener('mousemove', (e) => {{
                    if (isSeeking) seek(e);
                }});
                document.addEventListener('mouseup', () => {{
                    isSeeking = false;
                }});
                function seek(e) {{
                    const rect = progressBarBg.getBoundingClientRect();
                    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
                    const percent = x / rect.width;
                    video.currentTime = percent * (TOTAL_DURATION || video.duration || 0);
                }}
                // Fullscreen
                const fullscreenBtn = document.getElementById('fullscreenBtn');
                fullscreenBtn.addEventListener('click', () => {{
                    if (!document.fullscreenElement) {{
                        document.documentElement.requestFullscreen();
                    }} else {{
                        document.exitFullscreen();
                    }}
                }});
                // Hide UI on inactivity
                function showUI() {{
                    controlsBar.classList.remove('hide');
                    titleBar.classList.remove('hide');
                    clearTimeout(hideUITimeout);
                    if (!video.paused) {{
                        hideUITimeout = setTimeout(hideUI, 2000);
                    }}
                }}
                function hideUI() {{
                    controlsBar.classList.add('hide');
                    titleBar.classList.add('hide');
                }}
                document.addEventListener('mousemove', showUI);
                document.addEventListener('keydown', showUI);
                video.addEventListener('play', () => {{
                    showUI();
                }});
                video.addEventListener('pause', () => {{
                    showUI();
                }});
                // Play/pause on click outside controls and title bar
                const playerWrapper = document.querySelector('.player-wrapper');
                playerWrapper.addEventListener('click', function(e) {{
                    if (
                        !e.target.closest('.custom-controls') &&
                        !e.target.closest('.video-title-bar')
                    ) {{
                        if (video.paused) video.play(); else video.pause();
                    }}
                }});
                // Prevent context menu on right click
                video.addEventListener('contextmenu', e => e.preventDefault());
                // Init
                updatePlayIcon();
                updateTime();
                updateProgress();
            </script>
        </body>
        </html>
        '''.format(
            title=video_info['title'],
            video_url=video_info['video_url'],
            video_id=video_info['video_id']
        )
    except Exception as e:
        print('Error in /embed:', e)
        return '<h2>Ошибка загрузки видео</h2>', 500

@app.route('/get-ytvideo-info.php', methods=['GET'])
def get_ytvideo_info():
    try:
        video_id = request.args.get('video_id')
        quality = request.args.get('quality', config['default_quality'])
        apikey = request.args.get('apikey', config['api_key'])
        # Новый параметр proxy
        proxy_param = request.args.get('proxy', 'true').lower()
        use_video_proxy = proxy_param != 'false'
        if not video_id:
            return jsonify({'error': 'ID видео не был передан.'})
        resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={apikey}&part=snippet,contentDetails,statistics", timeout=config['request_timeout'])
        resp.raise_for_status()
        data = resp.json()
        videoData = data['items'][0] if data.get('items') and data['items'] else None
        if not videoData:
            return jsonify({'error': 'Видео не найдено.'})
        videoInfo = videoData['snippet']
        contentDetails = videoData['contentDetails']
        statistics = videoData['statistics']
        channelId = videoInfo['channelId']
        channelThumbnail = get_channel_thumbnail(channelId, apikey)
        # Получение прямой ссылки на видео
        finalVideoUrl = ''
        if not use_video_proxy:
            # Получаем реальную прямую ссылку через yt_dlp
            finalVideoUrlWithProxy = get_real_direct_video_url(video_id)
        else:
            if config['video_source'] == 'direct':
                # Используем локальный endpoint direct_url
                finalVideoUrl = f"{config['mainurl']}direct_url?video_id={video_id}"
                finalVideoUrlWithProxy = finalVideoUrl
            else:
                finalVideoUrl = get_direct_video_url(video_id) if config['video_source'] == 'direct' else ''
                finalVideoUrlWithProxy = finalVideoUrl
                if config['use_video_proxy'] and finalVideoUrl:
                    finalVideoUrlWithProxy = f"{config['mainurl']}video.proxy?url={quote(finalVideoUrl)}"
        # Комментарии
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
            'description': videoInfo['description'],
            'video_id': video_id,
            'embed_url': f"https://www.youtube.com/embed/{video_id}",
            'duration': contentDetails['duration'],
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
            mark_stream_start()
            try:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            finally:
                mark_stream_end()
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
    app.run(host='0.0.0.0', port=2823)