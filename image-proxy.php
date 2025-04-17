<?php
// Проверяем, установлен ли параметр 'url'
if (isset($_GET['url'])) {
    $url = $_GET['url'];

    // Проверяем, является ли URL допустимым
    if (filter_var($url, FILTER_VALIDATE_URL)) {
        // Получаем содержимое изображения
        $imageData = file_get_contents($url);

        // Устанавливаем заголовок для типа контента
        header('Content-Type: image/jpeg'); // Измените на нужный тип изображения
        echo $imageData;
    } else {
        // Если URL недопустимый, возвращаем ошибку
        http_response_code(400);
        echo 'Invalid URL';
    }
} else {
    // Если параметр 'url' не установлен, возвращаем ошибку
    http_response_code(400);
    echo 'URL parameter is required';
}
?>
