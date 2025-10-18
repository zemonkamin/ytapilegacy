from flask import Blueprint, request, jsonify, Response
import json
import requests
import subprocess
import threading
from urllib.parse import quote
from datetime import datetime
from utils.video_processing import get_direct_video_url, get_real_direct_video_url, get_video_url, get_video_info_ytdlp
from utils.helpers import run_yt_dlp, get_channel_thumbnail, get_proxy_url, get_video_proxy_url, get_cookies_files, select_random_cookie_file

# Create blueprint
video_bp = Blueprint('video', __name__)

def setup_video_routes(config):
    """Configure video routes with application config"""
    
    @video_bp.route('/get-ytvideo-info.php', methods=['GET'])
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
                'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
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

            # Если указано качество, используем новый подход для получения видео
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
                    
                    # Если получили комбинированный поток (только video_url, audio_url = None)
                    if video_url and not audio_url:
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
                    
                    # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                    elif video_url and audio_url:
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
                        try:
                            threading.Thread(target=_drain_stderr, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate():
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

                        response = Response(generate(), mimetype='video/mp4')
                        response.headers['Content-Type'] = 'video/mp4'
                        if duration_value:
                            duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                            response.headers['X-Content-Duration'] = duration_str
                            response.headers['Content-Duration'] = duration_str
                            response.headers['X-Video-Duration'] = duration_str
                            response.headers['X-Duration-Seconds'] = duration_str
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

            # Fallback: прямой прокси без FFmpeg
            video_url, audio_url = get_video_url(video_id, 'standard')
            
            # Если не удалось получить URL, пробуем с другим cookie файлом
            if not video_url and not audio_url:
                # Попробуем все доступные cookie файлы
                cookies_files = get_cookies_files()
                for cookie_file in cookies_files:
                    video_url, audio_url = get_video_url(video_id, 'standard', cookie_file)
                    if video_url or audio_url:
                        break
            
            # Если получили комбинированный поток (только video_url, audio_url = None)
            if video_url and not audio_url:
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
            
            # Если не удалось получить URL
            else:
                response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
                response.status_code = 500
                response.headers['Content-Length'] = str(len(response.get_data()))
                return response

        except Exception as e:
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
                    import re
                    video_title = re.sub(r'[<>:"/\\|?*]', '_', video_title)
            except Exception as e:
                print(f"Error fetching video info for video_id {video_id}: {e}")

            # Если указано качество, используем новый подход для получения видео
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
                    
                    # Если получили комбинированный поток (только video_url, audio_url = None)
                    if video_url and not audio_url:
                        headers = {
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
                        
                        response = Response(generate(), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        return response
                    
                    # Если получили отдельные потоки видео и аудио, используем FFmpeg для объединения
                    elif video_url and audio_url:
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
                        try:
                            threading.Thread(target=_drain_stderr, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate():
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

                        response = Response(generate(), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        return response
                    
                    # Если не удалось получить URL
                    else:
                        response = jsonify({'error': 'Не удалось получить ссылки на потоки.'})
                        response.status_code = 500
                        return response

                except Exception as e:
                    print(f'Error in download (new approach): {e}')
                    return jsonify({'error': f'Internal server error: {str(e)}'}), 500

            # Fallback: прямой прокси без FFmpeg
            video_url, audio_url = get_video_url(video_id, 'standard')
            
            # Если не удалось получить URL, пробуем с другим cookie файлом
            if not video_url and not audio_url:
                # Попробуем все доступные cookie файлы
                cookies_files = get_cookies_files()
                for cookie_file in cookies_files:
                    video_url, audio_url = get_video_url(video_id, 'standard', cookie_file)
                    if video_url or audio_url:
                        break
            
            # Если получили комбинированный поток (только video_url, audio_url = None)
            if video_url and not audio_url:
                headers = {
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
                
                response = Response(generate(), mimetype='video/mp4')
                response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                return response
            
            # Если не удалось получить URL
            else:
                response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
                response.status_code = 500
                return response

        except Exception as e:
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