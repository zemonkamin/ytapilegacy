from flask import Blueprint, request, jsonify, redirect
import requests
import json
from urllib.parse import quote
from utils.helpers import get_channel_thumbnail

# Create blueprint
search_bp = Blueprint('search', __name__)

def setup_search_routes(config):
    """Configure search routes with application config"""
    
    @search_bp.route('/get_search_videos.php', methods=['GET'])
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
                channelThumbnail = get_channel_thumbnail(videoInfo['channelId'], apikey, config)
                searchResults.append({
                    'title': videoInfo['title'],
                    'author': videoInfo['channelTitle'],
                    'video_id': videoId,
                    'thumbnail': f"{config['mainurl']}thumbnail/{videoId}",
                    'channel_thumbnail': channelThumbnail,
                })
            return jsonify(searchResults)
        except Exception as e:
            print('Error in get_search_videos:', e)
            return jsonify({'error': 'Internal server error'})

    @search_bp.route('/get_top_videos.php', methods=['GET'])
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

    @search_bp.route('/get_search_suggestions.php', methods=['GET'])
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