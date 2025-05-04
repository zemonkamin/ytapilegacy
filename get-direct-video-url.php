<?php
require_once 'config.php';

// Получаем ID видео из GET-запроса
if (isset($_GET['video_id'])) {
    $video_id = $_GET['video_id'];
    $python_path = $config['python_path'];
    
    // Вызываем Python-скрипт для получения прямой ссылки
    $command = escapeshellcmd($python_path . ' get_video_url.py ' . escapeshellarg($video_id));
    $output = shell_exec($command);
    preg_match('/Direct video URL: (https?:\/\/[^\s]+)/', $output, $matches);
    $video_url = $matches[1] ?? null;

    if ($video_url) {
        header('Content-Type: application/json');
        echo json_encode(['video_url' => $video_url]);
    } else {
        header('Content-Type: application/json');
        echo json_encode(['error' => 'Не удалось получить прямую ссылку на видео.']);
    }
} else {
    header('Content-Type: application/json');
    echo json_encode(['error' => 'ID видео не был передан.']);
} 