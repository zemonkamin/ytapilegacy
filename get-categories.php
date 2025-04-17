<?php
// Подключаем конфигурационный файл
require_once 'config.php';

$regionCode = isset($_GET['region']) ? $_GET['region'] : 'US';
$api_key = isset($_GET['apikey']) ? $_GET['apikey'] : $config['api_key'];

// URL для запроса категорий
$url = "https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode={$regionCode}&key={$api_key}";

// Получаем данные с помощью cURL
$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, $url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$response = curl_exec($ch);
curl_close($ch);

// Декодируем JSON-ответ
$data = json_decode($response, true);

// Формируем ответ
if (isset($data['items']) && !empty($data['items'])) {
    $categories = array();
    
    foreach ($data['items'] as $item) {
        $categories[] = array(
            'id' => $item['id'],
            'title' => $item['snippet']['title']
        );
    }
    
    // Возвращаем ответ в формате JSON
    header('Content-Type: application/json');
    echo json_encode($categories);
} else {
    // Возвращаем ошибку в формате JSON
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Не удалось получить категории видео.'));
}
?>