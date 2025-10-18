import os
import json
from flask import Flask, session
from flask_cors import CORS
from flask_session import Session

# Load configuration from config.json
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

def create_app():
    app = Flask(__name__)
    app.secret_key = config.get('secretkey', 'default_secret_key_for_sessions')
    CORS(app)
    
    # Session configuration
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SECRET_KEY'] = config.get('secretkey', 'default_secret_key_for_sessions')
    
    # Initialize session
    Session(app)

    # Import and register blueprints
    from routes.auth_routes import auth_bp, setup_auth_routes
    from routes.video_routes import video_bp, setup_video_routes
    from routes.search_routes import search_bp, setup_search_routes
    from routes.channel_routes import channel_bp, setup_channel_routes
    from routes.additional_routes import additional_bp, setup_additional_routes

    # Setup routes with configuration
    setup_auth_routes(
        config.get('oauth_client_id', ''),
        config.get('oauth_client_secret', ''),
        "https://yt.legacyprojects.ru/oauth/callback",
        [
            'https://www.googleapis.com/auth/youtube.readonly',
            'https://www.googleapis.com/auth/youtube',
            'https://www.googleapis.com/auth/userinfo.profile',
            'https://www.googleapis.com/auth/userinfo.email'
        ]
    )
    
    setup_video_routes(config)
    setup_search_routes(config)
    setup_channel_routes(config)
    setup_additional_routes(config)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(channel_bp)
    app.register_blueprint(additional_bp)

    # Home route
    @app.route('/')
    def home():
        port = 2823
        return f'''
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>YouTube Legacy API</title>
                <style>
                    body {{
                        margin: 0;
                        padding: 0;
                        font-family: 'Segoe UI', sans-serif;
                        background: #1a1a1a;
                        color: #fff;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        justify-content: center;
                        min-height: 100vh;
                    }}
                    .container {{
                        text-align: center;
                        padding: 20px;
                        max-width: 800px;
                    }}
                    .icon {{
                        width: 150px;
                        height: 150px;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        font-size: 2.5em;
                        margin: 0;
                        color: #fff;
                    }}
                    .subtitle {{
                        font-size: 1.2em;
                        color: #888;
                        margin: 10px 0 30px;
                    }}
                    .tile {{
                        background: #2d2d2d;
                        border-radius: 10px;
                        padding: 20px;
                        margin: 10px 0;
                        text-align: left;
                    }}
                    .tile h2 {{
                        margin: 0 0 10px;
                        color: #fff;
                    }}
                    .tile p {{
                        margin: 0;
                        color: #888;
                    }}
                    .endpoints {{
                        display: grid;
                        grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                        gap: 20px;
                        margin-top: 30px;
                    }}
                    .endpoint {{
                        background: #333;
                        padding: 15px;
                        border-radius: 8px;
                        transition: transform 0.2s;
                    }}
                    .endpoint:hover {{
                        transform: translateY(-5px);
                    }}
                    .endpoint h3 {{
                        margin: 0 0 10px;
                        color: #fff;
                    }}
                    .endpoint p {{
                        margin: 0;
                        color: #888;
                        font-size: 0.9em;
                    }}
                    .footer {{
                        margin-top: 40px;
                        color: #666;
                        font-size: 0.9em;
                    }}
                    .legacy-badge {{
                        background: #0078D7;
                        color: white;
                        padding: 5px 10px;
                        border-radius: 4px;
                        font-size: 0.8em;
                        margin-left: 10px;
                        vertical-align: middle;
                    }}
                </style>
            </head> 
            <body>
                <div class="container">
                    <img src="https://github.com/zemonkamin/ytapilegacy/raw/main/icon.png" alt="YouTube Legacy API" class="icon">
                    <h1>YouTube Legacy API <span class="legacy-badge">LegacyProjects</span></h1>
                    <div class="subtitle">A Windows Phone inspired YouTube API service</div>
                    <div class="tile">
                        <h2>About</h2>
                        <p>This is a legacy YouTube API service that provides endpoints for fetching video information, channel data, and more. Built with Python and Flask.</p>
                        <p style="margin-top: 10px;">Part of the LegacyProjects initiative, bringing back the classic YouTube experience.</p>
                    </div>
                    <div class="endpoints">
                        <div class="endpoint">
                            <h3>Authentication</h3>
                            <p>/auth - OAuth authentication with QR code</p>
                            <p>/auth/status - Check auth status</p>
                            <p>/auth/simple - Simple auth (POST)</p>
                        </div>
                        <div class="endpoint">
                            <h3>Account Info</h3>
                            <p>/account_info?token=REFRESH_TOKEN - Get Google account information</p>
                        </div>
                        <div class="endpoint">
                            <h3>Recommendations</h3>
                            <p>/get_recommendations.php?token=TOKEN&count=N - InnerTube API (формат как /get_top_videos.php)</p>
                            <p style="font-size: 0.8em; color: #aaa;">Example: /get_recommendations_innertube?token=YOUR_TOKEN&count=10</p>
                        </div>
                        <div class="endpoint">
                            <h3>Video Information</h3>
                            <p>/get-ytvideo-info.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Channel Videos</h3>
                            <p>/get_author_videos.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Search Videos</h3>
                            <p>/get_search_videos.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Top Videos</h3>
                            <p>/get_top_videos.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Categories</h3>
                            <p>/get-categories.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Related Videos</h3>
                            <p>/get_related_videos.php</p>
                        </div>
                        <div class="endpoint">
                            <h3>Direct URLs</h3>
                            <p>/get-direct-video-url.php</p>
                            <p>/direct_url</p>
                            <p>/direct_audio_url</p>
                        </div>
                        <div class="endpoint">
                            <h3>Download</h3>
                            <p>/download</p>
                        </div>
                    </div>
                    <div class="footer">
                        Running on port {port} | LegacyProjects YouTube API Service
                    </div>
                </div>
            </body>
            </html>
        '''

    return app

if __name__ == '__main__':
    app = create_app()
    # Запуск сервера в многопоточном режиме
    app.run(host='0.0.0.0', port=2823, threaded=True)