<?php
require_once 'config.php';

function get_proxy_url($url, $use_proxy = true) {
    global $config;
    if ($use_proxy) {
        return $config['url'] . '/image-proxy.php?url=' . urlencode($url);
    }
    return $url;
}

function get_video_proxy_url($url, $use_proxy = true) {
    global $config;
    if ($use_proxy) {
        return $config['url'] . '/video-proxy.php?url=' . urlencode($url);
    }
    return $url;
} 