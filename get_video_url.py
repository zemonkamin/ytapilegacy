import yt_dlp
import sys

def get_video_url(video_id):
    """Get direct video URL from YouTube video ID."""
    ydl_opts = {
        'quiet': True,
        'format': 'best',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
            return info.get('url')
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python get_video_url.py VIDEO_ID")
        sys.exit(1)
    
    video_id = sys.argv[1]
    video_url = get_video_url(video_id)
    
    if video_url:
        print(f"Direct video URL: {video_url}")
    else:
        print("Could not get video URL") 