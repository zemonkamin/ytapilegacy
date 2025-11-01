from flask import Blueprint, request, jsonify, Response
import json
import requests
import subprocess
import threading
import os
import re
from urllib.parse import quote
from datetime import datetime
from utils.video_processing import get_direct_video_url, get_real_direct_video_url, get_video_url, get_video_info_ytdlp
from utils.helpers import run_yt_dlp, get_channel_thumbnail, get_proxy_url, get_video_proxy_url, get_cookies_files, select_random_cookie_file, get_api_key, get_api_key_rotated
from utils.video_cache import (
    get_cache_path, is_video_cached, get_cached_video_size, should_cache_video,
    increment_video_view_count, check_and_cleanup_cache
)

# Create blueprint
video_bp = Blueprint('video', __name__)

# Dictionary to track ongoing downloads
ongoing_downloads = {}
download_lock = threading.Lock()

def setup_video_routes(config):
    """Configure video routes with application config"""
    
    @video_bp.route('/get-ytvideo-info.php', methods=['GET'])
    def get_ytvideo_info():
        try:
            video_id = request.args.get('video_id')
            quality = request.args.get('quality', config['default_quality'])
            apikey = get_api_key_rotated(config)
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
            
            # Initialize variables with default values
            subscriberCount = "0"
            
            r = requests.get(
                f"https://www.googleapis.com/youtube/v3/channels?id={channelId}&key={apikey}&part=snippet,statistics", 
                timeout=config['request_timeout']
            )
            r.raise_for_status()
            data = r.json()
            
            print(f"DEBUG: API response: {json.dumps(data, ensure_ascii=False)[:200]}...")
            
            if data.get('items') and data['items']:
                # Get subscriber count from channel data
                subscriberCount = data['items'][0]['statistics'].get('subscriberCount', '0')
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
                    commentAuthorThumbnail = get_channel_thumbnail(commentAuthorId, apikey, config)
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
                'channel_thumbnail': f"{config['mainurl']}channel_icon/{video_id}",
                'thumbnail': f"{config['mainurl']}thumbnail/{video_id}",
                'video_url': finalVideoUrlWithProxy
            }
            
            return jsonify(result)
            
        except Exception as e:
            print('Error in get-ytvideo-info:', e)
            return jsonify({'error': 'Internal server error'})

    @video_bp.route('/direct_url', methods=['GET', 'HEAD'])
    def direct_url():
        try:
            video_id = request.args.get('video_id')
            quality = request.args.get('quality')
            
            if not video_id:
                response = jsonify({'error': 'ID видео не был передан.'})
                response.status_code = 400
                response.headers['Content-Length'] = str(len(response.get_data()))
                return response

            # Increment view count for this video
            if video_id:
                increment_video_view_count(video_id)

            # Check if video is already cached with the specific quality
            if is_video_cached(video_id, quality):
                # Serve from cache
                cache_path = get_cache_path(video_id, quality)
                file_size = os.path.getsize(cache_path)
                
                if request.method == 'HEAD':
                    response = Response(None, mimetype='video/mp4')
                    response.headers['Accept-Ranges'] = 'bytes'
                    response.headers['Content-Type'] = 'video/mp4'
                    response.headers['Content-Length'] = str(file_size)
                    return response
                
                # Handle range requests for partial content
                range_header = request.headers.get('Range', None)
                if range_header:
                    byte1, byte2 = 0, None
                    match = re.search(r'(\d+)-(\d*)', range_header)
                    if match:
                        byte1 = int(match.group(1))
                        if match.group(2):
                            byte2 = int(match.group(2))
                    
                    with open(cache_path, 'rb') as f:
                        f.seek(0, 2)  # Seek to end
                        file_length = f.tell()
                        
                    if byte2 is None:
                        byte2 = file_length - 1
                        
                    chunk_size = byte2 - byte1 + 1
                    
                    def generate_range():
                        with open(cache_path, 'rb') as f:
                            f.seek(byte1)
                            remaining = chunk_size
                            while remaining > 0:
                                chunk = f.read(min(65536, remaining))
                                if not chunk:
                                    break
                                yield chunk
                                remaining -= len(chunk)
                    
                    response = Response(generate_range(), 206, mimetype='video/mp4')
                    response.headers['Content-Range'] = f'bytes {byte1}-{byte2}/{file_length}'
                    response.headers['Accept-Ranges'] = 'bytes'
                    response.headers['Content-Length'] = str(chunk_size)
                    response.headers['Content-Type'] = 'video/mp4'
                    return response
                else:
                    # Full file streaming
                    def generate_full():
                        with open(cache_path, 'rb') as f:
                            while True:
                                chunk = f.read(65536)
                                if not chunk:
                                    break
                                yield chunk
                    
                    response = Response(generate_full(), mimetype='video/mp4')
                    response.headers['Accept-Ranges'] = 'bytes'
                    response.headers['Content-Length'] = str(file_size)
                    response.headers['Content-Type'] = 'video/mp4'
                    return response

            # Получаем информацию о длительности видео
            duration_value = None
            try:
                url = f'https://www.youtube.com/watch?v={video_id}'
                info_output = run_yt_dlp(['--dump-json', '--no-warnings', url])
                
                if info_output:
                    try:
                        info = json.loads(info_output)
                        duration_value = info.get('duration')
                    except json.JSONDecodeError as e:
                        print(f"Error parsing JSON for duration: {e}")
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
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['Content-Type'] = 'video/mp4'
                return response

            # Create a unique key for this download
            download_key = f"{video_id}_{quality}" if quality else video_id
            
            # Check if download is already in progress
            with download_lock:
                if download_key in ongoing_downloads:
                    # Download is in progress, proxy the original URL while it completes
                    video_url, audio_url = get_video_url(video_id, quality or 'standard')
                    if video_url:
                        # Proxy the original URL directly
                        headers = {
                            'Range': request.headers.get('Range', 'bytes=0-'),
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
                        
                        def generate():
                            try:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        yield chunk
                            finally:
                                pass
                        
                        response = Response(generate(), status=resp.status_code, mimetype='video/mp4')
                        response.headers['Accept-Ranges'] = 'bytes'
                        response.headers['Content-Type'] = 'video/mp4'
                        if 'content-range' in resp.headers:
                            response.headers['Content-Range'] = resp.headers['content-range']
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
                        return response
                    else:
                        # If we can't get the URL, wait for the download to complete
                        pass
                else:
                    # Mark download as in progress
                    ongoing_downloads[download_key] = True

            try:
                # Check if we should cache this video (based on frequency)
                # For testing purposes, we'll cache every video
                should_cache = True  # should_cache_video(video_id)
                cache_path = None
                if should_cache and video_id:
                    cache_path = get_cache_path(video_id, quality)
                    print(f"Caching video {video_id} at {cache_path}")

                # Получаем URL видео и аудио для указанного качества
                # If quality is not specified, we use standard quality
                if quality is not None:
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

                        # Используем качество по умолчанию из конфигурации, если не указано
                        if not quality:
                            quality = config.get('default_quality', '360')
                        
                        desired_height = parse_desired_height(quality)
                        
                        # Преобразуем высоту в строку для функции get_video_url
                        if desired_height:
                            quality_str = str(desired_height)
                        else:
                            quality_str = 'standard'
                        
                        # Получаем URL видео и аудио
                        video_url, audio_url = get_video_url(video_id, quality_str)
                        
                        # Если не удалось получить URL, пробуем с другим cookie файлом
                        if not video_url and not audio_url:
                            # Попробуем все доступные cookie файлы
                            cookies_files = get_cookies_files()
                            for cookie_file in cookies_files:
                                video_url, audio_url = get_video_url(video_id, quality_str, cookie_file)
                                if video_url or audio_url:
                                    break
                        
                        # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                        if video_url and audio_url:
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
                                    if ffmpeg_process and ffmpeg_process.stderr:
                                        while True:
                                            line = ffmpeg_process.stderr.readline()
                                            if not line:
                                                break
                                except Exception:
                                    pass
                            try:
                                threading.Thread(target=_drain_stderr, daemon=True).start()
                            except Exception as e:
                                print(f"Error starting stderr drain thread: {e}")

                            def generate_and_cache_ffmpeg():
                                try:
                                    if cache_path:
                                        # Ensure directory exists
                                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                        with open(cache_path, 'wb') as cache_file:
                                            if ffmpeg_process and ffmpeg_process.stdout:
                                                while True:
                                                    chunk = ffmpeg_process.stdout.read(65536)
                                                    if not chunk:
                                                        break
                                                    cache_file.write(chunk)
                                                    yield chunk
                                    else:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    break
                                                yield chunk
                                except Exception as e:
                                    print(f"Error in generate_and_cache_ffmpeg: {e}")
                                finally:
                                    try:
                                        if ffmpeg_process:
                                            ffmpeg_process.terminate()
                                    except Exception:
                                        pass

                            response = Response(generate_and_cache_ffmpeg(), mimetype='video/mp4')
                            response.headers['Content-Type'] = 'video/mp4'
                            if duration_value:
                                duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                                response.headers['X-Content-Duration'] = duration_str
                                response.headers['Content-Duration'] = duration_str
                                response.headers['X-Video-Duration'] = duration_str
                                response.headers['X-Duration-Seconds'] = duration_str
                            
                            # Check and cleanup cache if needed
                            check_and_cleanup_cache(
                                config.get('temp_folder_max_size_mb', 5120),
                                config.get('cache_cleanup_threshold_mb', 100)
                            )
                            
                            return response
                        # Если получили комбинированный поток (только video_url, audio_url = None)
                        elif video_url and not audio_url:
                            # For combined streams, we can directly proxy without FFmpeg processing
                            headers = {
                                'Range': request.headers.get('Range', 'bytes=0-'),
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            }
                            resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
                            
                            def generate_and_cache_combined():
                                try:
                                    if cache_path:
                                        # Ensure directory exists
                                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                        with open(cache_path, 'wb') as cache_file:
                                            for chunk in resp.iter_content(chunk_size=8192):
                                                if chunk:
                                                    cache_file.write(chunk)
                                                    yield chunk
                                    else:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                yield chunk
                                finally:
                                    pass
                            
                            response = Response(generate_and_cache_combined() if cache_path else resp.iter_content(chunk_size=8192), status=resp.status_code, mimetype='video/mp4')
                            response.headers['Accept-Ranges'] = 'bytes'
                            response.headers['Content-Type'] = 'video/mp4'
                            if 'content-range' in resp.headers:
                                response.headers['Content-Range'] = resp.headers['content-range']
                            if duration_value:
                                duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                                response.headers['X-Content-Duration'] = duration_str
                                response.headers['Content-Duration'] = duration_str
                                response.headers['X-Video-Duration'] = duration_str
                                response.headers['X-Duration-Seconds'] = duration_str
                            
                            # Check and cleanup cache if needed
                            check_and_cleanup_cache(
                                config.get('temp_folder_max_size_mb', 5120),
                                config.get('cache_cleanup_threshold_mb', 100)
                            )
                            
                            return response
                        
                        # Если не удалось получить URL
                        else:
                            response = jsonify({'error': 'Не удалось получить ссылки на потоки.'})
                            response.status_code = 500
                            response.headers['Content-Length'] = str(len(response.get_data()))
                            return response

                    except Exception as e:
                        print(f'Error in direct_url (new approach): {e}')
                        response = jsonify({'error': f'Internal server error: {str(e)}'})
                        response.status_code = 500
                        response.headers['Content-Length'] = str(len(response.get_data()))
                        return response
                else:
                    # Fallback: прямой прокси без FFmpeg для стандартного качества
                    video_url, audio_url = get_video_url(video_id, 'standard')
                    
                    # Если не удалось получить URL, пробуем с другим cookie файлом
                    if not video_url and not audio_url:
                        # Попробуем все доступные cookie файлы
                        cookies_files = get_cookies_files()
                        for cookie_file in cookies_files:
                            video_url, audio_url = get_video_url(video_id, 'standard', cookie_file)
                            if video_url or audio_url:
                                break
                    
                    # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                    if video_url and audio_url:
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

                        def _drain_stderr_fallback():
                            try:
                                if ffmpeg_process and ffmpeg_process.stderr:
                                    while True:
                                        line = ffmpeg_process.stderr.readline()
                                        if not line:
                                            break
                            except Exception:
                                pass
                        try:
                            threading.Thread(target=_drain_stderr_fallback, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate_and_cache_ffmpeg_fallback():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    break
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    if ffmpeg_process and ffmpeg_process.stdout:
                                        while True:
                                            chunk = ffmpeg_process.stdout.read(65536)
                                            if not chunk:
                                                break
                                            yield chunk
                            except Exception as e:
                                print(f"Error in generate_and_cache_ffmpeg_fallback: {e}")
                            finally:
                                try:
                                    if ffmpeg_process:
                                        ffmpeg_process.terminate()
                                except Exception:
                                    pass

                        response = Response(generate_and_cache_ffmpeg_fallback(), mimetype='video/mp4')
                        response.headers['Content-Type'] = 'video/mp4'
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                    # Если получили комбинированный поток (только video_url, audio_url = None)
                    elif video_url and not audio_url:
                        # For combined streams, we can directly proxy without FFmpeg processing
                        headers = {
                            'Range': request.headers.get('Range', 'bytes=0-'),
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
                        
                        def generate_and_cache_combined_fallback():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    for chunk in resp.iter_content(chunk_size=8192):
                                        if chunk:
                                            yield chunk
                            finally:
                                pass
                        
                        response = Response(generate_and_cache_combined_fallback() if cache_path else resp.iter_content(chunk_size=8192), status=resp.status_code, mimetype='video/mp4')
                        response.headers['Accept-Ranges'] = 'bytes'
                        response.headers['Content-Type'] = 'video/mp4'
                        if 'content-range' in resp.headers:
                            response.headers['Content-Range'] = resp.headers['content-range']
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                    
                    # Если не удалось получить URL
                    else:
                        response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
                        response.status_code = 500
                        response.headers['Content-Length'] = str(len(response.get_data()))
                        return response

            finally:
                # Mark download as completed
                with download_lock:
                    if download_key in ongoing_downloads:
                        del ongoing_downloads[download_key]

        except Exception as e:
            # Clean up download tracking in case of error
            download_key = f"{request.args.get('video_id')}_{request.args.get('quality')}" if request.args.get('quality') else request.args.get('video_id')
            with download_lock:
                if download_key in ongoing_downloads:
                    del ongoing_downloads[download_key]
            
            print(f'Error in direct_url: {e}')
            response = jsonify({'error': f'Internal server error: {str(e)}'})
            response.status_code = 500
            response.headers['Content-Length'] = str(len(response.get_data()))
            return response

    @video_bp.route('/download', methods=['GET'])
    def download_video():
        try:
            video_id = request.args.get('video_id')
            quality = request.args.get('quality')
            
            if not video_id:
                return jsonify({'error': 'ID видео не был передан.'}), 400

            # Increment view count for this video
            if video_id:
                increment_video_view_count(video_id)

            # Check if video is already cached with the specific quality
            if is_video_cached(video_id, quality):
                # Serve from cache for download
                cache_path = get_cache_path(video_id, quality)
                file_size = os.path.getsize(cache_path)
                
                # Получаем информацию о видео для названия файла
                video_title = "video"
                try:
                    # Получаем информацию о видео в формате JSON
                    url = f'https://www.youtube.com/watch?v={video_id}'
                    info_output = run_yt_dlp(['--dump-json', '--no-warnings', url])
                    
                    if info_output:
                        info = json.loads(info_output)
                        video_title = info.get('title', 'video')
                        # Очищаем название файла от недопустимых символов
                        video_title = re.sub(r'[<>:"/\\|?*]', '_', video_title)
                except Exception as e:
                    print(f"Error fetching video info for video_id {video_id}: {e}")
                
                def generate_from_cache():
                    with open(cache_path, 'rb') as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            yield chunk
                
                response = Response(generate_from_cache(), mimetype='video/mp4')
                response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                response.headers['Content-Length'] = str(file_size)
                return response

            # Получаем информацию о видео для названия файла
            video_title = "video"
            try:
                # Получаем информацию о видео в формате JSON
                url = f'https://www.youtube.com/watch?v={video_id}'
                info_output = run_yt_dlp(['--dump-json', '--no-warnings', url])
                
                if info_output:
                    info = json.loads(info_output)
                    video_title = info.get('title', 'video')
                    # Очищаем название файла от недопустимых символов
                    video_title = re.sub(r'[<>:"/\\|?*]', '_', video_title)
            except Exception as e:
                print(f"Error fetching video info for video_id {video_id}: {e}")

            # Check if we should cache this video (based on frequency)
            # For testing purposes, we'll cache every video
            should_cache = True  # should_cache_video(video_id)
            cache_path = None
            if should_cache and video_id:
                cache_path = get_cache_path(video_id, quality)
                print(f"Caching video {video_id} at {cache_path} for download")

            # Create a unique key for this download
            download_key = f"{video_id}_{quality}" if quality else video_id
            
            # Check if download is already in progress
            with download_lock:
                if download_key in ongoing_downloads:
                    return jsonify({'error': 'Download already in progress'}), 409
                else:
                    # Mark download as in progress
                    ongoing_downloads[download_key] = True

            try:
                # Получаем URL видео и аудио для указанного качества
                # If quality is not specified, we use standard quality
                if quality is not None:
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

                        # Используем качество по умолчанию из конфигурации, если не указано
                        if not quality:
                            quality = config.get('default_quality', '360')
                        
                        desired_height = parse_desired_height(quality)
                        
                        # Преобразуем высоту в строку для функции get_video_url
                        if desired_height:
                            quality_str = str(desired_height)
                        else:
                            quality_str = 'standard'
                        
                        # Получаем URL видео и аудио
                        video_url, audio_url = get_video_url(video_id, quality_str)
                        
                        # Если не удалось получить URL, пробуем с другим cookie файлом
                        if not video_url and not audio_url:
                            # Попробуем все доступные cookie файлы
                            cookies_files = get_cookies_files()
                            for cookie_file in cookies_files:
                                video_url, audio_url = get_video_url(video_id, quality_str, cookie_file)
                                if video_url or audio_url:
                                    break
                        
                        # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                        if video_url and audio_url:
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
                                    if ffmpeg_process and ffmpeg_process.stderr:
                                        while True:
                                            line = ffmpeg_process.stderr.readline()
                                            if not line:
                                                break
                                except Exception:
                                    pass
                            try:
                                threading.Thread(target=_drain_stderr, daemon=True).start()
                            except Exception as e:
                                print(f"Error starting stderr drain thread: {e}")

                            def generate_and_cache_ffmpeg_download():
                                try:
                                    if cache_path:
                                        # Ensure directory exists
                                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                        with open(cache_path, 'wb') as cache_file:
                                            if ffmpeg_process and ffmpeg_process.stdout:
                                                while True:
                                                    chunk = ffmpeg_process.stdout.read(65536)
                                                    if not chunk:
                                                        break
                                                    cache_file.write(chunk)
                                                    yield chunk
                                    else:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    break
                                                yield chunk
                                except Exception as e:
                                    print(f"Error in generate_and_cache_ffmpeg_download: {e}")
                                finally:
                                    try:
                                        if ffmpeg_process:
                                            ffmpeg_process.terminate()
                                    except Exception:
                                        pass

                            response = Response(generate_and_cache_ffmpeg_download(), mimetype='video/mp4')
                            response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                            
                            # Check and cleanup cache if needed
                            check_and_cleanup_cache(
                                config.get('temp_folder_max_size_mb', 5120),
                                config.get('cache_cleanup_threshold_mb', 100)
                            )
                            
                            return response
                        # Если получили комбинированный поток (только video_url, audio_url = None)
                        elif video_url and not audio_url:
                            # For combined streams, we can directly proxy without FFmpeg processing
                            headers = {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            }
                            resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
                            
                            def generate_and_cache_combined_download():
                                try:
                                    if cache_path:
                                        # Ensure directory exists
                                        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                        with open(cache_path, 'wb') as cache_file:
                                            for chunk in resp.iter_content(chunk_size=8192):
                                                if chunk:
                                                    cache_file.write(chunk)
                                                    yield chunk
                                    else:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                yield chunk
                                finally:
                                    pass
                            
                            response = Response(generate_and_cache_combined_download() if cache_path else resp.iter_content(chunk_size=8192), mimetype='video/mp4')
                            response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                            
                            # Check and cleanup cache if needed
                            check_and_cleanup_cache(
                                config.get('temp_folder_max_size_mb', 5120),
                                config.get('cache_cleanup_threshold_mb', 100)
                            )
                            
                            return response
                        
                        # Если не удалось получить URL
                        else:
                            response = jsonify({'error': 'Не удалось получить ссылки на потоки.'})
                            response.status_code = 500
                            return response

                    except Exception as e:
                        print(f'Error in download (new approach): {e}')
                        return jsonify({'error': f'Internal server error: {str(e)}'}), 500
                else:
                    # Fallback: прямой прокси без FFmpeg для стандартного качества
                    video_url, audio_url = get_video_url(video_id, 'standard')
                
                    # Если не удалось получить URL, пробуем с другим cookie файлом
                    if not video_url and not audio_url:
                        # Попробуем все доступные cookie файлы
                        cookies_files = get_cookies_files()
                        for cookie_file in cookies_files:
                            video_url, audio_url = get_video_url(video_id, 'standard', cookie_file)
                            if video_url or audio_url:
                                break
                    
                    # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                    if video_url and audio_url:
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

                        def _drain_stderr_fallback():
                            try:
                                if ffmpeg_process and ffmpeg_process.stderr:
                                    while True:
                                        line = ffmpeg_process.stderr.readline()
                                        if not line:
                                            break
                            except Exception:
                                pass
                        try:
                            threading.Thread(target=_drain_stderr_fallback, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate_and_cache_ffmpeg_download_fallback():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    break
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    if ffmpeg_process and ffmpeg_process.stdout:
                                        while True:
                                            chunk = ffmpeg_process.stdout.read(65536)
                                            if not chunk:
                                                break
                                            yield chunk
                            except Exception as e:
                                print(f"Error in generate_and_cache_ffmpeg_download_fallback: {e}")
                            finally:
                                try:
                                    if ffmpeg_process:
                                        ffmpeg_process.terminate()
                                except Exception:
                                    pass

                        response = Response(generate_and_cache_ffmpeg_download_fallback(), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                    # Если получили комбинированный поток (только video_url, audio_url = None)
                    elif video_url and not audio_url:
                        # For combined streams, we can directly proxy without FFmpeg processing
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        resp = requests.get(video_url, headers=headers, stream=True, timeout=config['request_timeout'])
                        
                        def generate_and_cache_combined_download_fallback():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        for chunk in resp.iter_content(chunk_size=8192):
                                            if chunk:
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    for chunk in resp.iter_content(chunk_size=8192):
                                        if chunk:
                                            yield chunk
                            finally:
                                pass
                        
                        response = Response(generate_and_cache_combined_download_fallback() if cache_path else resp.iter_content(chunk_size=8192), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                
                # Если не удалось получить URL
                response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
                response.status_code = 500
                return response

            finally:
                # Mark download as completed
                with download_lock:
                    if download_key in ongoing_downloads:
                        del ongoing_downloads[download_key]

        except Exception as e:
            # Clean up download tracking in case of error
            download_key = f"{request.args.get('video_id')}_{request.args.get('quality')}" if request.args.get('quality') else request.args.get('video_id')
            with download_lock:
                if download_key in ongoing_downloads:
                    del ongoing_downloads[download_key]
            
            print('Error in download:', e)
            return jsonify({'error': 'Internal server error'}), 500

    @video_bp.route('/thumbnail/<video_id>')
    def thumbnail_proxy(video_id):
        try:
            # Get quality parameter, default to 'medium' if not provided
            quality = request.args.get('quality', 'medium')
            
            # Map quality parameters to thumbnail URLs
            quality_map = {
                'default': 'default.jpg',
                'medium': 'mqdefault.jpg',
                'high': 'hqdefault.jpg',
                'standard': 'sddefault.jpg',
                'maxres': 'maxresdefault.jpg'
            }
            
            # Use medium as default if quality parameter is invalid
            thumbnail_type = quality_map.get(quality, 'mqdefault.jpg')
            url = f'https://i.ytimg.com/vi/{video_id}/{thumbnail_type}'
            
            resp = requests.get(url, stream=True, timeout=10)
            
            # If the requested thumbnail is not found, fallback to medium quality
            if resp.status_code == 404 and thumbnail_type != 'mqdefault.jpg':
                fallback_url = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'
                resp = requests.get(fallback_url, stream=True, timeout=10)
            
            return Response(resp.content, mimetype=resp.headers.get('Content-Type', 'image/jpeg'))
        except Exception as e:
            print('Error in /thumbnail:', e)
            return '', 404

    @video_bp.route('/channel_icon/<path:video_id>')
    def channel_icon(video_id):
        try:
            # Check if video_id is already a direct image URL (starts with http or https)
            if video_id.startswith('http://') or video_id.startswith('https://'):
                # Proxy the image directly
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                # Proxy the image
                try:
                    image_resp = requests.get(video_id, timeout=30, headers=headers)
                    image_resp.raise_for_status()
                    
                    return Response(
                        image_resp.content,
                        mimetype=image_resp.headers.get('content-type', 'image/jpeg'),
                        headers={'Cache-Control': 'public, max-age=3600'}  # Cache for 1 hour
                    )
                except requests.exceptions.SSLError as ssl_error:
                    print(f'SSL Error fetching image: {ssl_error}')
                    # Try again without SSL verification as a fallback
                    image_resp = requests.get(video_id, timeout=30, headers=headers, verify=False)
                    image_resp.raise_for_status()
                    
                    return Response(
                        image_resp.content,
                        mimetype=image_resp.headers.get('content-type', 'image/jpeg'),
                        headers={'Cache-Control': 'public, max-age=3600'}  # Cache for 1 hour
                    )
                except Exception as e:
                    print(f'Error fetching direct image: {e}')
                    return jsonify({'error': 'Failed to fetch direct image'}), 500
            else:
                # Handle as YouTube channel ID
                # Get API key from config or request parameters
                apikey = get_api_key_rotated(config)
                # Get quality parameter, default to 'default' if not provided
                # This ensures that when no quality is specified, we use 'default' quality (not 'high')
                quality = request.args.get('quality', 'default')
                
                # API key is now optional since we can use keys from config
                # But we still need to check if we have a key to use
                if not apikey:
                    return jsonify({'error': 'API key is required'}), 400
                
                # Check if the provided ID is a channel ID (starts with UC) or video ID
                if video_id.startswith('UC'):
                    # It's a channel ID, use it directly
                    channel_id = video_id
                elif video_id.startswith('@'):
                    # It's a channel username (starts with @), search for the channel
                    username = video_id[1:]  # Remove the @ prefix
                    search_url = f"https://www.googleapis.com/youtube/v3/channels?forUsername={username}&key={apikey}&part=id"
                    search_resp = requests.get(search_url, timeout=config['request_timeout'])
                    
                    # Check if the response is successful
                    if search_resp.status_code != 200:
                        error_msg = f"Failed to search channel by username: {search_resp.status_code}"
                        if search_resp.text:
                            error_msg += f" - {search_resp.text}"
                        print(error_msg)
                        return jsonify({'error': 'Failed to search channel by username'}), 500
                    
                    search_data = search_resp.json()
                    
                    if not search_data.get('items'):
                        # Try searching by custom URL instead
                        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={username}&type=channel&key={apikey}"
                        search_resp = requests.get(search_url, timeout=config['request_timeout'])
                        
                        if search_resp.status_code != 200:
                            error_msg = f"Failed to search channel by name: {search_resp.status_code}"
                            if search_resp.text:
                                error_msg += f" - {search_resp.text}"
                            print(error_msg)
                            return jsonify({'error': 'Failed to search channel by name'}), 500
                        
                        search_data = search_resp.json()
                        
                        if not search_data.get('items'):
                            return jsonify({'error': 'Channel not found'}), 404
                        
                        # Extract channel ID from search results (search API format)
                        if search_data.get('items') and len(search_data['items']) > 0:
                            channel_id = search_data['items'][0]['snippet']['channelId']
                        else:
                            return jsonify({'error': 'Channel not found'}), 404
                    else:
                        # Extract channel ID from channels API results
                        if search_data.get('items') and len(search_data['items']) > 0:
                            channel_id = search_data['items'][0]['id']
                        else:
                            return jsonify({'error': 'Channel not found'}), 404
                else:
                    # It's a video ID, get the channel ID from video information
                    video_url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={apikey}&part=snippet"
                    video_resp = requests.get(video_url, timeout=config['request_timeout'])
                    
                    # Check if the response is successful
                    if video_resp.status_code != 200:
                        error_msg = f"Failed to fetch video info: {video_resp.status_code}"
                        if video_resp.text:
                            error_msg += f" - {video_resp.text}"
                        print(error_msg)
                        return jsonify({'error': 'Failed to fetch video information'}), 500
                    
                    video_data = video_resp.json()
                    
                    if not video_data.get('items'):
                        return jsonify({'error': 'Video not found'}), 404
                    
                    # Extract channel ID from video data
                    channel_id = video_data['items'][0]['snippet']['channelId']
                
                # Get channel information to retrieve thumbnail
                channel_url = f"https://www.googleapis.com/youtube/v3/channels?id={channel_id}&key={apikey}&part=snippet"
                channel_resp = requests.get(channel_url, timeout=config['request_timeout'])
                
                # Check if the response is successful
                if channel_resp.status_code != 200:
                    error_msg = f"Failed to fetch channel info: {channel_resp.status_code}"
                    if channel_resp.text:
                        error_msg += f" - {channel_resp.text}"
                    print(error_msg)
                    return jsonify({'error': 'Failed to fetch channel information'}), 500
                
                channel_data = channel_resp.json()
                
                if not channel_data.get('items'):
                    return jsonify({'error': 'Channel not found'}), 404
                
                # Extract thumbnail URL based on quality parameter
                thumbnails = channel_data['items'][0]['snippet']['thumbnails']
                
                # Map quality parameters to thumbnail URLs
                quality_map = {
                    'default': 'default',
                    'medium': 'medium',
                    'high': 'high'
                }
                
                # Use the requested quality, or 'default' if not provided/invalid
                thumbnail_quality = quality_map.get(quality, 'default')
                
                # Check if the requested quality is available, if not fall back in order
                # When no quality is specified, we prefer 'default' over 'high' as the first fallback
                if thumbnail_quality not in thumbnails:
                    # Try in order: requested quality -> default -> medium -> high
                    fallback_order = [thumbnail_quality, 'default', 'medium', 'high']
                    for q in fallback_order:
                        if q in thumbnails:
                            thumbnail_quality = q
                            break
                    else:
                        # If none of the fallback options are available, use any available thumbnail
                        if thumbnails:
                            thumbnail_quality = list(thumbnails.keys())[0]
                        else:
                            return jsonify({'error': 'Channel thumbnail not available'}), 404
                
                thumbnail_url = thumbnails[thumbnail_quality]['url']
                
                # Replace yt3.ggpht.com with yt3.googleusercontent.com to avoid SSL issues
                # As per project memory, googleusercontent.com is more reliable
                if 'yt3.ggpht.com' in thumbnail_url:
                    thumbnail_url = thumbnail_url.replace('yt3.ggpht.com', 'yt3.googleusercontent.com')
                
                # Add headers to mimic a browser request
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                # Proxy the thumbnail image
                try:
                    thumbnail_resp = requests.get(thumbnail_url, timeout=30, headers=headers)
                    thumbnail_resp.raise_for_status()
                    
                    return Response(
                        thumbnail_resp.content,
                        mimetype=thumbnail_resp.headers.get('content-type', 'image/jpeg'),
                        headers={'Cache-Control': 'public, max-age=3600'}  # Cache for 1 hour
                    )
                except requests.exceptions.SSLError as ssl_error:
                    print(f'SSL Error fetching thumbnail: {ssl_error}')
                    # Try again without SSL verification as a fallback
                    thumbnail_resp = requests.get(thumbnail_url, timeout=30, headers=headers, verify=False)
                    thumbnail_resp.raise_for_status()
                    
                    return Response(
                        thumbnail_resp.content,
                        mimetype=thumbnail_resp.headers.get('content-type', 'image/jpeg'),
                        headers={'Cache-Control': 'public, max-age=3600'}  # Cache for 1 hour
                    )
        except requests.exceptions.RequestException as e:
            print(f'Error fetching channel icon: {e}')
            return jsonify({'error': f'Failed to fetch channel icon: {str(e)}'}), 500
        except Exception as e:
            print(f'Error in channel_icon: {e}')
            return jsonify({'error': 'Internal server error'}), 500

    @video_bp.route('/video.proxy', methods=['GET'])
    def video_proxy():
        try:
            url = request.args.get('url')
            if not url:
                return jsonify({'error': 'URL parameter is required'}), 400
            try:
                from urllib.parse import urlparse
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