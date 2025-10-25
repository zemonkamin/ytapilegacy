import os
import time
import threading
import json
from datetime import datetime, timedelta

# Simple in-memory cache tracking for video requests
video_request_counts = {}
video_cache_lock = threading.Lock()

# Path to the video views tracking file
VIEWS_TRACKING_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'temp', 'video_views.json')

def get_cache_path(video_id, quality=None):
    """Get the file path for cached video"""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'temp')
    if quality:
        filename = f"{video_id}_{quality}.mp4"
    else:
        filename = f"{video_id}.mp4"
    return os.path.join(cache_dir, filename)

def is_video_cached(video_id, quality=None):
    """Check if video is already cached with the specific quality"""
    cache_path = get_cache_path(video_id, quality)
    return os.path.exists(cache_path)

def get_cached_video_size(video_id, quality=None):
    """Get the size of cached video file"""
    cache_path = get_cache_path(video_id, quality)
    if os.path.exists(cache_path):
        return os.path.getsize(cache_path)
    return 0

def record_video_request(video_id):
    """Record a video request for frequency tracking"""
    with video_cache_lock:
        now = time.time()
        if video_id not in video_request_counts:
            video_request_counts[video_id] = []
        
        # Add current request timestamp
        video_request_counts[video_id].append(now)
        
        # Remove requests older than 1 hour
        cutoff = now - 3600  # 1 hour
        video_request_counts[video_id] = [
            timestamp for timestamp in video_request_counts[video_id] 
            if timestamp > cutoff
        ]
        
        # Return request count in the last hour
        return len(video_request_counts[video_id])

def should_cache_video(video_id, request_threshold=5):
    """Determine if video should be cached based on request frequency"""
    request_count = record_video_request(video_id)
    return request_count >= request_threshold

def load_video_views():
    """Load video views from the tracking file"""
    try:
        if os.path.exists(VIEWS_TRACKING_FILE):
            with open(VIEWS_TRACKING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading video views: {e}")
    return {}

def save_video_views(views_data):
    """Save video views to the tracking file"""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(VIEWS_TRACKING_FILE), exist_ok=True)
        with open(VIEWS_TRACKING_FILE, 'w', encoding='utf-8') as f:
            json.dump(views_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving video views: {e}")

def increment_video_view_count(video_id):
    """Increment the view count for a video"""
    with video_cache_lock:
        views_data = load_video_views()
        if video_id not in views_data:
            views_data[video_id] = {
                'views': 0,
                'last_accessed': time.time()
            }
        views_data[video_id]['views'] += 1
        views_data[video_id]['last_accessed'] = time.time()
        save_video_views(views_data)

def get_temp_folder_size():
    """Get the total size of the temp folder in bytes"""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'temp')
    if not os.path.exists(cache_dir):
        return 0
    
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(cache_dir):
        for filename in filenames:
            if filename.endswith('.mp4'):
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except Exception:
                    pass
    return total_size

def cleanup_cache_if_needed(max_size_bytes):
    """Clean up cache if it exceeds the maximum size"""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'temp')
    if not os.path.exists(cache_dir):
        return
    
    current_size = get_temp_folder_size()
    if current_size <= max_size_bytes:
        return
    
    # Load video views data
    views_data = load_video_views()
    
    # Get all cached video files with their sizes and last access times
    video_files = []
    for filename in os.listdir(cache_dir):
        if filename.endswith('.mp4'):
            filepath = os.path.join(cache_dir, filename)
            try:
                file_size = os.path.getsize(filepath)
                last_modified = os.path.getmtime(filepath)
                
                # Extract video_id from filename
                video_id = filename.replace('.mp4', '')
                if '_' in video_id:
                    video_id = video_id.split('_')[0]
                
                # Get view count or use 0 if not tracked
                view_count = views_data.get(video_id, {}).get('views', 0)
                last_accessed = views_data.get(video_id, {}).get('last_accessed', last_modified)
                
                video_files.append({
                    'filepath': filepath,
                    'filename': filename,
                    'size': file_size,
                    'video_id': video_id,
                    'view_count': view_count,
                    'last_accessed': last_accessed
                })
            except Exception as e:
                print(f"Error getting file info for {filename}: {e}")
    
    # Sort by view count (ascending) and last accessed time (ascending)
    # This will prioritize deleting least viewed and least recently accessed files
    video_files.sort(key=lambda x: (x['view_count'], x['last_accessed']))
    
    # Calculate how many files to delete (10% of total files)
    files_to_delete = max(1, len(video_files) // 10)
    
    # Delete the least popular files
    bytes_freed = 0
    deleted_count = 0
    
    for video_file in video_files:
        if deleted_count >= files_to_delete:
            break
            
        try:
            os.remove(video_file['filepath'])
            bytes_freed += video_file['size']
            deleted_count += 1
            print(f"Removed cached video file: {video_file['filename']} ({video_file['size']} bytes)")
        except Exception as e:
            print(f"Error removing cached video file {video_file['filename']}: {e}")
    
    print(f"Cache cleanup completed. Deleted {deleted_count} files, freed {bytes_freed} bytes.")

def check_and_cleanup_cache(max_size_mb=5120, cleanup_threshold_mb=100):
    """Check if cache needs cleanup and perform it if necessary
    Default max_size_mb is 5120 (5GB)"""
    max_size_bytes = max_size_mb * 1024 * 1024
    # cleanup_threshold_bytes = cleanup_threshold_mb * 1024 * 1024
    
    current_size = get_temp_folder_size()
    
    # If we're over the 5GB limit, trigger cleanup
    if current_size > max_size_bytes:
        cleanup_cache_if_needed(max_size_bytes)