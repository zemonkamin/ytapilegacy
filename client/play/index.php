<?php
require_once '../config.php';

if (!isset($_GET['video_id'])) {
    die('ID видео не указан');
}

$video_id = $_GET['video_id'];
$quality = isset($_GET['quality']) ? $_GET['quality'] : '360';

// Получаем информацию о видео
$api_url = $url . '/get-ytvideo-info.php?video_id=' . $video_id . '&quality=' . $quality . '&apikey=' . $apikey;
$video_data = json_decode(file_get_contents($api_url), true);

if (isset($video_data['error'])) {
    die($video_data['error']);
}

// Получаем рекомендованные видео
$related_url = $url . '/get_related_videos.php?video_id=' . $video_id . '&apikey=' . $apikey;
$related_videos = json_decode(file_get_contents($related_url), true);
?>
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo htmlspecialchars($video_data['title']); ?></title>
    <link rel="stylesheet" href="play.css">
    <!-- Bootstrap CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
<?php include '../navbar.php'; ?>
<div class="container mt-4">
    <div class="row">
        <div class="col-md-8">
            <h1 id="video-title"><?php echo htmlspecialchars($video_data['title']); ?></h1>
            <div class="ratio ratio-16x9 mb-3">
                <!--<video id="video-player" controls autoplay>
                    <source src="<?php echo htmlspecialchars($video_data['video_url']); ?>" type="video/mp4">
                    Ваш браузер не поддерживает видео тег.
                </video>-->
				<iframe src='<?php echo $invidious . '/embed/' . $video_id; ?>'></iframe>
            </div>
            
            <div class="d-flex align-items-center mb-3">
                <img src="<?php echo htmlspecialchars($video_data['channel_thumbnail']); ?>" 
                     alt="Channel thumbnail" class="rounded-circle me-3" width="50" height="50">
                <div>
                    <h5 class="mb-0"><?php echo htmlspecialchars($video_data['author']); ?></h5>
                    <small class="text-muted"><?php echo $video_data['views']; ?> просмотров</small>
                </div>
                <div class="ms-auto">
                    <span class="badge bg-secondary me-2">
                        <i class="bi bi-hand-thumbs-up"></i> <?php echo $video_data['likes']; ?>
                    </span>
                    <span class="badge bg-secondary">
                        <i class="bi bi-calendar"></i> <?php echo $video_data['published_at']; ?>
                    </span>
                </div>
            </div>
            
            <div class="card mb-4">
                <div class="card-body">
                    <h5 class="card-title">Описание</h5>
                    <p class="card-text"><?php echo nl2br(htmlspecialchars($video_data['description'])); ?></p>
                </div>
            </div>
        </div>
        
        <div class="col-md-4">
            <!-- Рекомендованные видео -->
            <div class="card mb-4">
                <div class="card-header">
                    Рекомендованные видео
                </div>
                <div class="card-body p-0">
                    <?php if (!empty($related_videos) && !isset($related_videos['error'])): ?>
                        <div class="list-group list-group-flush">
                            <?php foreach ($related_videos as $video): ?>
                                <a href="play.php?video_id=<?php echo $video['video_id']; ?>" class="list-group-item list-group-item-action">
                                    <div class="d-flex">
                                        <img src="<?php echo htmlspecialchars($video['thumbnail']); ?>" 
                                             alt="Thumbnail" class="me-3" width="120" height="68">
                                        <div>
                                            <h6 class="mb-1"><?php echo htmlspecialchars($video['title']); ?></h6>
                                            <small class="text-muted"><?php echo htmlspecialchars($video['author']); ?></small>
                                        </div>
                                    </div>
                                </a>
                            <?php endforeach; ?>
                        </div>
                    <?php else: ?>
                        <div class="p-3">
                            <p class="mb-0">Не удалось загрузить рекомендованные видео.</p>
                        </div>
                    <?php endif; ?>
                </div>
            </div>
            
            <!-- Комментарии -->
            <div class="card">
                <div class="card-header">
                    Комментарии (<?php echo $video_data['comment_count']; ?>)
                </div>
                <div class="card-body">
                    <?php if (!empty($video_data['comments'])): ?>
                        <?php foreach ($video_data['comments'] as $comment): ?>
                            <div class="mb-3">
                                <div class="d-flex align-items-center mb-1">
                                    <strong><?php echo htmlspecialchars($comment['author']); ?></strong>
                                    <small class="text-muted ms-2"><?php echo date('d.m.Y', strtotime($comment['published_at'])); ?></small>
                                </div>
                                <p><?php echo htmlspecialchars($comment['text']); ?></p>
                            </div>
                            <hr>
                        <?php endforeach; ?>
                    <?php else: ?>
                        <p>Комментариев пока нет.</p>
                    <?php endif; ?>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Bootstrap Icons -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
<!-- Bootstrap JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
// Автоматическое воспроизведение видео после загрузки метаданных
document.getElementById('video-player').addEventListener('loadedmetadata', function() {
    this.play().catch(e => console.log('Автовоспроизведение не разрешено:', e));
});
</script>
</body>
</html>