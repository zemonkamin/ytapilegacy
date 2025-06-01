const express = require('express');
const axios = require('axios');
const cors = require('cors');
const { exec } = require('child_process');
const path = require('path');
const app = express();
const port = 2823;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Configuration
const config = {
    api_key: 'AIzaSyCve8OQH2HNIQ2oBwt6udvDoe0gvs5aTf',
    invidious_url: 'inv1.nadeko.net',
    oldyoutube_url: 'http://sonyericsson.org:64',
    url: 'https://qqq.bccst.ru/youtube/',
    default_quality: '360',
    available_qualities: ['144', '240', '360', '480', '720', '1080', '1440', '2160'],
    youtube_api_key: 'AIzaSyDK9_faQma3ZKlVZCI8W8tJWicE0HpRcCk',
    invidious_instance: 'inv1.nadeko.net',
    max_search_results: 10,
    max_popular_videos: 10,
    video_timer: 30,
    use_thumbnail_proxy: true,
    use_channel_thumbnail_proxy: true,
    use_video_proxy: false,
    video_source: 'oldyoutube',
    python_path: 'topvenv/bin/python'
};

// Helper functions
const getChannelThumbnail = async (channelId, apiKey) => {
    try {
        const response = await axios.get(`https://www.googleapis.com/youtube/v3/channels?id=${channelId}&key=${apiKey}&part=snippet`);
        return response.data.items[0]?.snippet?.thumbnails?.default?.url || '';
    } catch (error) {
        console.error('Error getting channel thumbnail:', error);
        return '';
    }
};

const getProxyUrl = (url, useProxy) => {
    if (!useProxy) return url;
    return url.startsWith('https://i.ytimg.com') 
        ? `https://qqq.bccst.ru/youtube/image-proxy.php?url=${url}`
        : url;
};

const getVideoProxyUrl = (url, useProxy) => {
    if (!useProxy) return url;
    return `https://qqq.bccst.ru/youtube/video-proxy.php?url=${url}`;
};

const getFinalUrl = async (url, timeout = 10) => {
    try {
        const response = await axios.get(url, {
            maxRedirects: 5,
            timeout: timeout * 1000,
            validateStatus: () => true
        });
        return response.request.res.responseUrl;
    } catch (error) {
        console.error('Error getting final URL:', error);
        return null;
    }
};

const urlExists = async (url) => {
    try {
        const response = await axios.head(url, {
            timeout: 5000,
            validateStatus: () => true
        });
        return response.status === 200;
    } catch (error) {
        return false;
    }
};

