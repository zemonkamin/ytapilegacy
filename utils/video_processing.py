import json
import requests
import re
from urllib.parse import quote
from datetime import datetime
from .helpers import run_yt_dlp, get_available_formats

def get_direct_video_url(video_id, quality=None, cookie_file=None):
    """Получает прямую ссылку на видео через yt-dlp бинарник."""
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        format_option = 'best' if not quality else f'best[height<={quality}]'
        
        # Получаем информацию о видео в формате JSON
        info_output = run_yt_dlp(['--dump-json', '--format', format_option, url], cookie_file)
        
        if not info_output:
            print(f"No info found for video_id: {video_id}, quality: {quality}")
            return None
        
        try:
            info = json.loads(info_output)
            selected_format = info.get('url')
            formats = info.get('formats', [])
            print(f"Video ID: {video_id}, Quality requested: {quality}")
            print(f"Selected format URL: {selected_format}")
            print(f"Available formats: {[f.get('height', 'N/A') for f in formats if f.get('height')]}")
            
            if not selected_format:
                print(f"No URL found for video_id: {video_id}, quality: {quality}")
                return None
            
            return selected_format
        except json.JSONDecodeError:
            print("[ERROR] Не удалось разобрать JSON от yt-dlp.")
            return None
            
    except Exception as e:
        print(f"Unexpected error in get_direct_video_url for video_id {video_id}, quality {quality}: {str(e)}")
        return None

def get_real_direct_video_url(video_id, cookie_file=None):
    """Возвращает прямую ссылку на видео через yt-dlp бинарник (без прокси и без /direct_url)."""
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        
        # Получаем информацию о видео в формате JSON
        info_output = run_yt_dlp(['--dump-json', '--format', 'best', url], cookie_file)
        
        if not info_output:
            print(f"No info found for video_id: {video_id}")
            return None
        
        try:
            info = json.loads(info_output)
            return info.get('url')
        except json.JSONDecodeError:
            print("[ERROR] Не удалось разобрать JSON от yt-dlp.")
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_standard_quality_url(video_id, cookie_file=None):
    """Получает прямую ссылку на видео в стандартном качестве (готовый поток с видео+аудио)."""
    url = f'https://www.youtube.com/watch?v={video_id}'
    print("[DEBUG] Получение стандартного качества (готовый поток с видео+аудио)")
    
    # Ищем формат, который содержит и видео и аудио вместе (обычно это 360p или 480p)
    formats = get_available_formats(video_id, cookie_file)
    if not formats:
        return None, None
    
    # Ищем форматы с видео и аудио вместе, предпочитая 360p
    combined_formats = [
        f for f in formats 
        if f.get('vcodec') != 'none' and 
        f.get('acodec') != 'none' and 
        f.get('protocol', '').startswith('https') and
        f.get('height', 0) <= 480  # Ограничиваем максимальным качеством для комбинированных потоков
    ]
    
    if combined_formats:
        # Сортируем по качеству (высоте) в порядке убывания, но ограничиваем 480p
        best_combined = max(combined_formats, key=lambda f: f.get('height', 0))
        format_id = best_combined['format_id']
        height = best_combined.get('height', 'N/A')
        print(f"[DEBUG] Найден комбинированный поток: {height}p, ID={format_id}")
        
        video_url = run_yt_dlp(['-f', format_id, '--get-url', url], cookie_file)
        return video_url, None  # Для стандартного качества возвращаем только одну ссылку
    else:
        print("[DEBUG] Комбинированные потоки не найдены, пробуем лучший доступный")
        # Если комбинированных потоков нет, используем лучший доступный
        video_url = run_yt_dlp(['-f', 'best', '--get-url', url], cookie_file)
        return video_url, None

def get_specific_quality_url(video_id, resolution, cookie_file=None):
    """Получает прямую ссылку на комбинированный поток (видео+аудио) для выбранного разрешения через формат-селектор yt-dlp."""
    url = f'https://www.youtube.com/watch?v={video_id}'
    height = int(resolution)
    
    # Используем формат-селектор для получения комбинированного потока с нужным качеством
    # Формат: [height=качество][vcodec!=none][acodec!=none] - выбирает формат с нужной высотой, где есть и видео и аудио
    format_selector = f'[height={height}][vcodec!=none][acodec!=none]'
    
    print(f"[DEBUG] Получение комбинированного потока {height}p через формат-селектор: {format_selector}")
    video_url = run_yt_dlp(['--get-url', '-f', format_selector, url], cookie_file)
    
    if video_url:
        print(f"[DEBUG] Получен комбинированный поток {height}p")
        return video_url, None  # Возвращаем комбинированный поток (audio_url = None)
    else:
        print(f"[DEBUG] Комбинированный поток {height}p не найден через формат-селектор")
        return None, None

def get_video_url(video_id, quality_choice, cookie_file=None):
    """Основная функция для получения URL в зависимости от выбора качества."""
    if quality_choice == 'standard':
        return get_standard_quality_url(video_id, cookie_file)
    else:
        return get_specific_quality_url(video_id, quality_choice, cookie_file)

def is_m3u8_url(url):
    """Проверяет, является ли URL m3u8 (HLS поток)."""
    if not url:
        return False
    url_lower = url.lower()
    return '.m3u8' in url_lower or 'manifest/hls_playlist' in url_lower or 'hls_playlist' in url_lower

def get_video_info_ytdlp(video_id, cookie_file=None):
    """Получает информацию о видео через yt-dlp."""
    try:
        url = f'https://www.youtube.com/watch?v={video_id}'
        
        # Получаем информацию о видео в формате JSON
        info_output = run_yt_dlp(['--dump-json', '--format', 'best', url], cookie_file)
        
        if not info_output:
            print(f"No info found for video_id: {video_id}")
            return None
        
        try:
            info = json.loads(info_output)
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
        except json.JSONDecodeError:
            print("[ERROR] Не удалось разобрать JSON от yt-dlp.")
            return None
    except Exception as e:
        print('Error in get_video_info_ytdlp:', e)
        return None