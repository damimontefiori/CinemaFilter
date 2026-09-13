"""
Flask Web Application for YTS Movie Filter by IMDb and Rotten Tomatoes.
"""

from flask import Flask, render_template, request, Response, jsonify
import json
import csv
import io
import scraper

app = Flask(__name__)

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
            # Format as SSE
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


if __name__ == '__main__':
    print("Iniciando servidor de Películas en http://localhost:5000 ...")
    app.run(host='0.0.0.0', port=5000, debug=True)