// Routes
app.get('/get_author_videos_by_id.php', async (req, res) => {
    try {
        const { channel_id, count = '50', apikey = config.api_key } = req.query;
        
        if (!channel_id) {
            return res.json({ error: 'Channel ID parameter is required' });
        }

        const channelResponse = await axios.get(`https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,brandingSettings&id=${channel_id}&key=${apikey}`);
        const channelInfo = channelResponse.data.items[0];

        if (!channelInfo) {
            return res.json({ error: 'Channel not found' });
        }

        const videos = [];
        let nextPageToken = '';
        let totalVideos = 0;

        do {
            const videosUrl = `https://www.googleapis.com/youtube/v3/search?part=snippet&channelId=${channel_id}&maxResults=50&type=video&order=date&key=${apikey}${nextPageToken ? `&pageToken=${nextPageToken}` : ''}`;
            const videosResponse = await axios.get(videosUrl);
            const videosData = videosResponse.data;

            if (videosData.items?.length) {
                for (const video of videosData.items) {
                    if (totalVideos >= count) break;

                    const videoInfo = video.snippet;
                    const videoId = video.id.videoId;
                    const channelThumbnail = await getChannelThumbnail(channel_id, apikey);

                    videos.push({
                        title: videoInfo.title,
                        author: channelInfo.snippet.title,
                        video_id: videoId,
                        thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`, config.use_thumbnail_proxy),
                        channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
                        url: `${config.url}/get-ytvideo-info.php?video_id=${videoId}&quality=${config.default_quality}`
                    });

                    totalVideos++;
                }
            }

            nextPageToken = videosData.nextPageToken || '';
        } while (nextPageToken && totalVideos < count);

        res.json({
            channel_info: {
                title: channelInfo.snippet.title,
                description: channelInfo.snippet.description,
                thumbnail: getProxyUrl(channelInfo.snippet.thumbnails.high.url, config.use_channel_thumbnail_proxy),
                banner: getProxyUrl(channelInfo.brandingSettings?.image?.bannerExternalUrl || '', config.use_thumbnail_proxy),
                subscriber_count: channelInfo.statistics.subscriberCount,
                video_count: channelInfo.statistics.videoCount
            },
            videos
        });
    } catch (error) {
        console.error('Error in get_author_videos_by_id:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_author_videos.php', async (req, res) => {
    try {
        const { author, count = '50', apikey = config.api_key } = req.query;

        if (!author) {
            return res.json({ error: 'Author parameter is required' });
        }

        const searchResponse = await axios.get(`https://www.googleapis.com/youtube/v3/search?part=snippet&q=${encodeURIComponent(author)}&type=channel&maxResults=1&key=${apikey}`);
        const channelId = searchResponse.data.items[0]?.id?.channelId;

        if (!channelId) {
            return res.json({ error: 'Channel not found' });
        }

        // Redirect to get_author_videos_by_id.php with the found channel ID
        res.redirect(`/get_author_videos_by_id.php?channel_id=${channelId}&count=${count}&apikey=${apikey}`);
    } catch (error) {
        console.error('Error in get_author_videos:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_channel_thumbnail.php', async (req, res) => {
    try {
        const { video_id, apikey = config.api_key } = req.query;

        if (!video_id) {
            return res.json({ error: 'ID видео не был передан.' });
        }

        if (!apikey) {
            return res.json({ channel_thumbnail: '' });
        }

        const videoResponse = await axios.get(`https://www.googleapis.com/youtube/v3/videos?id=${video_id}&key=${apikey}&part=snippet`);
        const channelId = videoResponse.data.items[0]?.snippet?.channelId;

        if (!channelId) {
            return res.json({ error: 'Видео не найдено.' });
        }

        const channelThumbnail = await getChannelThumbnail(channelId, apikey);
        res.json({ channel_thumbnail: channelThumbnail });
    } catch (error) {
        console.error('Error in get_channel_thumbnail:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_related_videos.php', async (req, res) => {
    try {
        const { video_id, count = '50', apikey = config.api_key } = req.query;

        if (!video_id) {
            return res.json({ error: 'ID видео не был передан.' });
        }

        const videoResponse = await axios.get(`https://www.googleapis.com/youtube/v3/videos?part=snippet&id=${video_id}&key=${apikey}`);
        const videoInfo = videoResponse.data.items[0]?.snippet;

        if (!videoInfo) {
            return res.json({ error: 'Видео не найдено.' });
        }

        const searchResponse = await axios.get(`https://www.googleapis.com/youtube/v3/search?part=snippet&q=${encodeURIComponent(videoInfo.title)}&type=video&maxResults=${count}&key=${apikey}`);
        const relatedVideos = [];

        for (const video of searchResponse.data.items) {
            if (video.id.videoId === video_id) continue;

            const videoInfo = video.snippet;
            const videoId = video.id.videoId;
            const channelThumbnail = await getChannelThumbnail(videoInfo.channelId, apikey);

            relatedVideos.push({
                title: videoInfo.title,
                author: videoInfo.channelTitle,
                video_id: videoId,
                thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`, config.use_thumbnail_proxy),
                channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
                url: getVideoProxyUrl(`${config.url}/get-ytvideo-info.php?video_id=${videoId}&quality=${config.default_quality}`, config.use_video_proxy)
            });
        }

        res.json(relatedVideos);
    } catch (error) {
        console.error('Error in get_related_videos:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_search_suggestions.php', async (req, res) => {
    try {
        const { query, apikey = config.api_key } = req.query;

        if (!query) {
            return res.json({ error: 'Query parameter is required' });
        }

        const response = await axios.get(`https://clients1.google.com/complete/search?client=youtube&hl=en&ds=yt&q=${encodeURIComponent(query)}`, {
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        });

        const data = response.data.replace(/^window\.google\.ac\.h\(/, '').replace(/\)$/, '');
        const suggestions = JSON.parse(data)[1].slice(0, 10);

        res.json({
            query,
            suggestions
        });
    } catch (error) {
        console.error('Error in get_search_suggestions:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_search_videos.php', async (req, res) => {
    try {
        const { query, count = '50', apikey = config.api_key } = req.query;

        if (!query) {
            return res.json({ error: 'Параметр query не указан' });
        }

        const response = await axios.get(`https://www.googleapis.com/youtube/v3/search?part=snippet&q=${encodeURIComponent(query)}&maxResults=${count}&type=video&key=${apikey}`);
        const searchResults = [];

        for (const video of response.data.items) {
            const videoInfo = video.snippet;
            const videoId = video.id.videoId;
            const channelThumbnail = await getChannelThumbnail(videoInfo.channelId, apikey);

            searchResults.push({
                title: videoInfo.title,
                author: videoInfo.channelTitle,
                video_id: videoId,
                thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`, config.use_thumbnail_proxy),
                channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
                url: `${config.url}/get-ytvideo-info.php?video_id=${videoId}&quality=${config.default_quality}`
            });
        }

        res.json(searchResults);
    } catch (error) {
        console.error('Error in get_search_videos:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get_top_videos.php', async (req, res) => {
    try {
        const { count = '50', apikey = config.api_key } = req.query;

        const response = await axios.get(`https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults=${count}&key=${apikey}`);
        const topVideos = [];

        for (const video of response.data.items) {
            const videoInfo = video.snippet;
            const videoId = video.id;
            const channelThumbnail = await getChannelThumbnail(videoInfo.channelId, apikey);

            topVideos.push({
                title: videoInfo.title,
                author: videoInfo.channelTitle,
                video_id: videoId,
                thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`, config.use_thumbnail_proxy),
                channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
                url: `${config.url}/get-ytvideo-info.php?video_id=${videoId}&quality=${config.default_quality}`
            });
        }

        res.json(topVideos);
    } catch (error) {
        console.error('Error in get_top_videos:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get-categories_videos.php', async (req, res) => {
    try {
        const { count = '50', categoryId, apikey = config.api_key } = req.query;

        let url = `https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults=${count}&key=${apikey}`;
        if (categoryId) {
            url += `&videoCategoryId=${categoryId}`;
        }

        const response = await axios.get(url);
        const topVideos = [];

        for (const video of response.data.items) {
            const videoInfo = video.snippet;
            const videoId = video.id;
            const channelThumbnail = await getChannelThumbnail(videoInfo.channelId, apikey);

            topVideos.push({
                title: videoInfo.title,
                author: videoInfo.channelTitle,
                video_id: videoId,
                thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`, config.use_thumbnail_proxy),
                channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
                url: `${config.url}/get-ytvideo-info.php?video_id=${videoId}&quality=${config.default_quality}`
            });
        }

        res.json(topVideos);
    } catch (error) {
        console.error('Error in get-categories_videos:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get-categories.php', async (req, res) => {
    try {
        const { region = 'US', apikey = config.api_key } = req.query;

        const response = await axios.get(`https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode=${region}&key=${apikey}`);
        const categories = response.data.items.map(item => ({
            id: item.id,
            title: item.snippet.title
        }));

        res.json(categories);
    } catch (error) {
        console.error('Error in get-categories:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get-direct-video-url.php', async (req, res) => {
    try {
        const { video_id } = req.query;

        if (!video_id) {
            return res.json({ error: 'ID видео не был передан.' });
        }

        exec(`${config.python_path} get_video_url.py ${video_id}`, (error, stdout) => {
            if (error) {
                console.error('Error executing Python script:', error);
                return res.json({ error: 'Не удалось получить прямую ссылку на видео.' });
            }

            const match = stdout.match(/Direct video URL: (https?:\/\/[^\s]+)/);
            const videoUrl = match ? match[1] : null;

            if (videoUrl) {
                res.json({ video_url: videoUrl });
            } else {
                res.json({ error: 'Не удалось получить прямую ссылку на видео.' });
            }
        });
    } catch (error) {
        console.error('Error in get-direct-video-url:', error);
        res.json({ error: 'Internal server error' });
    }
});

app.get('/get-ytvideo-info.php', async (req, res) => {
    try {
        const { video_id, quality, apikey = config.api_key } = req.query;

        if (!video_id) {
            return res.json({ error: 'ID видео не был передан.' });
        }

        const response = await axios.get(`https://www.googleapis.com/youtube/v3/videos?id=${video_id}&key=${apikey}&part=snippet,contentDetails,statistics`);
        const videoData = response.data.items[0];

        if (!videoData) {
            return res.json({ error: 'Видео не найдено.' });
        }

        const videoInfo = videoData.snippet;
        const contentDetails = videoData.contentDetails;
        const statistics = videoData.statistics;
        const channelId = videoInfo.channelId;
        const channelThumbnail = await getChannelThumbnail(channelId, apikey);

        let finalVideoUrl = '';
        if (config.video_source === 'invidious') {
            const videoUrl = `https://${config.invidious_url}/embed/${video_id}?raw=1&quality=${quality}`;
            finalVideoUrl = await getFinalUrl(videoUrl);
        } else if (config.video_source === 'oldyoutube') {
            // Try multiple methods to get the video URL
            const methods = [
                // Method 1: Direct video URL
                async () => {
                    const videoUrl = `${config.oldyoutube_url}/get_video?video_id=${video_id}/mp4%27,%27/exp_hd?video_id=${video_id}`;
                    return await getFinalUrl(videoUrl, config.video_timer);
                },
                // Method 2: Assets directory
                async () => {
                    const baseUrl = config.oldyoutube_url.replace(/\/$/, '');
                    const videoUrl = `${baseUrl}/assets/${video_id}.mp4`;
                    if (await urlExists(videoUrl)) {
                        return videoUrl;
                    }
                    return null;
                },
                // Method 3: Legacy format
                async () => {
                    const baseUrl = config.oldyoutube_url.replace(/\/$/, '');
                    const videoUrl = `${baseUrl}/videos/${video_id}.mp4`;
                    if (await urlExists(videoUrl)) {
                        return videoUrl;
                    }
                    return null;
                },
                // Method 4: Alternative format
                async () => {
                    const baseUrl = config.oldyoutube_url.replace(/\/$/, '');
                    const videoUrl = `${baseUrl}/watch?v=${video_id}&format=mp4`;
                    return await getFinalUrl(videoUrl, config.video_timer);
                }
            ];

            // Try each method until we get a valid URL
            for (const method of methods) {
                const url = await method();
                if (url) {
                    finalVideoUrl = url;
                    break;
                }
            }

            // If all methods fail, try to get video info and construct URL
            if (!finalVideoUrl) {
                try {
                    const videoInfoUrl = `${config.oldyoutube_url}/api/video_info.php?video_id=${video_id}`;
                    const videoInfoResponse = await axios.get(videoInfoUrl);
                    const videoInfo = videoInfoResponse.data;

                    if (videoInfo && videoInfo.video_url) {
                        finalVideoUrl = videoInfo.video_url;
                    }
                } catch (error) {
                    console.error('Error getting video info from oldyoutube:', error);
                }
            }
        } else if (config.video_source === 'direct') {
            const directUrl = `https://legacyprojects.ru/youtube/get-direct-video-url.php?video_id=${encodeURIComponent(video_id)}`;
            const directResponse = await axios.get(directUrl, {
                httpsAgent: new (require('https').Agent)({ rejectUnauthorized: false })
            });
            finalVideoUrl = directResponse.data.video_url;
        } else {
            exec(`${config.python_path} get_video_url.py ${video_id}`, (error, stdout) => {
                if (!error) {
                    const match = stdout.match(/Direct video URL: (https?:\/\/[^\s]+)/);
                    finalVideoUrl = match ? match[1] : null;
                }
            });
        }

        const commentsResponse = await axios.get(`https://www.googleapis.com/youtube/v3/commentThreads?key=${apikey}&textFormat=plainText&part=snippet&videoId=${video_id}&maxResults=25`);
        const comments = [];

        for (const item of commentsResponse.data.items) {
            const commentAuthorId = item.snippet.topLevelComment.snippet.authorChannelId.value;
            const commentAuthorThumbnail = await getChannelThumbnail(commentAuthorId, apikey);

            comments.push({
                author: item.snippet.topLevelComment.snippet.authorDisplayName,
                text: item.snippet.topLevelComment.snippet.textDisplay,
                published_at: item.snippet.topLevelComment.snippet.publishedAt,
                author_thumbnail: getProxyUrl(commentAuthorThumbnail, config.use_channel_thumbnail_proxy)
            });
        }

        const publishedAt = new Date(videoInfo.publishedAt);
        const publishedAtFormatted = publishedAt.toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });

        res.json({
            title: videoInfo.title,
            author: videoInfo.channelTitle,
            description: videoInfo.description,
            video_id: video_id,
            embed_url: `https://www.youtube.com/embed/${video_id}`,
            duration: contentDetails.duration,
            published_at: publishedAtFormatted,
            likes: statistics.likeCount,
            views: statistics.viewCount,
            comment_count: statistics.commentCount,
            comments,
            channel_thumbnail: getProxyUrl(channelThumbnail, config.use_channel_thumbnail_proxy),
            thumbnail: getProxyUrl(`https://i.ytimg.com/vi/${video_id}/mqdefault.jpg`, config.use_thumbnail_proxy),
            video_url: finalVideoUrl ? getVideoProxyUrl(finalVideoUrl, config.use_video_proxy) : null
        });
    } catch (error) {
        console.error('Error in get-ytvideo-info:', error);
        res.json({ error: 'Internal server error' });
    }
});

// Start server
app.listen(port, () => {
    console.log(`Server running at http://localhost:${port}`);
}); 