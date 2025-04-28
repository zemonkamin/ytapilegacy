<?php
// Конфигурационный файл

// Настройки качества видео
$config = array(
    // API ключ от YouTubeAPI
   'api_key' => 'AIzaSyCve8OQH2HNIQ2oBwt6udvDoe0gvs5aTf',

    // Ссылка на Invidious
    'invidious_url' => 'inv1.nadeko.net',

    // Ссылка на oldyoutube
    'oldyoutube_url' => 'http://sonyericsson.org:64',

    // Ссылка на хост
    'url' => 'https://qqq.bccst.ru/youtube',

    // Качество видео по умолчанию
    'default_quality' => '360',
    
    // Доступные качества видео
    'available_qualities' => array(
        '144',
        '240',
        '360',
        '480',
        '720',
        '1080',
        '1440',
        '2160'
    ),
    
    // API ключ YouTube
    'youtube_api_key' => 'AIzaSyDK9_faQma3ZKlVZCI8W8tJWicE0HpRcCk',
    
    // Invidious инстанс
    'invidious_instance' => 'inv1.nadeko.net',
    
    // Максимальное количество результатов поиска
    'max_search_results' => 10,
    
    // Максимальное количество популярных видео
    'max_popular_videos' => 10,
	
	// Таймер на загрузку прямой ссылки видео
    'video_timer' => 10,
    
    // Настройки прокси
    'use_thumbnail_proxy' => true,          // Использовать прокси для превью видео
    'use_channel_thumbnail_proxy' => true,  // Использовать прокси для иконок каналов
    'use_video_proxy' => false,              // Использовать прокси для видео
    
    // Метод получения видео
    'video_source' => 'oldyoutube',          // 'invidious' - использовать Invidious, 'direct' - использовать прямые ссылки через Python-скрипт, 'oldyoutube' - использование oldyoutube layout
    
    // Путь к Python в виртуальном окружении (используется только при video_source = 'direct')
    'python_path' => 'topvenv/bin/python'
);

// Функция для проверки валидности качества видео
function is_valid_quality($quality) {
    global $config;
    return in_array($quality, $config['available_qualities']);
}

// Функция для получения следующего доступного качества
function get_next_quality($current_quality) {
    global $config;
    $qualities = $config['available_qualities'];
    $current_index = array_search($current_quality, $qualities);
    
    if ($current_index === false) {
        return $config['default_quality'];
    }
    
    $next_index = $current_index + 1;
    return isset($qualities[$next_index]) ? $qualities[$next_index] : $current_quality;
}

// Функция для получения предыдущего доступного качества
function get_previous_quality($current_quality) {
    global $config;
    $qualities = $config['available_qualities'];
    $current_index = array_search($current_quality, $qualities);
    
    if ($current_index === false) {
        return $config['default_quality'];
    }
    
    $prev_index = $current_index - 1;
    return isset($qualities[$prev_index]) ? $qualities[$prev_index] : $current_quality;
}
?>