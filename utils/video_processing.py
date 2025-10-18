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
    """Получает прямую ссылку на видео и аудио для выбранного разрешения."""
    formats = get_available_formats(video_id, cookie_file)
    if not formats:
        return None, None
    
    url = f'https://www.youtube.com/watch?v={video_id}'
    height = int(resolution)
    
    # Находим видео-формат с нужным разрешением (видео only, без аудио)
    matching_formats = [
        f for f in formats 
        if f.get('height') == height and 
        f.get('vcodec') != 'none' and 
        f.get('acodec') == 'none' and 
        f.get('protocol', '').startswith('https')
    ]
    
    video_url = None
    if matching_formats:
        best_format = max(matching_formats, key=lambda f: f.get('tbr', 0))
        format_id = best_format['format_id']
        print(f"[DEBUG] Выбран формат видео: ID={format_id}, {resolution}p, tbr={best_format.get('tbr', 'N/A')}")
        video_url = run_yt_dlp(['-f', format_id, '--get-url', url], cookie_file)
    else:
        print(f"[DEBUG] Формат {resolution}p не найден")
    
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
    
    audio_url = None
    if audio_formats:
        best_audio = max(audio_formats, key=lambda f: f.get('tbr', 0))
        format_id = best_audio['format_id']
        print(f"[DEBUG] Выбран формат аудио: ID={format_id}, tbr={best_audio.get('tbr', 'N/A')}")
        audio_url = run_yt_dlp(['-f', format_id, '--get-url', url], cookie_file)
    
    # If we couldn't get separate streams, try to get a combined stream
    if not video_url or not audio_url:
        print("[DEBUG] Не удалось получить отдельные потоки, пробуем комбинированный поток")
        combined_formats = [
            f for f in formats 
            if f.get('vcodec') != 'none' and 
            f.get('acodec') != 'none' and 
            f.get('protocol', '').startswith('https') and
            f.get('height', 0) <= height
        ]
        
        if combined_formats:
            # Sort by quality (height) in descending order but limit to requested height
            best_combined = max(combined_formats, key=lambda f: f.get('height', 0))
            format_id = best_combined['format_id']
            print(f"[DEBUG] Найден комбинированный поток: {best_combined.get('height', 'N/A')}p, ID={format_id}")
            video_url = run_yt_dlp(['-f', format_id, '--get-url', url], cookie_file)
            audio_url = None  # Combined stream contains both video and audio
    
    return video_url, audio_url

def get_video_url(video_id, quality_choice, cookie_file=None):
    """Основная функция для получения URL в зависимости от выбора качества."""
    if quality_choice == 'standard':
        return get_standard_quality_url(video_id, cookie_file)
    else:
        return get_specific_quality_url(video_id, quality_choice, cookie_file)

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