from flask import Blueprint, request, jsonify, Response, session
import time
import secrets
import html
import json
import io
import base64
import qrcode
from utils.auth import get_auth_url, get_access_token, refresh_access_token, get_account_info, generate_qr_code, token_store, token_store_lock

# Create blueprint
auth_bp = Blueprint('auth', __name__)

def setup_auth_routes(client_id, client_secret, redirect_uri, scopes):
    """Configure authentication routes with OAuth settings"""
    # Initialize auth configuration
    from utils.auth import init_auth_config
    init_auth_config(client_id, client_secret, redirect_uri, scopes)
    
    @auth_bp.route('/auth')
    def auth():
        """
        Serves a page with a QR code or a token inside a <ytreq> element.
        """
        try:
            if 'session_id' not in session:
                session['session_id'] = str(time.time()) + secrets.token_hex(8)
            
            current_session_id = session['session_id']
            
            # Check the global token_store for the token.
            if current_session_id in token_store:
                token = token_store.get(current_session_id)
                if token and not token.startswith("Error"):
                    session['refresh_token'] = token
                    del token_store[current_session_id]

            # If a token is in the session, display the token.
            if 'refresh_token' in session and session['refresh_token']:
                token_display = f"Token: {html.escape(session['refresh_token'])}"
                return Response(f'''<ytreq>{token_display}</ytreq>''', mimetype='text/html')

            # If no token, generate and display the QR code.
            if 'auth_url' in session and time.time() - session.get('auth_url_timestamp', 0) < 300:
                auth_url = session['auth_url']
            else:
                auth_url = get_auth_url(current_session_id)
                session['auth_url'] = auth_url
                session['auth_url_timestamp'] = time.time()
            
            qr_display = generate_qr_code(auth_url)
            return Response(f'''<ytreq>{qr_display}</ytreq>''', mimetype='text/html')

        except Exception as e:
            return Response(f'''<ytreq>Ошибка: {html.escape(str(e))}</ytreq>''', 500)

    @auth_bp.route('/auth/events')
    def auth_events():
        """SSE endpoint to push token updates to the client"""
        session_id = request.args.get('session_id')
        if not session_id:
            return Response(
                'data: {"error": "Missing session_id"}\n\n',
                mimetype='text/event-stream'
            )

        def generate():
            start_time = time.time()
            timeout = 300  # 5 minutes timeout
            while time.time() - start_time < timeout:
                with token_store_lock:
                    if session_id in token_store:
                        token = token_store[session_id]
                        yield f'data: {json.dumps({"token": token})}\n\n'
                        del token_store[session_id]  # Clean up
                        return
                time.sleep(1)
            yield f'data: {json.dumps({"error": "Authentication timed out"})}\n\n'

        return Response(generate(), mimetype='text/event-stream')

    @auth_bp.route('/oauth/callback')
    def oauth_callback():
        try:
            code = request.args.get('code')
            session_id = request.args.get('state')
            if not code or not session_id:
                return '''
                    <html>
                        <body>
                            <h2>Authentication failed</h2>
                            <p>No authorization code or state received.</p>
                        </body>
                    </html>
                ''', 400

            try:
                token_data = get_access_token(code)
                refresh_token = token_data.get('refresh_token')
                
                if not refresh_token:
                    return '''
                        <html>
                            <body>
                                <h2>Authentication failed</h2>
                                <p>No refresh token received. Please try again.</p>
                            </body>
                        </html>
                    ''', 400
                
                session['refresh_token'] = refresh_token
                
                with token_store_lock:
                    token_store[session_id] = refresh_token
                
                session.pop('auth_url', None)
                session.pop('auth_url_timestamp', None)
                
                return '''
                    <html>
                        <body>
                            <h2>Authentication successful</h2>
                            <p>You can close this window now and refresh the previous page.</p>
                            <script>
                                window.close();
                            </script>
                        </body>
                    </html>
                '''
            except Exception as e:
                with token_store_lock:
                    token_store[session_id] = f"Error getting token: {str(e)}"
                return f'''
                    <html>
                        <body>
                            <h2>Error</h2>
                            <p>Error getting token: {html.escape(str(e))}</p>
                        </body>
                    </html>
                ''', 400
        except Exception as e:
            return f'''
                <html>
                    <body>
                        <h2>Internal server error</h2>
                        <p>{html.escape(str(e))}</p>
                    </body>
                    </html>
            ''', 500

    @auth_bp.route('/account_info')
    def account_info():
        """Get Google account information using refresh token"""
        try:
            refresh_token = request.args.get('token')
            if not refresh_token:
                return jsonify({'error': 'Missing token parameter. Use ?token=YOUR_REFRESH_TOKEN'}), 400

            # Get access token from refresh token
            try:
                token_data = refresh_access_token(refresh_token)
                access_token = token_data['access_token']
            except Exception as e:
                return jsonify({'error': 'Invalid refresh token', 'details': str(e)}), 401

            # Get account information
            account_data = get_account_info(access_token)
            if not account_data:
                return jsonify({'error': 'Failed to get account information'}), 500

            # Format the response
            profile = account_data['profile']
            youtube = account_data['youtube']
            
            result = {
                'google_account': {
                    'id': profile.get('id'),
                    'name': profile.get('name'),
                    'given_name': profile.get('given_name'),
                    'family_name': profile.get('family_name'),
                    'email': profile.get('email'),
                    'verified_email': profile.get('verified_email'),
                    'picture': profile.get('picture'),
                    'locale': profile.get('locale')
                }
            }

            # Add YouTube channel info if available
            if youtube and youtube.get('items') and len(youtube['items']) > 0:
                channel = youtube['items'][0]
                snippet = channel.get('snippet', {})
                statistics = channel.get('statistics', {})
                
                result['youtube_channel'] = {
                    'id': channel.get('id'),
                    'title': snippet.get('title'),
                    'description': snippet.get('description'),
                    'custom_url': snippet.get('customUrl'),
                    'published_at': snippet.get('publishedAt'),
                    'thumbnails': snippet.get('thumbnails'),
                    'country': snippet.get('country'),
                    'subscriber_count': statistics.get('subscriberCount'),
                    'video_count': statistics.get('videoCount'),
                    'view_count': statistics.get('viewCount')
                }

            return jsonify(result)

        except Exception as e:
            error_msg = str(e)
            try:
                error_msg = error_msg.encode('ascii', errors='ignore').decode('ascii')
            except:
                error_msg = "Request failed"
            return jsonify({
                'error': 'Failed to get account information',
                'details': error_msg
            }), 500