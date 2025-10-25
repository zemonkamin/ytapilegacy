from flask import Blueprint, request, jsonify, redirect
import requests
import json
from urllib.parse import quote
from utils.helpers import get_channel_thumbnail, get_api_key, get_api_key_rotated, get_proxy_url, replace_youtube_thumbnail_domain

# Create blueprint
search_bp = Blueprint('search', __name__)

def setup_search_routes(config):
    """Configure search routes with application config"""
    
    @search_bp.route('/get_search_videos.php', methods=['GET'])
    def get_search_videos():
        try:
            query = request.args.get('query')
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            search_type = request.args.get('type', 'video')  # New parameter with default 'video'
            apikey = get_api_key_rotated(config)
            if not query:
                return jsonify({'error': 'Параметр query не указан'})
            
            # Validate search type
            valid_types = ['video', 'channel', 'playlist']
            if search_type not in valid_types:
                return jsonify({'error': f'Invalid type parameter. Must be one of: {", ".join(valid_types)}'})
            
            resp = requests.get(f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={quote(query)}&maxResults={count}&type={search_type}&key={apikey}")
            resp.raise_for_status()
            data = resp.json()
            searchResults = []
            
            for item in data.get('items', []):
                if 'id' not in item:
                    continue
                    
                itemInfo = item['snippet']
                result = None  # Initialize result
                
                # Handle different item types
                if search_type == 'video':
                    if 'videoId' not in item['id']:
                        continue
                    itemId = item['id']['videoId']
                    result = {
                        'title': itemInfo['title'],
                        'author': itemInfo['channelTitle'],
                        'video_id': itemId,
                        'thumbnail': f"{config['mainurl']}thumbnail/{itemId}",
                        'channel_thumbnail': get_channel_thumbnail(itemInfo['channelId'], apikey, config) if itemInfo.get('channelId') else '',
                    }
                elif search_type == 'channel':
                    if 'channelId' not in item['id']:
                        continue
                    itemId = item['id']['channelId']
                    result = {
                        'title': itemInfo['title'],
                        'author': itemInfo['channelTitle'],
                        'channel_id': itemId,
                        'thumbnail': itemInfo['thumbnails']['high']['url'] if 'thumbnails' in itemInfo and 'high' in itemInfo['thumbnails'] else '',
                        'channel_thumbnail': f"{config['mainurl']}channel_icon/{itemId}",
                    }
                elif search_type == 'playlist':
                    if 'playlistId' not in item['id']:
                        continue
                    itemId = item['id']['playlistId']
                    # Extract video ID from thumbnail URL if available
                    thumbnail_url = itemInfo['thumbnails']['high']['url'] if 'thumbnails' in itemInfo and 'high' in itemInfo['thumbnails'] else ''
                    video_id = ''
                    if thumbnail_url and 'i.ytimg.com/vi/' in thumbnail_url:
                        # Extract video ID from URL like https://i.ytimg.com/vi/VIDEO_ID/hqdefault.jpg
                        try:
                            video_id = thumbnail_url.split('i.ytimg.com/vi/')[1].split('/')[0]
                        except:
                            video_id = ''
                    
                    result = {
                        'title': itemInfo['title'],
                        'author': itemInfo['channelTitle'],
                        'playlist_id': itemId,
                        'thumbnail': f"{config['mainurl']}thumbnail/{video_id}" if video_id else thumbnail_url,
                        'channel_thumbnail': get_channel_thumbnail(itemInfo['channelId'], apikey, config) if itemInfo.get('channelId') else '',
                    }
                
                # Only append if we have a valid result
                if result is not None:
                    searchResults.append(result)
                
            return jsonify(searchResults)
        except Exception as e:
            print('Error in get_search_videos:', e)
            return jsonify({'error': 'Internal server error'})

    @search_bp.route('/get_top_videos.php', methods=['GET'])
    def get_top_videos():
        try:
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            apikey = get_api_key_rotated(config)
            resp = requests.get(f"https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults={count}&key={apikey}")
            resp.raise_for_status()
            data = resp.json()
            topVideos = []
            for video in data.get('items', []):
                videoInfo = video['snippet']
                videoId = video['id']
                channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey, config)
                topVideos.append({
                    'title': videoInfo['title'],
                    'author': videoInfo['channelTitle'],
                    'video_id': videoId,
                    'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                    'channel_thumbnail': channelThumbnail,
                })
            return jsonify(topVideos)
        except Exception as e:
            print('Error in get_top_videos:', e)
            return jsonify({'error': 'Internal server error'})

    @search_bp.route('/get-categories_videos.php', methods=['GET'])
    def get_categories_videos():
        try:
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            categoryId = request.args.get('categoryId')
            apikey = get_api_key_rotated(config)
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
                channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey, config)
                topVideos.append({
                    'title': videoInfo['title'],
                    'author': videoInfo['channelTitle'],
                    'video_id': videoId,
                    'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                    'channel_thumbnail': channelThumbnail,
                })
            return jsonify(topVideos)
        except Exception as e:
            print('Error in get-categories_videos:', e)
            return jsonify({'error': 'Internal server error'})

    @search_bp.route('/get-categories.php', methods=['GET'])
    def get_categories():
        try:
            region = request.args.get('region', 'US')
            apikey = get_api_key_rotated(config)
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

    @search_bp.route('/playlist', methods=['GET'])
    def get_playlist_no_id():
        return jsonify({'error': 'Playlist ID is required. Use /playlist/PLAYLIST_ID'})

    @search_bp.route('/playlist/<playlist_id>', methods=['GET'])
    def get_playlist_videos(playlist_id):
        try:
            count = int(request.args.get('count', str(config.get('default_count', 50))))
            apikey = get_api_key_rotated(config)

            if not playlist_id:
                return jsonify({'error': 'Playlist ID parameter is required'})

            # Get playlist information
            playlist_resp = requests.get(f"https://www.googleapis.com/youtube/v3/playlists?part=snippet,contentDetails&id={playlist_id}&key={apikey}", timeout=config['request_timeout'])
            playlist_resp.raise_for_status()
            playlist_data = playlist_resp.json()
            playlist_info = playlist_data['items'][0] if playlist_data.get('items') else None

            if not playlist_info:
                return jsonify({'error': 'Playlist not found'})

            # Get channel information for channel thumbnail
            channel_id = playlist_info['snippet']['channelId']
            channel_resp = requests.get(f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={channel_id}&key={apikey}", timeout=config['request_timeout'])
            channel_resp.raise_for_status()
            channel_data = channel_resp.json()
            channel_info = channel_data['items'][0] if channel_data.get('items') else None

            videos = []
            nextPageToken = ''
            totalVideos = 0

            while totalVideos < count:
                # Get playlist items
                playlist_items_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet,contentDetails&playlistId={playlist_id}&maxResults=50&key={apikey}"
                if nextPageToken:
                    playlist_items_url += f"&pageToken={nextPageToken}"
                playlist_items_resp = requests.get(playlist_items_url, timeout=config['request_timeout'])
                playlist_items_resp.raise_for_status()
                playlist_items_data = playlist_items_resp.json()

                if playlist_items_data.get('items'):
                    for item in playlist_items_data['items']:
                        if totalVideos >= count:
                            break
                        videoInfo = item['snippet']
                        videoId = item['contentDetails']['videoId']
                        channelThumbnail = get_channel_thumbnail(channel_id, apikey, config)
                        videos.append({
                            'title': videoInfo['title'],
                            'author': channel_info['snippet']['title'] if channel_info else videoInfo['channelTitle'],
                            'video_id': videoId,
                            'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                            'channel_thumbnail': channelThumbnail,
                        })
                        totalVideos += 1
                nextPageToken = playlist_items_data.get('nextPageToken', '')
                if not nextPageToken:
                    break

            # Get first video ID for playlist thumbnail
            first_video_id = None
            if playlist_items_data.get('items'):
                first_item = playlist_items_data['items'][0]
                if 'contentDetails' in first_item and 'videoId' in first_item['contentDetails']:
                    first_video_id = first_item['contentDetails']['videoId']

            result = {
                'playlist_info': {
                    'title': playlist_info['snippet']['title'],
                    'description': playlist_info['snippet']['description'],
                    'thumbnail': f"{config['mainurl']}thumbnail/{first_video_id}" if first_video_id else '',
                    'channel_title': channel_info['snippet']['title'] if channel_info else playlist_info['snippet']['channelTitle'],
                    'channel_thumbnail': replace_youtube_thumbnail_domain(get_proxy_url(channel_info['snippet']['thumbnails']['high']['url'], config['use_channel_thumbnail_proxy'])) if channel_info and 'thumbnails' in channel_info['snippet'] and 'high' in channel_info['snippet']['thumbnails'] else '',
                    'video_count': playlist_info['contentDetails']['itemCount']
                },
                'videos': videos
            }
            return jsonify(result)
        except Exception as e:
            print('Error in get_playlist_videos:', e)
            return jsonify({'error': 'Internal server error'})

    @search_bp.route('/get_search_suggestions.php', methods=['GET'])
    def get_search_suggestions():
        try:
            query = request.args.get('query')
            apikey = get_api_key_rotated(config)
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