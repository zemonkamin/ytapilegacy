<?php
// Ваш API ключ
$api_key = 'AIzaSyDK9_faQma3ZKlVZCI8W8tJWicE0HpRcCk'; // Замените на ваш API ключ

// Получаем параметр запроса
$query = isset($_GET['query']) ? $_GET['query'] : '';

if (empty($query)) {
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Параметр query не указан'));
    exit;
}

// Формируем URL для запроса к YouTube API
$api_url = "https://www.googleapis.com/youtube/v3/search?part=snippet&q=" . urlencode($query) . "&maxResults=10&type=video&key={$api_key}";

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
    $search_results = array();

    foreach ($data['items'] as $video) {
        $video_info = $video['snippet'];
        $video_id = $video['id']['videoId'];

        // Проверяем наличие миниатюры высокого разрешения и используем другую, если она недоступна
        $thumbnail_url = isset($video_info['thumbnails']['maxres']['url']) ? $video_info['thumbnails']['maxres']['url'] :
            (isset($video_info['thumbnails']['standard']['url']) ? $video_info['thumbnails']['standard']['url'] :
                (isset($video_info['thumbnails']['high']['url']) ? $video_info['thumbnails']['high']['url'] :
                    (isset($video_info['thumbnails']['medium']['url']) ? $video_info['thumbnails']['medium']['url'] :
                        (isset($video_info['thumbnails']['default']['url']) ? $video_info['thumbnails']['default']['url'] : null))));

        // Формируем массив с информацией о видео
        $search_results[] = array(
            'title' => $video_info['title'],
            'author' => $video_info['channelTitle'],
            'video_id' => $video_id,
            'thumbnail' => $thumbnail_url
        );
    }

    // Возвращаем ответ в формате JSON
    header('Content-Type: application/json');
    echo json_encode($search_results);
    exit;
} else {
    // Возвращаем ошибку в формате JSON
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Не удалось найти видео по запросу.'));
}
?> 