from flask import Blueprint, request, jsonify, redirect
import requests
from urllib.parse import quote
from utils.helpers import get_channel_thumbnail, get_proxy_url, get_api_key, get_api_key_rotated, replace_youtube_thumbnail_domain

# Create blueprint
channel_bp = Blueprint('channel', __name__)

def setup_channel_routes(config):
    """Configure channel routes with application config"""
    
    @channel_bp.route('/get_author_videos.php', methods=['GET'])
    def get_author_videos():
        try:
            author = request.args.get('author')
            count = request.args.get('count', '50')
            apikey = get_api_key_rotated(config)

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

    @channel_bp.route('/get_author_videos_by_id.php', methods=['GET'])
    def get_author_videos_by_id():
        try:
            channel_id = request.args.get('channel_id')
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            apikey = get_api_key_rotated(config)

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
                        channelThumbnail = get_channel_thumbnail(channel_id, apikey, config)
                        videos.append({
                            'title': videoInfo['title'],
                            'author': channel_info['snippet']['title'],
                            'video_id': videoId,
                            'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                            'channel_thumbnail': replace_youtube_thumbnail_domain(get_proxy_url(channelThumbnail, config['use_channel_thumbnail_proxy'])),
                        })
                        totalVideos += 1
                nextPageToken = videos_data.get('nextPageToken', '')
                if not nextPageToken:
                    break

            result = {
                'channel_info': {
                    'title': channel_info['snippet']['title'],
                    'description': channel_info['snippet']['description'],
                    'thumbnail': replace_youtube_thumbnail_domain(get_proxy_url(channel_info['snippet']['thumbnails']['high']['url'], config['use_channel_thumbnail_proxy'])),
                    'banner': replace_youtube_thumbnail_domain(get_proxy_url(channel_info.get('brandingSettings', {}).get('image', {}).get('bannerExternalUrl', ''), config['use_thumbnail_proxy'])),
                    'subscriber_count': channel_info['statistics']['subscriberCount'],
                    'video_count': channel_info['statistics']['videoCount']
                },
                'videos': videos
            }
            return jsonify(result)
        except Exception as e:
            print('Error in get_author_videos_by_id:', e)
            return jsonify({'error': 'Internal server error'})

    @channel_bp.route('/get_channel_thumbnail.php', methods=['GET'])
    def get_channel_thumbnail_api():
        try:
            video_id = request.args.get('video_id')
            apikey = get_api_key_rotated(config)

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

            channelThumbnail = get_channel_thumbnail(channelId, apikey, config)
            return jsonify({'channel_thumbnail': channelThumbnail})
        except Exception as e:
            print('Error in get_channel_thumbnail:', e)
            return jsonify({'error': 'Internal server error'})