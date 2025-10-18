import os
import subprocess
import json
import requests
import re
from urllib.parse import quote
from datetime import datetime
import random

# We'll need to pass config to this function or import it
# For now, we'll modify the function signature to accept config

def get_script_directory():
    """Возвращает путь к папке, в которой находится текущий скрипт."""
    return os.path.dirname(os.path.abspath(__file__))

def get_yt_dlp_executable():
    """Определяет операционную систему и возвращает путь к исполняемому файлу yt-dlp."""
    script_dir = get_script_directory()
    
    if os.name == 'nt':  # Windows
        executable_name = 'yt-dlp.exe'
    else:  # Linux and others
        executable_name = 'yt-dlp_linux'
    
    # Формируем полный путь к файлу в папке assets
    assets_dir = os.path.join(script_dir, '..', 'assets')
    executable_path = os.path.join(assets_dir, executable_name)
    
    # Проверяем существование файла в папке assets
    if os.path.isfile(executable_path):
        return executable_path
    else:
        # Если файл не найден в папке assets, проверяем в папке со скриптом
        executable_path = os.path.join(script_dir, '..', executable_name)
        if os.path.isfile(executable_path):
            return executable_path
        else:
            # Если файл не найден, используем имя файла (будет искаться в PATH)
            return executable_name

def get_cookies_files():
    """Получает список файлов cookies из папки cookies и корневой директории."""
    script_dir = get_script_directory()
    cookies_files = []
    
    # Проверяем папку cookies
    cookies_dir = os.path.join(script_dir, '..', 'cookies')
    if os.path.isdir(cookies_dir):
        for file in os.listdir(cookies_dir):
            if file.startswith('cookies_') and file.endswith('.txt'):
                cookies_files.append(os.path.join(cookies_dir, file))
    
    # Проверяем корневую директорию на наличие cookies файлов
    root_cookies = os.path.join(script_dir, '..', 'cookies.txt')
    if os.path.isfile(root_cookies):
        cookies_files.append(root_cookies)
    
    # Также проверяем 1cookies.txt и 2cookies.txt в корневой директории
    for extra_cookie in ['1cookies.txt', '2cookies.txt']:
        extra_cookie_path = os.path.join(script_dir, '..', extra_cookie)
        if os.path.isfile(extra_cookie_path):
            cookies_files.append(extra_cookie_path)
    
    return cookies_files

def select_random_cookie_file():
    """Выбирает случайный файл cookies из доступных."""
    cookies_files = get_cookies_files()
    if cookies_files:
        selected_cookie = random.choice(cookies_files)
        print(f"[DEBUG] Using cookies file: {selected_cookie}")
        return selected_cookie
    return None

def run_yt_dlp(args, cookie_file=None):
    """Запускает yt-dlp с указанными аргументами и возвращает вывод."""
    executable = get_yt_dlp_executable()
    
    # Если файл cookie не указан, выбираем случайный
    if not cookie_file:
        cookie_file = select_random_cookie_file()
    elif os.path.isfile(cookie_file):
        print(f"[DEBUG] Using specified cookies file: {cookie_file}")
    
    # Добавляем cookies.txt если он существует
    if cookie_file and os.path.isfile(cookie_file):
        args = ['--cookies', cookie_file] + args
    
    try:
        result = subprocess.run(
            [executable] + args,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'  # Игнорируем ошибки декодирования
        )
        
        if result.returncode != 0:
            print(f"[ERROR] yt-dlp exited with code {result.returncode}")
            print(f"[ERROR] stderr: {result.stderr}")
            return None
            
        return result.stdout.strip()
    
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Ошибка при выполнении {executable}: {e}")
        return None
    except FileNotFoundError:
        print(f"[ERROR] {executable} не найден. Убедитесь, что он находится в той же папке что и скрипт или добавлен в PATH.")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error in run_yt_dlp: {e}")
        return None

def get_available_formats(video_id, cookie_file=None):
    """Получает список доступных форматов видео."""
    url = f'https://www.youtube.com/watch?v={video_id}'
    formats_output = run_yt_dlp(['--dump-json', url], cookie_file)
    if not formats_output:
        return None
    
    try:
        video_info = json.loads(formats_output)
        formats = video_info.get('formats', [])
        return formats
    except json.JSONDecodeError:
        print("[ERROR] Не удалось разобрать JSON от yt-dlp.")
        return None

def get_proxy_url(url, use_proxy):
    """Получает прокси URL если включено проксирование."""
    if not use_proxy:
        return url
    if url.startswith('https://i.ytimg.com'):
        # Assuming config is imported or passed as parameter
        return f"https://qqq.bccst.ru/youtube/image-proxy.php?url={url}"
    return url

def get_video_proxy_url(url, use_proxy):
    """Получает прокси URL для видео если включено проксирование."""
    if not use_proxy:
        return url
    # Assuming config is imported or passed as parameter
    return f"https://qqq.bccst.ru/youtube/video-proxy.php?url={url}"

def get_final_url(url):
    """Получает финальный URL после всех редиректов."""
    try:
        r = requests.get(url, allow_redirects=True, timeout=30)  # Assuming timeout from config
        return r.url
    except Exception as e:
        print('get_final_url error:', e)
        return None

def url_exists(url):
    """Проверяет существует ли URL."""
    try:
        r = requests.head(url, timeout=30)  # Assuming timeout from config
        return r.status_code == 200
    except Exception as e:
        print('url_exists error:', e)
        return False

def get_channel_thumbnail(channel_id, api_key, config):
    """Get channel thumbnail with multiple fallback methods"""
    if not config.get('fetch_channel_thumbnails', False):
        return ''
    
    print(f"DEBUG: Getting channel thumbnail for channel_id: {channel_id}")
    
    # Method 1: Try YouTube API to get channel thumbnail
    try:
        r = requests.get(
            f"https://www.googleapis.com/youtube/v3/channels?id={channel_id}&key={api_key}&part=snippet", 
            timeout=config.get('request_timeout', 30)
        )
        r.raise_for_status()
        data = r.json()
        
        print(f"DEBUG: API response: {json.dumps(data, ensure_ascii=False)[:200]}...")
        
        if data.get('items') and data['items']:
            # Get channel thumbnail from channel data
            channel_snippet = data['items'][0]['snippet']
            thumbnail_url = channel_snippet['thumbnails']['default']['url']
            print(f"DEBUG: Found channel thumbnail: {thumbnail_url}")
            return thumbnail_url
        else:
            print("DEBUG: No items in API response")
                
    except Exception as e:
        print(f'Error getting channel thumbnail from API for {channel_id}: {e}')
    
    # Fallback
    return 'https://yt3.ggpht.com/a/default-user=s88-c-k-c0x00ffffff-no-rj'