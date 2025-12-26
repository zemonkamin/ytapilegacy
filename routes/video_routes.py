from flask import Blueprint, request, jsonify, Response, redirect, stream_with_context
import json
import requests
import subprocess
import threading
import os
import re
import time
from urllib.parse import quote
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from utils.video_processing import get_direct_video_url, get_real_direct_video_url, get_video_url, get_video_info_ytdlp, is_m3u8_url
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

# Создаем сессию requests без таймаутов для потоковой передачи
streaming_session = requests.Session()
streaming_session.timeout = None

# InnerTube helper functions for channel avatar
INNERTUBE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _extract_ytcfg(html: str) -> Dict[str, Any]:
    """Extract ytcfg from YouTube page HTML"""
    m = re.search(r"ytcfg\.set\(\s*({.*?})\s*\)\s*;", html, flags=re.S)
    if not m:
        raise ValueError("ytcfg not found")
    return json.loads(m.group(1))

def _post_json_innertube(session: requests.Session, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Post JSON request to InnerTube API"""
    headers = {
        "User-Agent": INNERTUBE_USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json"
    }
    r = session.post(url, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def _get_in(obj: Any, path: List[str]) -> Any:
    """Get nested value from object by path"""
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur

def _recursive_find_thumbnails(obj: Any, path: List[str] = None) -> List[Tuple[List[str], List[Dict[str, Any]]]]:
    """Find all thumbnail arrays in object"""
    results: List[Tuple[List[str], List[Dict[str, Any]]]] = []
    if path is None:
        path = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = path + [k]
            if k == "thumbnails" and isinstance(v, list) and v and isinstance(v[0], dict) and "url" in v[0]:
                results.append((path, v))
            else:
                results.extend(_recursive_find_thumbnails(v, new_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            new_path = path + [f"[{i}]"]
            results.extend(_recursive_find_thumbnails(item, new_path))
    return results

def _choose_best_thumbnail(thumbnails: List[Dict[str, Any]]) -> Optional[str]:
    """Choose best thumbnail by area"""
    best = None
    best_area = -1
    for t in thumbnails:
        w = t.get("width") or t.get("w") or 0
        h = t.get("height") or t.get("h") or 0
        try:
            area = int(w) * int(h)
        except Exception:
            area = 0
        if area > best_area:
            best_area = area
            best = t
    if best and "url" in best:
        url = best["url"]
        # Fix protocol-relative URLs (starting with //)
        if url.startswith('//'):
            url = 'https:' + url
        return url
    for t in thumbnails:
        if "url" in t:
            url = t["url"]
            # Fix protocol-relative URLs (starting with //)
            if url.startswith('//'):
                url = 'https:' + url
            return url
    return None

def _get_innertube_config(session: Optional[requests.Session] = None) -> Tuple[str, Dict[str, Any]]:
    """Get InnerTube API key and context from YouTube page"""
    sess = session or requests.Session()
    # Get any YouTube page to extract config
    r = sess.get("https://www.youtube.com", headers={"User-Agent": INNERTUBE_USER_AGENT}, timeout=30)
    r.raise_for_status()
    html = r.text
    
    ytcfg = _extract_ytcfg(html)
    api_key = ytcfg.get("INNERTUBE_API_KEY") or ytcfg.get("innertubeApiKey")
    context = ytcfg.get("INNERTUBE_CONTEXT") or ytcfg.get("innertubeContext")
    if not api_key or not context:
        # Try to build context manually
        if "INNERTUBE_CLIENT_VERSION" in ytcfg:
            context = {
                "client": {
                    "clientName": ytcfg.get("INNERTUBE_CLIENT_NAME", "WEB"),
                    "clientVersion": ytcfg.get("INNERTUBE_CLIENT_VERSION")
                }
            }
    if not api_key or not context:
        raise RuntimeError("Не найден INNERTUBE_API_KEY/INNERTUBE_CONTEXT в странице")
    
    return api_key, context

def _get_channel_id_from_video(video_id: str, api_key: str, context: Dict[str, Any], session: requests.Session) -> Optional[str]:
    """Get channel ID from video ID using InnerTube player API"""
    player_url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"
    player_body = {"videoId": video_id, "context": context}
    player_json = _post_json_innertube(session, player_url, player_body)
    
    channel_id = None
    if isinstance(player_json, dict):
        channel_id = player_json.get("videoDetails", {}).get("channelId")
        if not channel_id:
            owner_url = _get_in(player_json, ["microformat", "playerMicroformatRenderer", "ownerProfileUrl"])
            if owner_url:
                m = re.search(r"/(channel|user)/([^/?&]+)", owner_url)
                if m and m.group(1) == "channel":
                    channel_id = m.group(2)
    if not channel_id:
        # Try to find channel ID pattern in response
        text = json.dumps(player_json)
        m = re.search(r"\"(UC[0-9A-Za-z_-]{20,})\"", text)
        if m:
            channel_id = m.group(1)
    
    return channel_id

def _get_channel_avatar_from_browse(channel_id: str, api_key: str, context: Dict[str, Any], session: requests.Session) -> Optional[str]:
    """Get channel avatar URL from InnerTube browse API"""
    browse_url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}"
    browse_body = {"browseId": channel_id, "context": context}
    browse_json = _post_json_innertube(session, browse_url, browse_body)
    
    # Check known paths to avatar
    known_paths = [
        ["header", "c4TabbedHeaderRenderer", "avatar", "thumbnails"],
        ["header", "channelHeaderSupportedRenderers", "channelHeaderRenderer", "avatar", "thumbnails"],
        ["header", "channelHeaderRenderer", "avatar", "thumbnails"],
    ]
    for p in known_paths:
        thumbs = _get_in(browse_json, p)
        if thumbs and isinstance(thumbs, list):
            url = _choose_best_thumbnail(thumbs)
            if url:
                # Fix protocol-relative URLs (starting with //)
                if url.startswith('//'):
                    url = 'https:' + url
                return url
    
    # Fallback: recursively find thumbnails
    candidates = _recursive_find_thumbnails(browse_json)
    prioritized: List[Tuple[List[str], List[Dict[str, Any]]]] = []
    other: List[Tuple[List[str], List[Dict[str, Any]]]] = []
    for path, thumbs in candidates:
        path_str = "/".join(path).lower()
        if any(k in path_str for k in ("avatar", "owner", "channel")):
            prioritized.append((path, thumbs))
        else:
            other.append((path, thumbs))
    for _, thumbs in prioritized + other:
        url = _choose_best_thumbnail(thumbs)
        if url:
            # Fix protocol-relative URLs (starting with //)
            if url.startswith('//'):
                url = 'https:' + url
            return url
    
    return None

def _resolve_handle_to_browse_id(handle: str, session: Optional[requests.Session] = None) -> str:
    """
    Resolves handle (e.g. '@Nerkin' or 'Nerkin') to browseId (UC...).
    Uses navigation/resolve_url via InnerTube; has fallback: parsing HTML page of handle.
    Returns browseId (e.g. 'UC...') or raises exception.
    """
    if not handle:
        raise ValueError("handle is required")
    
    sess = session or requests.Session()
    handle = handle.strip()
    if not handle.startswith("@"):
        handle = "@" + handle
    handle_url = f"https://www.youtube.com/{handle}"
    
    # Get HTML to extract INNERTUBE_API_KEY/context
    r = sess.get(handle_url, headers={"User-Agent": INNERTUBE_USER_AGENT}, timeout=30)
    r.raise_for_status()
    html = r.text
    
    try:
        ytcfg = _extract_ytcfg(html)
    except Exception:
        # fallback: try on YouTube main page (in case of redirect)
        r2 = sess.get("https://www.youtube.com", headers={"User-Agent": INNERTUBE_USER_AGENT}, timeout=30)
        r2.raise_for_status()
        ytcfg = _extract_ytcfg(r2.text)
    
    api_key = ytcfg.get("INNERTUBE_API_KEY") or ytcfg.get("innertubeApiKey")
    context = ytcfg.get("INNERTUBE_CONTEXT") or ytcfg.get("innertubeContext")
    if not api_key or not context:
        # try to restore context minimally
        if "INNERTUBE_CLIENT_VERSION" in ytcfg:
            context = {
                "client": {
                    "clientName": ytcfg.get("INNERTUBE_CLIENT_NAME", "WEB"),
                    "clientVersion": ytcfg.get("INNERTUBE_CLIENT_VERSION")
                }
            }
    if not api_key or not context:
        raise RuntimeError("INNERTUBE_API_KEY/INNERTUBE_CONTEXT not found")
    
    # Attempt 1: navigation/resolve_url
    resolve_url = f"https://www.youtube.com/youtubei/v1/navigation/resolve_url?key={api_key}"
    try:
        resp = _post_json_innertube(sess, resolve_url, {"url": handle_url, "context": context})
        # Look for browseId in response (in different places)
        text = json.dumps(resp)
        m = re.search(r'"(UC[0-9A-Za-z_-]{20,})"', text)
        if m:
            return m.group(1)
        # Try to find browseId in endpoint.payload or metadata
        def traverse_for_browse(obj):
            if isinstance(obj, dict):
                if "browseId" in obj and isinstance(obj["browseId"], str) and obj["browseId"].startswith("UC"):
                    return obj["browseId"]
                for v in obj.values():
                    res = traverse_for_browse(v)
                    if res:
                        return res
            elif isinstance(obj, list):
                for i in obj:
                    res = traverse_for_browse(i)
                    if res:
                        return res
            return None
        browse = traverse_for_browse(resp)
        if browse:
            return browse
    except Exception:
        # ignore and fallback to parsing HTML below
        pass
    
    # Fallback: parse HTML page of handle for channelId/browseId
    # Look for "browseId":"UC..." or "channelId":"UC..." in HTML
    m = re.search(r'(?:"browseId"|"channelId")\s*:\s*"(?P<id>UC[0-9A-Za-z_-]{20,})"', html)
    if m:
        return m.group("id")
    # Another attempt: look in initialData
    m2 = re.search(r"ytInitialData\s*=\s*({.*?});", html, flags=re.S)
    if m2:
        try:
            initial = json.loads(m2.group(1))
            text = json.dumps(initial)
            m3 = re.search(r'"(UC[0-9A-Za-z_-]{20,})"', text)
            if m3:
                return m3.group(1)
        except Exception:
            pass
    
    raise RuntimeError("Не удалось разрешить handle в browseId")

def get_channel_avatar_url_innertube(identifier: str, session: Optional[requests.Session] = None) -> Optional[str]:
    """
    Get channel avatar URL using InnerTube API.
    identifier can be:
    - video_id: YouTube video ID
    - channel_id: YouTube channel ID (starts with UC)
    - username: Channel username (starts with @)
    """
    sess = session or requests.Session()
    
    try:
        # Get InnerTube config
        api_key, context = _get_innertube_config(sess)
        
        # Determine channel_id based on identifier type
        channel_id = None
        
        if identifier.startswith('UC') and len(identifier) >= 24:
            # It's already a channel ID
            channel_id = identifier
        elif identifier.startswith('@'):
            # Username/handle - resolve to browseId using navigation/resolve_url
            try:
                channel_id = _resolve_handle_to_browse_id(identifier, sess)
            except Exception as e:
                print(f'Error resolving handle to browseId: {e}')
                return None
        else:
            # Assume it's a video_id
            channel_id = _get_channel_id_from_video(identifier, api_key, context, sess)
            if not channel_id:
                return None
        
        # Get avatar from browse API
        url = _get_channel_avatar_from_browse(channel_id, api_key, context, sess)
        # Additional safety check for protocol-relative URLs
        if url and url.startswith('//'):
            url = 'https:' + url
        return url
    
    except Exception as e:
        print(f'Error getting channel avatar via InnerTube: {e}')
        return None

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
            proxy_param = request.args.get('proxy', 'true').lower()
            use_proxy = proxy_param != 'false'
            
            if not video_id:
                response = jsonify({'error': 'ID видео не был передан.'})
                response.status_code = 400
                response.headers['Content-Length'] = str(len(response.get_data()))
                return response

            # If proxy=false, redirect to the original video URL
            if not use_proxy:
                try:
                    # Если есть параметр quality, получаем URL с нужным качеством
                    if quality:
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
                        if desired_height:
                            quality_str = str(desired_height)
                        else:
                            quality_str = 'standard'
                        
                        # Получаем URL с нужным качеством
                        video_url, _ = get_video_url(video_id, quality_str)
                        # Используем video_url
                        if not video_url:
                            # Если не удалось получить URL, пробуем с другим cookie файлом
                            cookies_files = get_cookies_files()
                            for cookie_file in cookies_files:
                                video_url, _ = get_video_url(video_id, quality_str, cookie_file)
                                if video_url:
                                    break
                    else:
                        # Если quality не указан, используем стандартный метод
                        video_url = get_real_direct_video_url(video_id)
                    
                    if video_url:
                        # Redirect to the original URL
                        return redirect(video_url)
                    else:
                        response = jsonify({'error': 'Не удалось получить прямую ссылку на видео.'})
                        response.status_code = 500
                        response.headers['Content-Length'] = str(len(response.get_data()))
                        return response
                except Exception as e:
                    print(f'Error getting original video URL: {e}')
                    response = jsonify({'error': f'Internal server error: {str(e)}'})
                    response.status_code = 500
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

            # Обработка HEAD запроса
            if request.method == 'HEAD':
                response = Response(None, mimetype='video/mp4')
                response.headers['Accept-Ranges'] = 'bytes'
                response.headers['Content-Type'] = 'video/mp4'
                return response

            # Create a unique key for this download
            download_key = f"{video_id}_{quality}" if quality else video_id
            
            # Check if download is already in progress
            with download_lock:
                if download_key in ongoing_downloads:
                    # Download is in progress, proxy the original URL while it completes
                    if quality:
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
                        if desired_height:
                            quality_str = str(desired_height)
                        else:
                            quality_str = 'standard'
                    else:
                        quality_str = 'standard'
                    
                    video_url, _ = get_video_url(video_id, quality_str)
                    if not video_url:
                        cookies_files = get_cookies_files()
                        for cookie_file in cookies_files:
                            video_url, _ = get_video_url(video_id, quality_str, cookie_file)
                            if video_url:
                                break
                    
                    if video_url:
                        # Проверяем, является ли URL m3u8
                        if is_m3u8_url(video_url):
                            # Конвертируем m3u8 в MP4 через FFmpeg
                            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                            common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                            ffmpeg_cmd = [
                                'ffmpeg',
                                '-hide_banner',
                                '-loglevel', 'error',
                                '-nostdin',
                                '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                                '-reconnect', '1',
                                '-reconnect_streamed', '1',
                                '-reconnect_at_eof', '1',
                                '-reconnect_delay_max', '10',
                                '-user_agent', user_agent,
                                '-headers', common_headers,
                                '-i', video_url,
                                '-c:v', 'copy',
                                '-c:a', 'aac',
                                '-b:a', '192k',
                                '-bsf:a', 'aac_adtstoasc',
                                '-fflags', '+genpts',
                                '-avoid_negative_ts', 'make_zero',
                                '-movflags', 'frag_keyframe+empty_moov+default_base_moof+faststart',
                                '-f', 'mp4',
                                '-'
                            ]

                            ffmpeg_process = subprocess.Popen(
                                ffmpeg_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                bufsize=0
                            )

                            def _drain_stderr_m3u8():
                                try:
                                    if ffmpeg_process and ffmpeg_process.stderr:
                                        while True:
                                            line = ffmpeg_process.stderr.readline()
                                            if not line:
                                                break
                                except Exception:
                                    pass
                            try:
                                threading.Thread(target=_drain_stderr_m3u8, daemon=True).start()
                            except Exception as e:
                                print(f"Error starting stderr drain thread: {e}")

                            def generate_m3u8():
                                try:
                                    if ffmpeg_process and ffmpeg_process.stdout:
                                        while True:
                                            chunk = ffmpeg_process.stdout.read(65536)
                                            if not chunk:
                                                if ffmpeg_process.poll() is not None:
                                                    break
                                                # Небольшая задержка, чтобы не нагружать CPU
                                                time.sleep(0.01)
                                                continue
                                            yield chunk
                                except Exception as e:
                                    print(f"Error in generate_m3u8: {e}")
                                finally:
                                    try:
                                        if ffmpeg_process:
                                            ffmpeg_process.terminate()
                                            ffmpeg_process.wait(timeout=5)
                                    except Exception:
                                        pass

                            response = Response(stream_with_context(generate_m3u8()), mimetype='video/mp4')
                            response.headers['Accept-Ranges'] = 'bytes'
                            response.headers['Content-Type'] = 'video/mp4'
                            # Не устанавливаем Content-Length для потоковой передачи
                            return response
                        else:
                            # Proxy the original URL directly (не m3u8)
                            headers = {
                                'Range': request.headers.get('Range', 'bytes=0-'),
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            }
                            # Используем сессию без таймаутов для потоковой передачи
                            resp = streaming_session.get(video_url, headers=headers, stream=True)
                            
                            def generate():
                                try:
                                    resp.raise_for_status()
                                    for chunk in resp.iter_content(chunk_size=65536):
                                        if chunk:
                                            yield chunk
                                except requests.exceptions.RequestException as e:
                                    print(f'Error streaming video: {e}')
                                except Exception as e:
                                    print(f'Unexpected error in generate: {e}')
                                finally:
                                    try:
                                        resp.close()
                                    except:
                                        pass
                            
                            response = Response(stream_with_context(generate()), status=resp.status_code, mimetype='video/mp4')
                            response.headers['Accept-Ranges'] = 'bytes'
                            response.headers['Content-Type'] = 'video/mp4'
                            # Не устанавливаем Content-Length для потоковой передачи
                            if 'content-range' in resp.headers:
                                response.headers['Content-Range'] = resp.headers['content-range']
                            return response
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

                # Получаем URL видео для указанного качества
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

                # Определяем качество
                if quality:
                    desired_height = parse_desired_height(quality)
                    if desired_height:
                        quality_str = str(desired_height)
                    else:
                        quality_str = 'standard'
                else:
                    quality_str = 'standard'
                
                # Получаем URL видео
                video_url, _ = get_video_url(video_id, quality_str)
                
                # Если не удалось получить URL, пробуем с другим cookie файлом
                if not video_url:
                    cookies_files = get_cookies_files()
                    for cookie_file in cookies_files:
                        video_url, _ = get_video_url(video_id, quality_str, cookie_file)
                        if video_url:
                            break
                
                if video_url:
                    # Проверяем, является ли URL m3u8
                    if is_m3u8_url(video_url):
                        # Конвертируем m3u8 в MP4 через FFmpeg и сохраняем в кеш
                        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                        common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-hide_banner',
                            '-loglevel', 'error',
                            '-nostdin',
                            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                            '-reconnect', '1',
                            '-reconnect_streamed', '1',
                            '-reconnect_at_eof', '1',
                            '-reconnect_delay_max', '10',
                            '-user_agent', user_agent,
                            '-headers', common_headers,
                            '-i', video_url,
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-b:a', '192k',
                            '-bsf:a', 'aac_adtstoasc',
                            '-fflags', '+genpts',
                            '-avoid_negative_ts', 'make_zero',
                            '-movflags', 'frag_keyframe+empty_moov+default_base_moof+faststart',
                            '-f', 'mp4',
                            '-'
                        ]

                        ffmpeg_process = subprocess.Popen(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            bufsize=0
                        )

                        def _drain_stderr_m3u8():
                            try:
                                if ffmpeg_process and ffmpeg_process.stderr:
                                    while True:
                                        line = ffmpeg_process.stderr.readline()
                                        if not line:
                                            break
                                        if line:
                                            print(f"FFmpeg stderr: {line.decode('utf-8', errors='ignore').strip()}")
                            except Exception:
                                pass
                        try:
                            threading.Thread(target=_drain_stderr_m3u8, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate_and_cache_m3u8():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    # Проверяем, завершился ли процесс
                                                    if ffmpeg_process.poll() is not None:
                                                        break
                                                    # Небольшая задержка, чтобы не нагружать CPU
                                                    time.sleep(0.01)
                                                    continue
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    if ffmpeg_process and ffmpeg_process.stdout:
                                        while True:
                                            chunk = ffmpeg_process.stdout.read(65536)
                                            if not chunk:
                                                # Проверяем, завершился ли процесс
                                                if ffmpeg_process.poll() is not None:
                                                    break
                                                # Небольшая задержка, чтобы не нагружать CPU
                                                time.sleep(0.01)
                                                continue
                                            yield chunk
                            except Exception as e:
                                print(f"Error in generate_and_cache_m3u8: {e}")
                            finally:
                                try:
                                    if ffmpeg_process:
                                        ffmpeg_process.terminate()
                                        ffmpeg_process.wait(timeout=5)
                                except Exception:
                                    pass

                        response = Response(stream_with_context(generate_and_cache_m3u8()), mimetype='video/mp4')
                        response.headers['Content-Type'] = 'video/mp4'
                        response.headers['Accept-Ranges'] = 'bytes'
                        # Не устанавливаем Content-Length для потоковой передачи
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                    else:
                        # Просто проксируем видео URL (не m3u8)
                        headers = {
                            'Range': request.headers.get('Range', 'bytes=0-'),
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        # Используем сессию без таймаутов для потоковой передачи
                        resp = streaming_session.get(video_url, headers=headers, stream=True)
                        
                        def generate_and_cache():
                            try:
                                resp.raise_for_status()
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        for chunk in resp.iter_content(chunk_size=65536):
                                            if chunk:
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    for chunk in resp.iter_content(chunk_size=65536):
                                        if chunk:
                                            yield chunk
                            except requests.exceptions.RequestException as e:
                                print(f'Error streaming video: {e}')
                            except Exception as e:
                                print(f'Unexpected error in generate_and_cache: {e}')
                            finally:
                                try:
                                    resp.close()
                                except:
                                    pass
                        
                        response = Response(stream_with_context(generate_and_cache()), status=resp.status_code, mimetype='video/mp4')
                        response.headers['Accept-Ranges'] = 'bytes'
                        response.headers['Content-Type'] = 'video/mp4'
                        # Не устанавливаем Content-Length для потоковой передачи
                        if 'content-range' in resp.headers:
                            response.headers['Content-Range'] = resp.headers['content-range']
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
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
                # Получаем URL видео для указанного качества
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

                # Определяем качество
                if quality:
                    desired_height = parse_desired_height(quality)
                    if desired_height:
                        quality_str = str(desired_height)
                    else:
                        quality_str = 'standard'
                else:
                    quality_str = 'standard'
                
                # Получаем URL видео
                video_url, _ = get_video_url(video_id, quality_str)
                
                # Если не удалось получить URL, пробуем с другим cookie файлом
                if not video_url:
                    cookies_files = get_cookies_files()
                    for cookie_file in cookies_files:
                        video_url, _ = get_video_url(video_id, quality_str, cookie_file)
                        if video_url:
                            break
                
                if video_url:
                    # Проверяем, является ли URL m3u8
                    if is_m3u8_url(video_url):
                        # Конвертируем m3u8 в MP4 через FFmpeg и сохраняем в кеш
                        user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36'
                        common_headers = 'Referer: https://www.youtube.com\r\nOrigin: https://www.youtube.com'
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-hide_banner',
                            '-loglevel', 'error',
                            '-nostdin',
                            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
                            '-reconnect', '1',
                            '-reconnect_streamed', '1',
                            '-reconnect_at_eof', '1',
                            '-reconnect_delay_max', '10',
                            '-user_agent', user_agent,
                            '-headers', common_headers,
                            '-i', video_url,
                            '-c:v', 'copy',
                            '-c:a', 'aac',
                            '-b:a', '192k',
                            '-bsf:a', 'aac_adtstoasc',
                            '-fflags', '+genpts',
                            '-avoid_negative_ts', 'make_zero',
                            '-movflags', 'frag_keyframe+empty_moov+default_base_moof+faststart',
                            '-f', 'mp4',
                            '-'
                        ]

                        ffmpeg_process = subprocess.Popen(
                            ffmpeg_cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            bufsize=0
                        )

                        def _drain_stderr_m3u8_download():
                            try:
                                if ffmpeg_process and ffmpeg_process.stderr:
                                    while True:
                                        line = ffmpeg_process.stderr.readline()
                                        if not line:
                                            break
                                        if line:
                                            print(f"FFmpeg stderr (download): {line.decode('utf-8', errors='ignore').strip()}")
                            except Exception:
                                pass
                        try:
                            threading.Thread(target=_drain_stderr_m3u8_download, daemon=True).start()
                        except Exception as e:
                            print(f"Error starting stderr drain thread: {e}")

                        def generate_and_cache_m3u8_download():
                            try:
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        if ffmpeg_process and ffmpeg_process.stdout:
                                            while True:
                                                chunk = ffmpeg_process.stdout.read(65536)
                                                if not chunk:
                                                    # Проверяем, завершился ли процесс
                                                    if ffmpeg_process.poll() is not None:
                                                        break
                                                    # Небольшая задержка, чтобы не нагружать CPU
                                                    time.sleep(0.01)
                                                    continue
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    if ffmpeg_process and ffmpeg_process.stdout:
                                        while True:
                                            chunk = ffmpeg_process.stdout.read(65536)
                                            if not chunk:
                                                # Проверяем, завершился ли процесс
                                                if ffmpeg_process.poll() is not None:
                                                    break
                                                # Небольшая задержка, чтобы не нагружать CPU
                                                time.sleep(0.01)
                                                continue
                                            yield chunk
                            except Exception as e:
                                print(f"Error in generate_and_cache_m3u8_download: {e}")
                            finally:
                                try:
                                    if ffmpeg_process:
                                        ffmpeg_process.terminate()
                                        ffmpeg_process.wait(timeout=5)
                                except Exception:
                                    pass

                        response = Response(stream_with_context(generate_and_cache_m3u8_download()), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        # Не устанавливаем Content-Length для потоковой передачи
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                    else:
                        # Просто проксируем видео URL (не m3u8)
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        # Используем сессию без таймаутов для потоковой передачи
                        resp = streaming_session.get(video_url, headers=headers, stream=True)
                        
                        def generate_and_cache_download():
                            try:
                                resp.raise_for_status()
                                if cache_path:
                                    # Ensure directory exists
                                    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                                    with open(cache_path, 'wb') as cache_file:
                                        for chunk in resp.iter_content(chunk_size=65536):
                                            if chunk:
                                                cache_file.write(chunk)
                                                yield chunk
                                else:
                                    for chunk in resp.iter_content(chunk_size=65536):
                                        if chunk:
                                            yield chunk
                            except requests.exceptions.RequestException as e:
                                print(f'Error streaming video for download: {e}')
                            except Exception as e:
                                print(f'Unexpected error in generate_and_cache_download: {e}')
                            finally:
                                try:
                                    resp.close()
                                except:
                                    pass
                        
                        response = Response(stream_with_context(generate_and_cache_download()), mimetype='video/mp4')
                        response.headers['Content-Disposition'] = f'attachment; filename="{video_title}.mp4"'
                        # Не устанавливаем Content-Length для потоковой передачи
                        
                        # Check and cleanup cache if needed
                        check_and_cleanup_cache(
                            config.get('temp_folder_max_size_mb', 5120),
                            config.get('cache_cleanup_threshold_mb', 100)
                        )
                        
                        return response
                else:
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
            # Check if the video_id is actually a direct image URL
            if video_id.startswith('http'):
                # It's a direct URL, proxy it directly
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                # Proxy the image directly
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
            
            # Use InnerTube API to get channel avatar (no API key needed)
            thumbnail_url = get_channel_avatar_url_innertube(video_id)
            
            if not thumbnail_url:
                return jsonify({'error': 'Channel thumbnail not found'}), 404
            
            # Fix protocol-relative URLs (starting with //) - additional safety check
            if thumbnail_url and thumbnail_url.startswith('//'):
                thumbnail_url = 'https:' + thumbnail_url
            
            # Replace yt3.ggpht.com with yt3.googleusercontent.com to avoid SSL issues
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
            # Используем сессию без таймаутов для потоковой передачи
            resp = streaming_session.get(url, headers=headers, stream=True)
            def generate():
                try:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            yield chunk
                except requests.exceptions.RequestException as e:
                    print(f'Error in video proxy: {e}')
                except Exception as e:
                    print(f'Unexpected error in video proxy generate: {e}')
                finally:
                    try:
                        resp.close()
                    except:
                        pass
            response = Response(stream_with_context(generate()), status=resp.status_code)
            response.headers['Content-Type'] = resp.headers.get('content-type', 'application/octet-stream')
            # Не устанавливаем Content-Length для потоковой передачи - пусть клиент читает до конца потока
            response.headers['Accept-Ranges'] = 'bytes'
            if 'content-range' in resp.headers:
                response.headers['Content-Range'] = resp.headers['content-range']
            return response
        except Exception as e:
            print('Error in video proxy:', e)
            return jsonify({'error': 'Internal server error'}), 500