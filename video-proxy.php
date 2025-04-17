<?php
require_once 'config.php';

if (isset($_GET['url'])) {
    $video_url = $_GET['url'];
    
    // Устанавливаем заголовки для потоковой передачи видео
    header('Content-Type: video/mp4');
    header('Accept-Ranges: bytes');
    
    // Открываем поток для чтения видео
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $video_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, false);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
    curl_setopt($ch, CURLOPT_HEADER, false);
    
    // Передаем заголовки от оригинального запроса
    if (isset($_SERVER['HTTP_RANGE'])) {
        curl_setopt($ch, CURLOPT_RANGE, substr($_SERVER['HTTP_RANGE'], 6));
    }
    
    // Выводим видео потоком
    curl_exec($ch);
    curl_close($ch);
    exit;
} else {
    header('HTTP/1.1 400 Bad Request');
    echo 'Не указан параметр url';
}
?> 