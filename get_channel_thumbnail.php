<?php
require_once 'config.php';

function getChannelThumbnail($channelId, $api_key = null) {
    if (empty($channelId)) return '';
    
    // Use provided API key or fall back to config
    $api_key = $api_key ?? $GLOBALS['config']['api_key'];
    
    $api_url = "https://www.googleapis.com/youtube/v3/channels?part=snippet&id={$channelId}&key={$api_key}";
    
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $api_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $response = curl_exec($ch);
    curl_close($ch);
    
    $data = json_decode($response, true);
    
    if (isset($data['items'][0]['snippet']['thumbnails']['default']['url'])) {
        return $data['items'][0]['snippet']['thumbnails']['default']['url'];
    }
    
    return '';
}

// Для тестирования можно раскомментировать
// if (isset($_GET['channelId'])) {
//     $api_key = isset($_GET['apikey']) ? $_GET['apikey'] : null;
//     header('Content-Type: application/json');
//     echo json_encode(['thumbnail' => getChannelThumbnail($_GET['channelId'], $api_key)]);
// }
?>