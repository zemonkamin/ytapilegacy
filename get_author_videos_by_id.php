<?php
require_once 'config.php';
require_once 'get_channel_thumbnail.php';
require_once 'proxy_url_handler.php';

// Get request parameters
$channel_id = isset($_GET['channel_id']) ? $_GET['channel_id'] : '';
$count = isset($_GET['count']) ? $_GET['count'] : '50';
$api_key = isset($_GET['apikey']) ? $_GET['apikey'] : $config['api_key'];

if (empty($channel_id)) {
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Channel ID parameter is required'));
    exit;
}

// Get detailed channel information
$channel_url = "https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,brandingSettings&id={$channel_id}&key={$api_key}";

$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, $channel_url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
$response = curl_exec($ch);
curl_close($ch);

$channel_data = json_decode($response, true);

if (!isset($channel_data['items'][0])) {
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'Channel not found'));
    exit;
}

$channel_info = $channel_data['items'][0];
$channel_title = $channel_info['snippet']['title'];
$channel_description = $channel_info['snippet']['description'];
$channel_thumbnail = $channel_info['snippet']['thumbnails']['high']['url'];
$channel_banner = isset($channel_info['brandingSettings']['image']['bannerExternalUrl']) 
    ? $channel_info['brandingSettings']['image']['bannerExternalUrl'] 
    : '';
$subscriber_count = $channel_info['statistics']['subscriberCount'];
$video_count = $channel_info['statistics']['videoCount'];

// Get videos from this channel
$videos = array();
$channel_thumbnail = getChannelThumbnail($channel_id, $api_key);
$nextPageToken = '';
$totalVideos = 0;

do {
    $videos_url = "https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={$channel_id}&maxResults=50&type=video&order=date&key={$api_key}";
    if ($nextPageToken) {
        $videos_url .= "&pageToken={$nextPageToken}";
    }

    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $videos_url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    $response = curl_exec($ch);
    curl_close($ch);

    $videos_data = json_decode($response, true);

    if (isset($videos_data['items']) && !empty($videos_data['items'])) {
        foreach ($videos_data['items'] as $video) {
            if ($totalVideos >= $count) break;
            
            $video_info = $video['snippet'];
            $video_id = $video['id']['videoId'];

            $thumbnail_url = get_proxy_url('https://i.ytimg.com/vi/' . $video_id . '/mqdefault.jpg', $config['use_thumbnail_proxy']);

            $videos[] = array(
                'title' => $video_info['title'],
                'author' => $channel_title,
                'video_id' => $video_id,
                'thumbnail' => $thumbnail_url,
                'channel_thumbnail' => get_proxy_url($channel_thumbnail, $config['use_channel_thumbnail_proxy']),
                'url' => "{$config['url']}/get-ytvideo-info.php?video_id={$video_id}&quality={$config['default_quality']}"
            );
            
            $totalVideos++;
        }
    }

    $nextPageToken = isset($videos_data['nextPageToken']) ? $videos_data['nextPageToken'] : '';
} while ($nextPageToken && $totalVideos < $count);

if (!empty($videos)) {
    $result = array(
        'channel_info' => array(
            'title' => $channel_title,
            'description' => $channel_description,
            'thumbnail' => get_proxy_url($channel_thumbnail, $config['use_channel_thumbnail_proxy']),
            'banner' => get_proxy_url($channel_banner, $config['use_thumbnail_proxy']),
            'subscriber_count' => $subscriber_count,
            'video_count' => $video_count
        ),
        'videos' => $videos
    );

    header('Content-Type: application/json');
    echo json_encode($result);
} else {
    header('Content-Type: application/json');
    echo json_encode(array('error' => 'No videos found for this channel'));
}
?> 