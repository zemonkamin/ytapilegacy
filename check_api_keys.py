import json
import requests
import time
import shutil
import os
from datetime import datetime

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config, config_path):
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def make_backup(config_path):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dirn, base = os.path.split(config_path)
    name, ext = os.path.splitext(base)
    backup_name = f"{name}_backup_{ts}{ext}"
    backup_path = os.path.join(dirn or '.', backup_name)
    shutil.copy2(config_path, backup_path)
    return backup_path

def test_api_key(api_key, test_query="music", max_results=5):
    try:
        url = f"https://www.googleapis.com/youtube/v3/search"
        params = {
            'part': 'snippet',
            'q': test_query,
            'maxResults': max_results,
            'key': api_key
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'items' in data:
                return True, f"Success: Received {len(data['items'])} results"
            else:
                return False, "Error: No items in response"
        else:
            try:
                error_data = response.json()
                if 'error' in error_data:
                    error_message = error_data['error'].get('message', 'Unknown error')
                    return False, f"Error {response.status_code}: {error_message}"
                else:
                    return False, f"Error {response.status_code}: {response.text}"
            except:
                return False, f"Error {response.status_code}: {response.text}"
                
    except requests.exceptions.Timeout:
        return False, "Error: Request timed out"
    except requests.exceptions.RequestException as e:
        return False, f"Error: Request failed - {str(e)}"
    except Exception as e:
        return False, f"Error: Unexpected error - {str(e)}"

def check_all_api_keys(config_path, output_file, interactive=True):
    config = load_config(config_path)
    api_keys = config.get('api_keys', [])
    
    if not api_keys:
        print("No API keys found in config file")
        return
    
    print(f"Found {len(api_keys)} API keys. Testing each one...\n")
    
    working_keys = []
    non_working_keys = []
    
    for i, api_key in enumerate(api_keys):
        print(f"Testing API key {i+1}/{len(api_keys)}...")
        is_working, message = test_api_key(api_key)
        
        if is_working:
            working_keys.append((api_key, message))
            print(f"  ✓ Working - {message}")
        else:
            non_working_keys.append((api_key, message))
            print(f"  ✗ Not working - {message}")
        
        time.sleep(0.5)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("YouTube API Keys Report\n")
        f.write("=" * 50 + "\n\n")
        
        f.write(f"Total keys tested: {len(api_keys)}\n")
        f.write(f"Working keys: {len(working_keys)}\n")
        f.write(f"Non-working keys: {len(non_working_keys)}\n\n")
        
        f.write("WORKING KEYS:\n")
        f.write("-" * 20 + "\n")
        for i, (key, message) in enumerate(working_keys, 1):
            f.write(f"{i}. {key}\n")
            f.write(f"   Status: {message}\n\n")
        
        f.write("NON-WORKING KEYS:\n")
        f.write("-" * 20 + "\n")
        for i, (key, message) in enumerate(non_working_keys, 1):
            f.write(f"{i}. {key}\n")
            f.write(f"   Status: {message}\n\n")
    
    print(f"\nReport generated: {output_file}")
    print(f"Working keys: {len(working_keys)}")
    print(f"Non-working keys: {len(non_working_keys)}")
    
    if non_working_keys and interactive:
        bad_keys = [k for k, _ in non_working_keys]
        print("\nНайдены неработающие ключи:")
        for k, msg in non_working_keys:
            print(f" - {k} ({msg})")
        answer = input("\nУбрать их из файла конфигурации? (y/N): ").strip().lower()
        if answer in ('y', 'yes', 'д', 'да'):
            try:
                backup_path = make_backup(config_path)
                print(f"Бэкап оригинального файла создан: {backup_path}")
                
                new_keys = [k for k in api_keys if k not in bad_keys]
                config['api_keys'] = new_keys
                save_config(config, config_path)
                
                print(f"Удалено {len(api_keys) - len(new_keys)} ключ(ей). Файл обновлён: {config_path}")
            except Exception as e:
                print(f"Ошибка при создании бэкапа или сохранении файла: {e}")
        else:
            print("Ключи не удалены.")
    elif not non_working_keys:
        print("Все ключи рабочие — изменений не требуется.")
    else:
        print("Интерактивный режим выключен — изменения не применялись.")

if __name__ == "__main__":
    config_path = "config.json"
    output_file = "api_keys_report.txt"
    
    check_all_api_keys(config_path, output_file, interactive=True)