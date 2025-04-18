<?php
require_once 'config.php';
require_once 'get_channel_thumbnail.php';
require_once 'proxy_url_handler.php';

// Получаем ID видео из GET-запроса
if (isset($_GET['video_id'])) {
    $video_id = $_GET['video_id'];
    $count = isset($_GET['count']) ? $_GET['count'] : '50';
    $api_key = isset($_GET['apikey']) ? $_GET['apikey'] : $config['api_key'];

    // Сначала получаем информацию о видео, чтобы использовать его теги и название
    $video_info_url = "https://www.googleapis.com/youtube/v3/videos?part=snippet&id={$video_id}&key={$api_key}";
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $video_info_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $video_response = curl_exec($ch);
    curl_close($ch);
    
    $video_data = json_decode($video_response, true);
    
    if (!isset($video_data['items'][0])) {
        header('Content-Type: application/json');
        echo json_encode(array('error' => 'Видео не найдено.'));
        exit;
    }
    
    $video_info = $video_data['items'][0]['snippet'];
    $title = $video_info['title'];
    $channel_id = $video_info['channelId'];
    
    // Формируем поисковый запрос на основе названия видео
    $search_query = urlencode($title);
    
    // Формируем URL для поиска похожих видео
    $api_url = "https://www.googleapis.com/youtube/v3/search?part=snippet&q={$search_query}&type=video&maxResults={$count}&key={$api_key}";

    // Получаем данные с помощью cURL
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $api_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $response = curl_exec($ch);
    curl_close($ch);

    // Декодируем JSON-ответ
    $data = json_decode($response, true);

    // Проверяем, есть ли данные о видео
    if (isset($data['items']) && !empty($data['items'])) {
        $related_videos = array();

        foreach ($data['items'] as $video) {
            // Пропускаем исходное видео
            if ($video['id']['videoId'] === $video_id) {
                continue;
            }
            
            $video_info = $video['snippet'];
            $video_id = $video['id']['videoId'];
            $channel_id = $video_info['channelId'];

            // Получаем иконку канала
            $channel_thumbnail = getChannelThumbnail($channel_id, $api_key);

            // Формируем массив с информацией о видео
            $related_videos[] = array(
                'title' => $video_info['title'],
                'author' => $video_info['channelTitle'],
                'video_id' => $video_id,
                'thumbnail' => get_proxy_url('https://i.ytimg.com/vi/' . $video_id . '/mqdefault.jpg', $config['use_thumbnail_proxy']),
                'channel_thumbnail' => get_proxy_url($channel_thumbnail, $config['use_channel_thumbnail_proxy']),
                'url' => get_video_proxy_url("{$config['url']}/get-ytvideo-info.php?video_id={$video_id}&quality={$config['default_quality']}", $config['use_video_proxy'])
            );
        }

        // Возвращаем ответ в формате JSON
        header('Content-Type: application/json');
        echo json_encode($related_videos);
        exit;
    } else {
        // Возвращаем ошибку в формате JSON
        header('Content-Type: application/json');
        echo json_encode(array('error' => 'Не удалось найти похожие видео.'));
    }
} else {
    // Возвращаем ошибку в формате JSON
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'ID видео не был передан.'));
} 