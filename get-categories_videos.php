<?php
require_once 'config.php';
require_once 'get_channel_thumbnail.php';
require_once 'proxy_url_handler.php';

$count = isset($_GET['count']) ? $_GET['count'] : '50';
$categoryId = isset($_GET['categoryId']) ? $_GET['categoryId'] : '';
$api_key = isset($_GET['apikey']) ? $_GET['apikey'] : $config['api_key'];

// Формируем URL для запроса к YouTube API
$api_url = "https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults={$count}&key={$api_key}";
if (!empty($categoryId)) {
    $api_url .= "&videoCategoryId={$categoryId}";
}

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
    $top_videos = array();

    foreach ($data['items'] as $video) {
        $video_info = $video['snippet'];
        $video_id = $video['id'];
        $channel_id = $video_info['channelId'];

        // Получаем иконку канала
        $channel_thumbnail = getChannelThumbnail($channel_id, $api_key);

        $thumbnail_url = get_proxy_url('https://i.ytimg.com/vi/' . $video_id . '/mqdefault.jpg', $config['use_thumbnail_proxy']);

        // Формируем массив с информацией о видео
        $top_videos[] = array(
            'title' => $video_info['title'],
            'author' => $video_info['channelTitle'],
            'video_id' => $video_id,
            'thumbnail' => $thumbnail_url,
            'channel_thumbnail' => get_proxy_url($channel_thumbnail, $config['use_channel_thumbnail_proxy']),
            'url' => get_video_proxy_url("{$config['url']}/get-ytvideo-info.php?video_id={$video_id}&quality={$config['default_quality']}", $config['use_video_proxy'])
        );
    }

    // Возвращаем ответ в формате JSON
    header('Content-Type: application/json');
    echo json_encode($top_videos);
    exit;
} else {
    // Возвращаем ошибку в формате JSON
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Не удалось найти популярные видео.'));
}
?>