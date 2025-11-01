from flask import Blueprint, request, jsonify, Response
import json
import requests
import subprocess
import re
import random
from urllib.parse import quote
from utils.video_processing import get_direct_video_url, get_real_direct_video_url, get_video_url
from utils.helpers import (
    run_yt_dlp, get_channel_thumbnail, get_proxy_url, get_video_proxy_url,
    get_api_key, get_api_key_rotated, get_available_formats
)
from utils.auth import refresh_access_token
import string
from yt import config

# Создаём blueprint
additional_bp = Blueprint('additional', __name__)

INNERTUBE_API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"


def setup_additional_routes(config):
    """Настройка всех дополнительных маршрутов с передачей config"""

    @additional_bp.route('/get-direct-video-url.php', methods=['GET'])
    def get_direct_video_url_api():
        try:
            video_id = request.args.get('video_id')
            if not video_id:
                return jsonify({'error': 'ID видео не был передан.'}), 400
            video_url = get_direct_video_url(video_id)
            if video_url:
                return jsonify({'video_url': video_url})
            else:
                return jsonify({'error': 'Не удалось получить прямую ссылку на видео.'}), 500
        except Exception as e:
            print('Error in get-direct-video-url:', e)
            return jsonify({'error': 'Internal server error'}), 500

    @additional_bp.route('/direct_audio_url', methods=['GET', 'HEAD'])
    def direct_audio_url():
        try:
            video_id = request.args.get('video_id')
            if not video_id:
                return jsonify({'error': 'ID видео не был передан.'}), 400

            duration_value = None
            try:
                url = f'https://www.youtube.com/watch?v={video_id}'
                info_output = run_yt_dlp(['--dump-json', '--no-warnings', url])
                if info_output:
                    info = json.loads(info_output)
                    duration_value = info.get('duration')
            except Exception as e:
                print(f"Error fetching duration for video_id {video_id}: {e}")

            try:
                formats = get_available_formats(video_id)
                if not formats:
                    return jsonify({'error': 'Не удалось получить информацию о форматах.'}), 500

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

                best_audio = max(audio_formats, key=lambda f: f.get('tbr', 0))
                format_id = best_audio['format_id']
                print(f"[DEBUG] Выбран формат аудио: ID={format_id}, tbr={best_audio.get('tbr', 'N/A')}")

                url = f'https://www.youtube.com/watch?v={video_id}'
                audio_url = run_yt_dlp(['-f', format_id, '--get-url', url])
                if not audio_url:
                    return jsonify({'error': 'Не удалось получить ссылку на аудио поток.'}), 500

                headers = {
                    'Range': request.headers.get('Range', 'bytes=0-'),
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                resp = requests.get(audio_url, headers=headers, stream=True, timeout=config['request_timeout'])

                def generate():
                    try:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                yield chunk
                    finally:
                        resp.close()

                response = Response(
                    None if request.method == 'HEAD' else generate(),
                    status=resp.status_code,
                    mimetype='audio/m4a'
                )
                response.headers['Content-Type'] = resp.headers.get('content-type', 'audio/m4a')
                response.headers['Content-Length'] = resp.headers.get('content-length', '')
                response.headers['Accept-Ranges'] = 'bytes'
                if 'content-range' in resp.headers:
                    response.headers['Content-Range'] = resp.headers['content-range']
                if duration_value:
                    duration_str = str(int(duration_value)) if isinstance(duration_value, (int, float)) else str(duration_value)
                    for header in ['X-Content-Duration', 'Content-Duration', 'X-Video-Duration', 'X-Duration-Seconds']:
                        response.headers[header] = duration_str
                return response
            except Exception as e:
                print('Error in direct_audio_url:', e)
                return jsonify({'error': 'Internal server error'}), 500
        except Exception as e:
            print('Error in direct_audio_url:', e)
            return jsonify({'error': 'Internal server error'}), 500

    @additional_bp.route('/get_subscriptions.php', methods=['GET'])
    def get_default_subscriptions():
        try:
            refresh_token = request.args.get('token')
            if not refresh_token:
                return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

            try:
                token_data = refresh_access_token(refresh_token)
                access_token = token_data['access_token']
                print(f"Access token: {access_token[:20]}...")
            except Exception as e:
                return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

            json_data = use_innertube_subscriptions(access_token)
            if not json_data:
                return jsonify({'error': 'Failed to fetch subscriptions data from YouTube API'}), 500

            subscriptions_data = extract_simplified_subscriptions_data(json_data, request)
            response_data = {
                'status': 'success',
                'count': subscriptions_data['count'],
                'subscriptions': subscriptions_data['subscriptions']
            }
            print(f"Returned {subscriptions_data['count']} subscriptions")
            return jsonify(response_data)
        except Exception as e:
            print(f"Error in get_default_subscriptions: {e}")
            return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

    @additional_bp.route('/get_recommendations.php', methods=['GET'])
    def get_recommendations_innertube():
        try:
            count = config.get('default_count', 50)
            refresh_token = request.args.get('token')
            if not refresh_token:
                return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

            try:
                token_data = refresh_access_token(refresh_token)
                access_token = token_data['access_token']
            except Exception as e:
                return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

            endpoint = "https://www.youtube.com/youtubei/v1/browse"
            payload = {
                "context": {
                    "client": {
                        "hl": "en", "gl": "US", "deviceMake": "Samsung",
                        "deviceModel": "SmartTV",
                        "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1",
                        "clientName": "TVHTML5", "clientVersion": "7.20250209.19.00",
                        "osName": "Tizen", "osVersion": "5.0", "platform": "TV",
                        "clientFormFactor": "UNKNOWN_FORM_FACTOR", "screenPixelDensity": 1
                    }
                },
                "browseId": "FEwhat_to_watch"
            }

            params = {"key": get_api_key_rotated(config), "prettyPrint": "false"}
            headers = {
                'User-Agent': payload["context"]["client"]["userAgent"],
                'Accept': '*/*', 'Accept-Language': 'en-US,en;q=0.5',
                'Content-Type': 'application/json', 'Origin': 'https://www.youtube.com',
                'Referer': 'https://www.youtube.com/', 'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive', 'Authorization': f'Bearer {access_token}'
            }

            try:
                response = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                json_data = response.json()
            except Exception as e:
                msg = str(e).encode('ascii', errors='ignore').decode('ascii')
                return jsonify({'error': 'InnerTube request failed', 'details': msg}), 500

            videos = extract_innertube_data(json_data, count)
            formatted_videos = []
            for video in videos:
                if video and video.get('video_id') and video.get('video_id') != 'unknown':
                    formatted_videos.append({
                        'title': video.get('title', 'No Title'),
                        'author': video.get('author', 'Unknown'),
                        'video_id': video.get('video_id'),
                        'thumbnail': f"{config['mainurl']}thumbnail/{video.get('video_id')}",
                        'channel_thumbnail': ''
                    })
            return jsonify(formatted_videos)
        except Exception as e:
            msg = str(e).encode('ascii', errors='ignore').decode('ascii')
            return jsonify({'error': 'API request failed', 'details': msg}), 500

    @additional_bp.route('/get_related_videos.php', methods=['GET'])
    def get_related_videos():
        try:
            video_id = request.args.get('video_id')
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            apikey = get_api_key_rotated(config)
            refresh_token = request.args.get('token')

            if not video_id:
                return jsonify({'error': 'ID видео не был передан.'}), 400

            video_resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}&key={apikey}")
            video_resp.raise_for_status()
            video_data = video_resp.json()
            videoInfo = video_data.get('items', [{}])[0].get('snippet')
            if not videoInfo:
                return jsonify({'error': 'Видео не найдено.'}), 404

            relatedVideos = []
            search_query = videoInfo['title'].split(' ')[0]
            search_resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(search_query)}&type=video&maxResults={count}&key={apikey}")
            search_data = search_resp.json() if search_resp.status_code == 200 else {'items': []}

            for video in search_data.get('items', []):
                if video['id']['videoId'] == video_id:
                    continue
                vinfo = video['snippet']
                vid = video['id']['videoId']
                channelThumbnail = get_channel_thumbnail(vinfo['channelId'], apikey, config)
                try:
                    stats = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={apikey}", timeout=5).json()
                    viewCount = stats['items'][0]['statistics']['viewCount'] if stats.get('items') else '0'
                except:
                    viewCount = '0'

                relatedVideos.append({
                    'title': vinfo['title'],
                    'author': vinfo['channelTitle'],
                    'video_id': vid,
                    'views': viewCount,
                    'published_at': vinfo.get('publishedAt', ''),
                    'thumbnail': f"{config['mainurl']}thumbnail/{vid}",
                    'channel_thumbnail': get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy']),
                    'url': get_video_proxy_url(f"{config['mainurl']}get-ytvideo-info.php?video_id={vid}&quality={config['default_quality']}", config['use_video_proxy']),
                    'source': 'search'
                })

            if refresh_token and len(relatedVideos) < count:
                try:
                    token_data = refresh_access_token(refresh_token)
                    if 'access_token' in token_data:
                        access_token = token_data['access_token']
                        recommendations = get_innertube_recommendations(access_token, count - len(relatedVideos), config)
                        for rec in recommendations:
                            if any(v['video_id'] == rec['video_id'] for v in relatedVideos):
                                continue
                            vid = rec['video_id']
                            try:
                                stats = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={apikey}", timeout=5).json()
                                viewCount = stats['items'][0]['statistics']['viewCount'] if stats.get('items') else '0'
                            except:
                                viewCount = '0'
                            try:
                                ch = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={vid}&key={apikey}", timeout=5).json()
                                ch_thumb = get_channel_thumbnail(ch['items'][0]['snippet']['channelId'], apikey, config) if ch.get('items') else ''
                            except:
                                ch_thumb = ''
                            relatedVideos.append({
                                'title': rec.get('title', 'No Title'),
                                'author': rec.get('author', 'Unknown'),
                                'video_id': vid,
                                'views': viewCount,
                                'published_at': '',
                                'thumbnail': f"{config['mainurl']}thumbnail/{vid}",
                                'channel_thumbnail': get_proxy_url(ch_thumb, config['use_channel_thumbnail_proxy']),
                                'url': get_video_proxy_url(f"{config['mainurl']}get-ytvideo-info.php?video_id={vid}&quality={config['default_quality']}", config['use_video_proxy']),
                                'source': 'recommendations'
                            })
                except Exception as e:
                    print('Error with InnerTube recommendations:', e)

            return jsonify(relatedVideos[:count])
        except Exception as e:
            print('Error in get_related_videos:', e)
            return jsonify({'error': 'Internal server error'}), 500

    @additional_bp.route('/get_history.php', methods=['GET'])
    def get_history():
        try:
            count = config.get('default_count', 50)
            refresh_token = request.args.get('token')
            if not refresh_token:
                return jsonify({'error': 'Missing token parameter'}), 400

            token_data = refresh_access_token(refresh_token)
            access_token = token_data['access_token']

            videos = []
            continuation_token = None
            while len(videos) < count:
                json_data = fetch_history_page(access_token, continuation_token, config)
                if not json_data:
                    break
                page_videos, continuation_token = extract_history_data_with_continuation(json_data, count - len(videos))
                videos.extend(page_videos)
                if not continuation_token or not page_videos:
                    break

            formatted = []
            for v in videos:
                if v and v.get('video_id') and v.get('video_id') != 'unknown':
                    formatted.append({
                        'title': v.get('title', 'No Title'),
                        'author': v.get('author', 'Unknown'),
                        'video_id': v.get('video_id'),
                        'thumbnail': f"{config['mainurl']}thumbnail/{v.get('video_id')}",
                        'channel_thumbnail': '',
                        'views': v.get('views', 0),
                        'duration': v.get('duration', '0:00'),
                        'watched_at': v.get('watched_at', '')
                    })
            return jsonify(formatted)
        except Exception as e:
            msg = str(e).encode('ascii', errors='ignore').decode('ascii')
            return jsonify({'error': 'API request failed', 'details': msg}), 500

    @additional_bp.route('/mark_video_watched.php', methods=['GET', 'POST'])
    def mark_video_watched():
        try:
            video_id = request.args.get('video_id')
            refresh_token = request.args.get('token')
            if not video_id or not refresh_token:
                return jsonify({'error': 'Missing video_id or token'}), 400

            token_data = refresh_access_token(refresh_token)
            access_token = token_data.get('access_token')
            if not access_token:
                return jsonify({'error': 'Failed to get access_token'}), 401

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'User-Agent': 'com.google.android.youtube/19.14.37'
            }
            context = {
                "context": {
                    "client": {
                        "clientName": "ANDROID", "clientVersion": "19.14.37",
                        "hl": "en", "gl": "US", "osName": "Android", "osVersion": "13", "platform": "MOBILE"
                    }
                }
            }
            player_payload = {**context, "videoId": video_id, "cpn": generate_cpn()}
            player_resp = requests.post(f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_API_KEY}", headers=headers, json=player_payload, timeout=15)
            if player_resp.status_code != 200:
                return jsonify({'error': 'Player failed', 'body': player_resp.text[:500]}), 400

            feedback_token = None
            try:
                feedback_token = player_resp.json().get("playbackTracking", {}).get("videostatsPlaybackUrl", {}).get("baseUrl")
            except:
                pass
            if not feedback_token:
                tokens = re.findall(r'"feedbackToken"\s*:\s*"([^"]+)"', player_resp.text)
                if tokens:
                    feedback_token = tokens[0]
            if not feedback_token:
                return jsonify({'error': 'No feedback token'}), 500

            feedback_payload = {**context, "feedbackTokens": [feedback_token]}
            feedback_resp = requests.post(f"https://www.youtube.com/youtubei/v1/feedback?key={INNERTUBE_API_KEY}", headers=headers, json=feedback_payload, timeout=15)
            if feedback_resp.status_code == 200:
                return jsonify({'status': 'success', 'message': f'Video {video_id} marked as watched'})
            else:
                return jsonify({'status': 'error', 'details': feedback_resp.text}), feedback_resp.status_code
        except Exception as e:
            return jsonify({'error': 'Internal error', 'details': str(e)}), 500

    # === Вспомогательные функции ===
    def use_innertube_subscriptions(access_token):
        endpoint = "https://www.googleapis.com/youtubei/v1/browse"
        payload = {
            "context": {
                "client": {
                    "hl": "en", "gl": "US", "deviceMake": "Samsung", "deviceModel": "SmartTV",
                    "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1",
                    "clientName": "TVHTML5", "clientVersion": "7.20250209.19.00",
                    "osName": "Tizen", "osVersion": "5.0", "platform": "TV",
                    "clientFormFactor": "UNKNOWN_FORM_FACTOR", "screenPixelDensity": 1
                }
            },
            "browseId": "FEsubscriptions"
        }
        params = {"key": "AIzaSyDCU8hByM-4DrUqRUYnGn-3llEO78bcxq8", "prettyPrint": "false"}
        headers = {
            'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json',
            'User-Agent': payload["context"]["client"]["userAgent"],
            'Origin': 'https://www.youtube.com', 'Referer': 'https://www.youtube.com/'
        }
        try:
            resp = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except:
            return None

    def extract_simplified_subscriptions_data(json_data, request):
        subscriptions = []
        count = 0
        mainurl = config.get('mainurl', 'http://127.0.0.1:5000/')
        try:
            tabs = None
            # Попытки найти tabs
            try:
                tabs = (json_data.get('contents', {}).get('tvBrowseRenderer', {}).get('content', {})
                        .get('tvSecondaryNavRenderer', {}).get('sections', [{}])[0]
                        .get('tvSecondaryNavSectionRenderer', {}).get('tabs', []))
            except:
                pass
            if not tabs:
                def find_tabs(obj):
                    if isinstance(obj, dict) and 'tabs' in obj and isinstance(obj['tabs'], list):
                        return obj['tabs']
                    for v in obj.values() if isinstance(obj, dict) else (obj if isinstance(obj, list) else []):
                        result = find_tabs(v)
                        if result: return result
                    return None
                tabs = find_tabs(json_data)

            if tabs:
                for tab in tabs:
                    if count >= 20: break
                    renderer = tab.get('tabRenderer', {})
                    if not renderer: continue
                    username = renderer.get('title', 'Unknown')
                    if username.lower() == "all": continue

                    thumb_url = "https://s.ytimg.com/yt/img/no_videos_140-vfl5AhOQY.png"
                    thumbs = renderer.get('thumbnail', {}).get('thumbnails', [])
                    if thumbs:
                        thumb_url = thumbs[-1].get('url', '')
                        if thumb_url.startswith('//'):
                            thumb_url = "https:" + thumb_url

                    clean_username = re.sub(r'[^a-zA-Z0-9_-]', '', username.replace(' ', '_'))
                    # Create a proxy URL for local_thumbnail using mainurl + channel_icon + the thumbnail URL
                    local_thumb = f"{mainurl}channel_icon/{thumb_url}"

                    channel_id = "unknown"
                    try:
                        ep = renderer.get('endpoint', {}) or renderer.get('navigationEndpoint', {})
                        channel_id = ep.get('browseEndpoint', {}).get('browseId', 'unknown')
                    except:
                        pass
                    if channel_id == "unknown": continue

                    subscriptions.append({
                        'channel_id': channel_id,
                        'title': username,
                        'thumbnail': thumb_url,
                        'local_thumbnail': local_thumb,
                        'profile_url': f"{mainurl}get_author_videos.php?author={username}"
                    })
                    count += 1
        except Exception as e:
            print(f"Error extracting subscriptions: {e}")
        return {'subscriptions': subscriptions, 'count': count}

    def get_innertube_recommendations(access_token, max_count, config):
        try:
            endpoint = "https://www.youtube.com/youtubei/v1/browse"
            payload = {
                "context": {
                    "client": {
                        "hl": "en", "gl": "US", "deviceMake": "Samsung", "deviceModel": "SmartTV",
                        "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1",
                        "clientName": "TVHTML5", "clientVersion": "7.20250209.19.00",
                        "osName": "Tizen", "osVersion": "5.0", "platform": "TV",
                        "clientFormFactor": "UNKNOWN_FORM_FACTOR", "screenPixelDensity": 1
                    }
                },
                "browseId": "FEwhat_to_watch"
            }
            params = {"key": get_api_key_rotated(config), "prettyPrint": "false"}
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'User-Agent': payload["context"]["client"]["userAgent"],
                'Origin': 'https://www.youtube.com', 'Referer': 'https://www.youtube.com/'
            }
            resp = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return extract_innertube_data(resp.json(), max_count)
        except:
            return []

    def fetch_history_page(access_token, continuation_token, config):
        endpoint = "https://www.youtube.com/youtubei/v1/browse"
        payload = {
            "context": {
                "client": {
                    "hl": "en", "gl": "US", "deviceMake": "Samsung", "deviceModel": "SmartTV",
                    "userAgent": "Mozilla/5.0 (SMART-TV; Linux; Tizen 5.0) AppleWebKit/538.1",
                    "clientName": "TVHTML5", "clientVersion": "7.20250209.19.00",
                    "osName": "Tizen", "osVersion": "5.0", "platform": "TV",
                    "clientFormFactor": "UNKNOWN_FORM_FACTOR", "screenPixelDensity": 1
                }
            },
            "browseId": "FEhistory"
        }
        if continuation_token:
            payload["continuation"] = continuation_token
        params = {"key": get_api_key_rotated(config), "prettyPrint": "false"}
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'User-Agent': payload["context"]["client"]["userAgent"],
            'Origin': 'https://www.youtube.com', 'Referer': 'https://www.youtube.com/'
        }
        try:
            resp = requests.post(endpoint, json=payload, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except:
            return None

    def extract_history_data_with_continuation(json_data, max_videos):
        videos = []
        continuation_token = None
        if not json_data: return videos, continuation_token
        try:
            continuation_token = find_continuation_token(json_data)
            contents = json_data.get('contents', {})
            if 'tvBrowseRenderer' in contents:
                tv = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
                if 'gridRenderer' in tv:
                    for item in tv['gridRenderer'].get('items', []):
                        if len(videos) >= max_videos: break
                        if 'tileRenderer' in item:
                            data = parse_history_tile_renderer(item['tileRenderer'])
                            if data: videos.append(data)
                elif 'sectionListRenderer' in tv:
                    for section in tv['sectionListRenderer'].get('contents', []):
                        if len(videos) >= max_videos: break
                        for item in section.get('itemSectionRenderer', {}).get('contents', []):
                            if len(videos) >= max_videos: break
                            if 'tileRenderer' in item:
                                data = parse_history_tile_renderer(item['tileRenderer'])
                                if data: videos.append(data)
            if 'onResponseReceivedActions' in json_data:
                for action in json_data['onResponseReceivedActions']:
                    if 'appendContinuationItemsAction' in action:
                        for item in action['appendContinuationItemsAction'].get('items', []):
                            if len(videos) >= max_videos: break
                            if 'tileRenderer' in item:
                                data = parse_history_tile_renderer(item['tileRenderer'])
                                if data: videos.append(data)
                            elif 'continuationItemRenderer' in item and not continuation_token:
                                continuation_token = item['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        except Exception as e:
            print(f"Extract history error: {e}")
        return videos, continuation_token

    def find_continuation_token(json_data):
        try:
            if 'continuationContents' in json_data:
                return json_data['continuationContents'].get('gridContinuation', {}).get('continuations', [{}])[0].get('nextContinuationData', {}).get('continuation')
            if 'onResponseReceivedActions' in json_data:
                for action in json_data['onResponseReceivedActions']:
                    if 'appendContinuationItemsAction' in action:
                        for item in action['appendContinuationItemsAction'].get('items', []):
                            if 'continuationItemRenderer' in item:
                                return item['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
            contents = json_data.get('contents', {})
            if 'tvBrowseRenderer' in contents:
                content = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']
                if 'continuationItemRenderer' in content:
                    return content['continuationItemRenderer'].get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
        except:
            pass
        return None

    def parse_history_tile_renderer(tile):
        try:
            video_id = tile.get('onSelectCommand', {}).get('watchEndpoint', {}).get('videoId', 'unknown')
            if video_id == 'unknown': return None
            title = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('title', {}).get('simpleText', 'No Title')
            author = "Unknown"
            try:
                lines = tile['metadata']['tileMetadataRenderer'].get('lines', [])
                if lines:
                    items = lines[0].get('lineRenderer', {}).get('items', [])
                    if items:
                        text = items[0].get('lineItemRenderer', {}).get('text', {}).get('runs', [{}])
                        if text: author = text[0].get('text', 'Unknown')
            except: pass
            views = 0
            duration = "0:00"
            watched_at = ""
            try:
                overlays = tile.get('header', {}).get('tileHeaderRenderer', {}).get('thumbnailOverlays', [])
                if overlays:
                    duration = overlays[0].get('thumbnailOverlayTimeStatusRenderer', {}).get('text', {}).get('simpleText', '0:00')
            except: pass
            try:
                lines = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('lines', [])
                if len(lines) > 1:
                    items = lines[1].get('lineRenderer', {}).get('items', [])
                    if items and len(items) > 2:
                        watched_at = items[2].get('lineItemRenderer', {}).get('text', {}).get('simpleText', '')
            except: pass
            return {
                'video_id': video_id, 'title': title, 'author': author,
                'views': views, 'duration': duration, 'watched_at': watched_at
            }
        except: return None

    def extract_innertube_data(json_data, max_videos):
        videos = []
        if not json_data: return videos
        try:
            contents = json_data.get('contents', {})
            if 'tvBrowseRenderer' in contents:
                sections = contents['tvBrowseRenderer']['content']['tvSurfaceContentRenderer']['content']['sectionListRenderer']['contents']
                for section in sections:
                    if len(videos) >= max_videos: break
                    if 'shelfRenderer' in section:
                        items = section['shelfRenderer'].get('content', {}).get('horizontalListRenderer', {}).get('items', [])
                        for item in items:
                            if len(videos) >= max_videos: break
                            if 'tileRenderer' in item:
                                data = parse_tile_renderer(item['tileRenderer'])
                                if data: videos.append(data)
            return videos[:max_videos]
        except: return videos

    def parse_tile_renderer(tile):
        try:
            video_id = tile.get('onSelectCommand', {}).get('watchEndpoint', {}).get('videoId', 'unknown')
            if video_id == 'unknown': return None
            title = tile.get('metadata', {}).get('tileMetadataRenderer', {}).get('title', {}).get('simpleText', 'No Title')
            author = "Unknown"
            try:
                lines = tile['metadata']['tileMetadataRenderer'].get('lines', [])
                if lines:
                    items = lines[0].get('lineRenderer', {}).get('items', [])
                    if items:
                        text = items[0].get('lineItemRenderer', {}).get('text', {}).get('runs', [])
                        if text: author = text[0].get('text', 'Unknown')
            except: pass
            return {'video_id': video_id, 'title': title, 'author': author}
        except: return None

    def generate_cpn():
        return ''.join(random.choices(string.ascii_letters + string.digits, k=16))