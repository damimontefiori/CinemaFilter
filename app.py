"""
Flask Web Application for YTS Movie Filter by IMDb and Rotten Tomatoes.
Protected by Multi-Key Access Authentication (APP_PASSWORDS).
"""

import os
import io
import re
import csv
import json
import subprocess
from datetime import timedelta
from flask import Flask, render_template, request, Response, jsonify, session, redirect, url_for
import scraper
import subtitles
import latino_sources

# Helper to load .env file if present
def load_dotenv_simple():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

load_dotenv_simple()

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'cinema-filter-secret-key-2026')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)


def get_allowed_passwords():
    """
    Parses comma-separated passwords from APP_PASSWORDS environment variable.
    Example: APP_PASSWORDS="clave1,clave2,amigo123"
    """
    raw = os.environ.get('APP_PASSWORDS', '').strip()
    if not raw:
        # Fallback default if not configured
        return ['admin123']
    return [p.strip() for p in raw.split(',') if p.strip()]


@app.before_request
def require_authentication():
    """
    Guards all routes and APIs behind authentication.
    """
    # Allow login, static files, and favicon
    allowed_endpoints = ['login', 'static']
    if request.endpoint in allowed_endpoints or request.path.startswith('/static'):
        return

    # Check session
    if not session.get('authenticated'):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Autenticación requerida', 'login_required': True}), 401
        return redirect(url_for('login', next=request.path))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to index
    if session.get('authenticated'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        entered_password = request.form.get('password', '').strip()
        allowed = get_allowed_passwords()

        if entered_password in allowed:
            session.permanent = True
            session['authenticated'] = True

            next_url = request.args.get('next')
            # Protect against open redirect vulnerabilities
            if not next_url or not next_url.startswith('/') or next_url.startswith('//'):
                next_url = url_for('index')

            return redirect(next_url)
        else:
            error = 'Clave de acceso incorrecta. Inténtalo nuevamente.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


GENRES = [
    'all', 'action', 'adventure', 'animation', 'biography', 'comedy',
    'crime', 'documentary', 'drama', 'family', 'fantasy', 'film-noir',
    'game-show', 'history', 'horror', 'music', 'musical', 'mystery',
    'news', 'reality-tv', 'romance', 'sci-fi', 'sport', 'talk-show',
    'thriller', 'war', 'western'
]

YEARS = ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018', '2015', '2010', '2000']

ORDER_BY_OPTIONS = [
    {'value': 'latest', 'label': 'Más recientes primero (latest)'},
    {'value': 'rating', 'label': 'Mayor calificación (rating)'},
    {'value': 'seeds', 'label': 'Más semillas / seeds'},
    {'value': 'peers', 'label': 'Más pares / peers'},
    {'value': 'year', 'label': 'Año de lanzamiento'}
]


@app.route('/')
def index():
    return render_template('index.html', genres=GENRES, years=YEARS, order_by_options=ORDER_BY_OPTIONS)


@app.route('/api/options')
def get_options():
    return jsonify({
        'genres': GENRES,
        'years': YEARS,
        'order_by': ORDER_BY_OPTIONS,
        'defaults': {
            'year': '2026',
            'genre': 'all',
            'min_rating': 7.0,
            'min_votes': 500,
            'rt_mode': 'if_available',
            'order_by': 'latest',
            'max_pages': 3
        }
    })


@app.route('/api/scan')
def scan_stream():
    """
    Server-Sent Events (SSE) endpoint to stream movie evaluation in real-time.
    """
    year = request.args.get('year', '2026')
    genre = request.args.get('genre', 'all')
    try:
        min_rating = float(request.args.get('min_rating', '7.0'))
    except ValueError:
        min_rating = 7.0

    try:
        min_votes = int(request.args.get('min_votes', '500'))
    except ValueError:
        min_votes = 500

    rt_mode = request.args.get('rt_mode', 'if_available')
    order_by = request.args.get('order_by', 'latest')
    keyword = request.args.get('keyword', '')
    quality = request.args.get('quality', 'all')
    custom_key = request.args.get('custom_key', '').strip() or None

    try:
        max_pages = int(request.args.get('max_pages', '3'))
        max_pages = max(1, min(max_pages, 10))
    except ValueError:
        max_pages = 3

    def event_stream():
        for event in scraper.scan_yts_stream(
            keyword=keyword,
            quality=quality,
            genre=genre,
            rating=str(int(min_rating)),
            year=year,
            order_by=order_by,
            min_rating=min_rating,
            min_votes=min_votes,
            rt_mode=rt_mode,
            custom_omdb_key=custom_key,
            start_page=1,
            max_pages=max_pages,
            max_workers=6
        ):
            json_data = json.dumps(event, ensure_ascii=False)
            yield f"data: {json_data}\n\n"

    return Response(event_stream(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive'
    })


@app.route('/api/scan_batch')
def scan_batch():
    """Non-streaming endpoint returning full results."""
    year = request.args.get('year', '2026')
    genre = request.args.get('genre', 'all')
    min_rating = float(request.args.get('min_rating', '7.0'))
    min_votes = int(request.args.get('min_votes', '500'))
    rt_mode = request.args.get('rt_mode', 'if_available')
    order_by = request.args.get('order_by', 'latest')
    keyword = request.args.get('keyword', '')
    quality = request.args.get('quality', 'all')
    custom_key = request.args.get('custom_key', '').strip() or None
    max_pages = min(int(request.args.get('max_pages', '2')), 5)

    passed = []
    discarded = []

    for p in range(1, max_pages + 1):
        movies = scraper.scan_yts_page(
            page=p,
            keyword=keyword,
            quality=quality,
            genre=genre,
            rating=str(int(min_rating)),
            year=year,
            order_by=order_by,
            min_rating=min_rating,
            min_votes=min_votes,
            rt_mode=rt_mode,
            custom_omdb_key=custom_key
        )
        for m in movies:
            if m.get('passed'):
                passed.append(m)
            else:
                discarded.append(m)

    return jsonify({
        'total_evaluated': len(passed) + len(discarded),
        'passed_count': len(passed),
        'discarded_count': len(discarded),
        'passed': passed,
        'discarded': discarded
    })


@app.route('/api/export', methods=['POST'])
def export_csv():
    """Exports passed movies list to CSV."""
    data = request.get_json() or {}
    movies = data.get('movies', [])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Título', 'Año', 'Calificación IMDb', 'Votos IMDb',
        'Tomatómetro (%)', 'Popcornómetro (%)', 'Géneros',
        'Ficha YTS', 'Ficha IMDb', 'Enlace Magnet (Principal)'
    ])

    for m in movies:
        magnets = m.get('torrents', [])
        primary_mag = magnets[0]['magnet'] if magnets else ''
        writer.writerow([
            m.get('title', ''),
            m.get('year', ''),
            m.get('imdb_rating', ''),
            m.get('imdb_votes', ''),
            m.get('rt_tomatometer') or 'N/A',
            m.get('rt_popcornmeter') or 'N/A',
            ', '.join(m.get('genres', [])),
            m.get('yts_url', ''),
            m.get('imdb_url', ''),
            primary_mag
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=peliculas_filtradas_yts.csv"}
    )


@app.route('/api/subtitles/<imdb_id>')
def get_subtitles_info(imdb_id):
    """Returns metadata for available Spanish subtitles for the given IMDb ID."""
    subs = subtitles.get_spanish_subtitles(imdb_id)
    return jsonify({'imdb_id': imdb_id, 'subtitles': subs})


@app.route('/api/subtitles/vtt/<imdb_id>')
def get_subtitles_vtt(imdb_id):
    """Returns WebVTT subtitles format for HTML5 video tracks."""
    srt_content, _ = subtitles.download_first_spanish_srt(imdb_id)
    if not srt_content:
        return Response("WEBVTT\n\n", mimetype="text/vtt")
    vtt_content = subtitles.srt_to_vtt(srt_content)
    return Response(
        vtt_content,
        mimetype="text/vtt",
        headers={
            "Content-Type": "text/vtt; charset=utf-8",
            "Access-Control-Allow-Origin": "*"
        }
    )


@app.route('/api/subtitles/download/<imdb_id>')
def download_subtitles_srt(imdb_id):
    """Downloads raw .srt file directly."""
    srt_content, fname = subtitles.download_first_spanish_srt(imdb_id)
    if not srt_content:
        return jsonify({'error': 'No se encontraron subtítulos en español para esta película'}), 404
    download_name = fname or f"{imdb_id}_es.srt"
    # Ensure safe ascii filename for Content-Disposition header
    safe_filename = re.sub(r'[^\w\.\- ]', '_', download_name)
    return Response(
        srt_content.encode('utf-8'),
        mimetype="application/x-subrip; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{safe_filename}\"",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@app.route('/api/latino/<imdb_id>')
def get_latino_sources(imdb_id):
    """Returns Spanish & Latino releases (Torrentio/Cinecalidad and DonTorrent) with clean torrent downloads and magnets."""
    title = request.args.get('title', '')
    year = request.args.get('year', '')
    items = latino_sources.search_all_spanish_sources(imdb_id, title, year)
    return jsonify({
        'imdb_id': imdb_id,
        'title': title,
        'year': year,
        'results': items,
        'dontorrent': items
    })


@app.route('/api/latino/torrent_download')
def download_latino_torrent():
    """Proxies and serves clean .torrent file to avoid browser referrer / CORS blocks."""
    torrent_url = request.args.get('url', '')
    filename = request.args.get('filename', 'pelicula_espanol.torrent')
    if not torrent_url:
        return jsonify({'error': 'URL de torrent no proporcionada'}), 400
    t_bytes = latino_sources.download_torrent_file(torrent_url)
    if not t_bytes:
        return jsonify({'error': 'No se pudo descargar el archivo torrent'}), 404
    if not filename.endswith('.torrent'):
        filename += '.torrent'
    return Response(
        t_bytes,
        mimetype="application/x-bittorrent",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


@app.route('/api/stremio/launch', methods=['GET', 'POST'])
def launch_stremio():
    """Directly launches local Stremio app with the provided magnet or torrent URI on the host machine."""
    magnet = request.args.get('magnet') or request.form.get('magnet', '')
    if not magnet:
        return jsonify({'success': False, 'error': 'No magnet provided'}), 400

    candidates = [
        os.path.expandvars(r'%LOCALAPPDATA%\Programs\LNV\Stremio-4\stremio.exe'),
        os.path.expandvars(r'%LOCALAPPDATA%\Smart Code OOD\Stremio\stremio.exe'),
        r'C:\Program Files\Stremio\stremio.exe',
        r'C:\Program Files (x86)\Stremio\stremio.exe'
    ]
    stremio_exe = next((c for c in candidates if os.path.exists(c)), None)
    if not stremio_exe:
        return jsonify({'success': False, 'error': 'Stremio not installed on host'}), 404

    try:
        subprocess.Popen([stremio_exe, magnet], shell=False)
        return jsonify({'success': True, 'launched': True, 'exe': stremio_exe})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print("Iniciando servidor de Películas en http://localhost:5000 ...")
    print(f"Claves autorizadas activas: {len(get_allowed_passwords())}")
    app.run(host='0.0.0.0', port=5000, debug=True)
