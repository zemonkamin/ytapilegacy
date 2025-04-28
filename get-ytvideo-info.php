<?php
require_once 'config.php';
require_once 'get_channel_thumbnail.php';
require_once 'proxy_url_handler.php';

// Получаем ID видео из GET-запроса
if (isset($_GET['video_id'])) {
    $video_id = $_GET['video_id'];
    $quality = $_GET['quality'];
    $api_key = isset($_GET['apikey']) ? $_GET['apikey'] : $config['api_key'];

    // Формируем URL для запроса к YouTube API
    $api_url = "https://www.googleapis.com/youtube/v3/videos?id={$video_id}&key={$api_key}&part=snippet,contentDetails,statistics";

    // Получаем данные с помощью cURL
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $api_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $response = curl_exec($ch);
    curl_close($ch);

    // Декодируем JSON-ответ
    $data = json_decode($response, true);

    // Проверяем, есть ли данные о видео
    if (isset($data['items'][0])) {
        $video_info = $data['items'][0]['snippet'];
        $content_details = $data['items'][0]['contentDetails'];
        $statistics = $data['items'][0]['statistics'];
        $channel_id = $video_info['channelId'];

        // Получаем иконку канала
        $channel_thumbnail = getChannelThumbnail($channel_id, $api_key);

        // Формируем URL для встраивания видео
        $embed_url = "https://www.youtube.com/embed/{$video_id}";
        
        // Получаем прямую ссылку на видео в зависимости от настроек
        $final_video_url = '';
        if ($config['video_source'] === 'invidious') {
            $video_url = "https://" . $config['invidious_url'] . '/embed/' . $video_id . '?raw=1&quality=' . $quality;
            $final_video_url = get_final_url($video_url);
        } elseif ($config['video_source'] === 'oldyoutube') {
            // Пытаемся получить ссылку с таймаутом 10 секунд
            $video_url = $config['oldyoutube_url'] . '/get_video?video_id=' . $video_id . '/mp4%27,%27/exp_hd?video_id=' . $video_id;
            $final_video_url = get_final_url($video_url, $config['video_timer']);
            
            // Если не получили ссылку, используем резервный вариант
            if (empty($final_video_url)) {
                $base_url = rtrim($config['oldyoutube_url'], '/');
                $final_video_url = $base_url . '/assets/' . $video_id . '.mp4';
                
                // Проверяем доступность резервного URL
                if (!url_exists($final_video_url)) {
                    $final_video_url = ''; // Если резервный URL тоже недоступен
                }
            }
        } else {
            // Используем Python-скрипт для получения прямой ссылки
            $command = escapeshellcmd($config['python_path'] . ' get_video_url.py ' . escapeshellarg($video_id));
            $output = shell_exec($command);
            preg_match('/Direct video URL: (https?:\/\/[^\s]+)/', $output, $matches);
            $video_url = $matches[1] ?? null;
            if ($video_url) {
                $final_video_url = get_final_url($video_url);
            }
        }
        
        // Получаем комментарии
        $comments_api_url = "https://www.googleapis.com/youtube/v3/commentThreads?key={$api_key}&textFormat=plainText&part=snippet&videoId={$video_id}&maxResults=5";
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $comments_api_url);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        $comments_response = curl_exec($ch);
        curl_close($ch);
        
        // Декодируем JSON-ответ комментариев
        $comments_data = json_decode($comments_response, true);
        $comments = [];

        // Извлекаем комментарии
        if (isset($comments_data['items'])) {
            foreach ($comments_data['items'] as $item) {
                $comments[] = [
                    'author' => $item['snippet']['topLevelComment']['snippet']['authorDisplayName'],
                    'text' => $item['snippet']['topLevelComment']['snippet']['textDisplay'],
                    'published_at' => $item['snippet']['topLevelComment']['snippet']['publishedAt']
                ];
            }
        }

        // Преобразуем дату загрузки в удобочитаемый формат
        $published_at = new DateTime($video_info['publishedAt']);
        $published_at_formatted = $published_at->format('d.m.Y H:i:s');

        // Формируем полный ответ
        $response_data = array(
            'title' => $video_info['title'],
            'author' => $video_info['channelTitle'],
            'description' => $video_info['description'],
            'video_id' => $video_id,
            'embed_url' => $embed_url,
            'duration' => $content_details['duration'],
            'published_at' => $published_at_formatted,
            'likes' => $statistics['likeCount'],
            'views' => $statistics['viewCount'],
            'comment_count' => $statistics['commentCount'],
            'comments' => $comments,
            'channel_thumbnail' => get_proxy_url($channel_thumbnail, $config['use_channel_thumbnail_proxy']),
            'thumbnail' => get_proxy_url('https://i.ytimg.com/vi/' . $video_id . '/mqdefault.jpg', $config['use_thumbnail_proxy']),
            'video_url' => !empty($final_video_url) ? get_video_proxy_url($final_video_url, $config['use_video_proxy']) : null
        );

        // Возвращаем ответ в формате JSON
        header('Content-Type: application/json');
        echo json_encode($response_data);
        exit;
    } else {
        // Возвращаем ошибку в формате JSON
        header('Content-Type: application/json');
        echo json_encode(array('error' => 'Видео не найдено.'));
    }
} else {
    // Возвращаем ошибку в формате JSON
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'ID видео не был передан.'));
}

// Функция для получения финального URL после редиректа с таймаутом
function get_final_url($url, $timeout = 10) {
    if (empty($url)) return null;
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_HEADER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, $timeout);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
    curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, false);
    
    $response = curl_exec($ch);
    $error = curl_error($ch);
    $final_url = curl_getinfo($ch, CURLINFO_EFFECTIVE_URL);
    curl_close($ch);

    return $error ? null : $final_url;
}

// Функция для проверки существования URL
function url_exists($url) {
    if (empty($url)) return false;
    
    $ch = curl_init($url);
    curl_setopt($ch, CURLOPT_NOBODY, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 5);
    curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    
    return $http_code == 200;
}
?>