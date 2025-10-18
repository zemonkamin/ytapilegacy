from flask import Blueprint, request, jsonify, Response
import json
import requests
import subprocess
import threading
import re
from urllib.parse import quote
from datetime import datetime
from utils.video_processing import get_direct_video_url, get_real_direct_video_url, get_video_url
from utils.helpers import run_yt_dlp, get_channel_thumbnail, get_proxy_url, get_video_proxy_url
from utils.auth import refresh_access_token

# Create blueprint
additional_bp = Blueprint('additional', __name__)

def setup_additional_routes(config):
    """Configure additional routes with application config"""
    
    @additional_bp.route('/get-direct-video-url.php', methods=['GET'])
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

    @additional_bp.route('/direct_audio_url', methods=['GET', 'HEAD'])
    def direct_audio_url():
        try:
            video_id = request.args.get('video_id')
            
            if not video_id:
                return jsonify({'error': 'ID видео не был передан.'}), 400
            
            duration_value = None
            try:
                # Получаем информацию о видео в формате JSON
                url = f'https://www.youtube.com/watch?v={video_id}'
                info_output = run_yt_dlp(['--dump-json', '--no-warnings', url])
                
                if info_output:
                    info = json.loads(info_output)
                    duration_value = info.get('duration')
            except Exception as e:
                print(f"Error fetching duration for video_id {video_id}: {e}")

            try:
                # Получаем аудио поток
                # For simplicity, we'll use the video_processing functions
                formats = None  # We would need to implement get_available_formats here
                if not formats:
                    return jsonify({'error': 'Не удалось получить информацию о форматах.'}), 500

                # Находим аудио-формат (предпочитаем английскую дорожку)
                audio_formats = [
                    f for f in formats 
                    if f.get('vcodec') == 'none' and 
                    f.get('acodec') != 'none' and 
                    f.get('protocol', '').startswith('https') and 
                    '[en]' in f.get('format', '')
                ]
                if not audio_formats:
                    audio_formats = [
                        f for f in formats 
                        if f.get('vcodec') == 'none' and 
                        f.get('acodec') != 'none' and 
                        f.get('protocol', '').startswith('https')
                    ]

                if not audio_formats:
                    return jsonify({'error': 'Не удалось подобрать аудио поток.'}), 500

                # Выбираем лучший аудио формат
                best_audio = max(audio_formats, key=lambda f: f.get('tbr', 0))
                format_id = best_audio['format_id']
                print(f"[DEBUG] Выбран формат аудио: ID={format_id}, tbr={best_audio.get('tbr', 'N/A')}")
                
                # Получаем URL аудио
                url = f'https://www.youtube.com/watch?v={video_id}'
                audio_url = run_yt_dlp(['-f', format_id, '--get-url', url])
                
                if not audio_url:
                    return jsonify({'error': 'Не удалось получить ссылку на аудио поток.'}), 500

                # Proxy the audio stream
                headers = {
                    'Range': request.headers.get('Range', 'bytes=0-'),
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                resp = requests.get(audio_url, headers=headers, stream=True, timeout=config['request_timeout'])
                
                def generate():
                    try:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                yield chunk
                    finally:
                        pass
                
                response = Response(None if request.method == 'HEAD' else generate(), status=resp.status_code, mimetype='audio/m4a')
                response.headers['Content-Type'] = resp.headers.get('content-type', 'audio/m4a')
                response.headers['Content-Length'] = resp.headers.get('content-length', '')
                response.headers['Accept-Ranges'] = 'bytes'
                if request.method == 'HEAD':
                    response.headers['Content-Type'] = 'audio/m4a'
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

    @additional_bp.route('/get_recommendations.php', methods=['GET'])
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

    @additional_bp.route('/get_related_videos.php', methods=['GET'])
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
                channelThumbnail = get_channel_thumbnail(vinfo['channelId'], apikey, config)
                
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
                        recommendations = get_innertube_recommendations(access_token, count - len(relatedVideos), config)
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
                                        channel_thumb = get_channel_thumbnail(channel_id, apikey, config) if channel_id else ''
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

    @additional_bp.route('/get_history.php', methods=['GET'])
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
                json_data = fetch_history_page(access_token, continuation_token, config)
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

def get_innertube_recommendations(access_token, max_count, config):
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
            "key": config.get('api_key', "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"),
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

def fetch_history_page(access_token, continuation_token, config):
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