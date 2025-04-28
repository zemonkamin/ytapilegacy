<?php
require_once 'config.php';
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Top YouTube Videos</title>
    <style>
        body {
            font-family: 'Roboto', Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f9f9f9;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .video-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px 0;
        }
        
        .video-card {
            display: flex;
            flex-direction: column;
            background: #fff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            text-decoration: none;
            color: #333;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .video-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.15);
        }
        
        .video-thumbnail-container {
            position: relative;
            width: 100%;
            padding-top: 56.25%; /* 16:9 Aspect Ratio */
            background-color: #f0f0f0;
        }
        
        .video-thumbnail {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        
        .video-info {
            padding: 12px;
        }
        
        .video-title {
            font-size: 16px;
            margin: 0 0 8px 0;
            line-height: 1.4;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        
        .video-author {
            display: flex;
            align-items: center;
            margin-top: 10px;
            font-size: 14px;
            color: #606060;
        }
        
        .author-thumbnail {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            margin-right: 8px;
        }
        
        .video-id {
            font-size: 12px;
            color: #909090;
            margin-top: 8px;
        }
    </style>
</head>
<body>
<?php include 'navbar.php'; ?>
<div class="container">
    <div id="video-list" class="video-list"></div>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {
    fetch('../get_top_videos.php?apikey=<?php echo $apikey; ?>')
        .then(response => response.json())
        .then(data => {
            const videoList = document.getElementById('video-list');
            data.forEach(video => {
                const videoCard = document.createElement('a');
                videoCard.className = 'video-card';
                videoCard.href = `play/?video_id=${video.video_id}`;
                videoCard.target = '_blank';

                const thumbnailContainer = document.createElement('div');
                thumbnailContainer.className = 'video-thumbnail-container';

                const thumbnail = document.createElement('img');
                thumbnail.className = 'video-thumbnail';
                thumbnail.src = video.thumbnail;
                thumbnail.alt = video.title;

                thumbnailContainer.appendChild(thumbnail);

                const info = document.createElement('div');
                info.className = 'video-info';

                const title = document.createElement('h2');
                title.className = 'video-title';
                title.textContent = video.title;

                const authorContainer = document.createElement('div');
                authorContainer.className = 'video-author';
                
                const authorThumbnail = document.createElement('img');
                authorThumbnail.className = 'author-thumbnail';
                authorThumbnail.src = video.channel_thumbnail || 'https://via.placeholder.com/24';
                authorThumbnail.alt = video.author;
                
                const authorName = document.createElement('span');
                authorName.textContent = video.author;
                
                authorContainer.appendChild(authorThumbnail);
                authorContainer.appendChild(authorName);

                const videoId = document.createElement('p');
                videoId.className = 'video-id';
                videoId.textContent = `ID: ${video.video_id}`;

                info.appendChild(title);
                info.appendChild(authorContainer);
                info.appendChild(videoId);

                videoCard.appendChild(thumbnailContainer);
                videoCard.appendChild(info);

                videoList.appendChild(videoCard);
            });
        })
        .catch(error => {
            console.error('Error fetching top videos:', error);
        });
});
</script>
</body>
</html>