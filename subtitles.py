"""
subtitles.py - Multi-source Spanish Subtitle extraction and WebVTT conversion for CinemaFilter.
Supports OpenSubtitles v3 (via Stremio CDN protocol) and YIFY Subtitles fallback.
"""

import urllib.request
import re
import zipfile
import io
import json
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# In-memory cache: imdb_id -> list of subtitles info
_SUBS_CACHE = {}
# In-memory cache for downloaded VTT/SRT: cache_key -> (content_bytes, filename)
_FILE_CACHE = {}

SPANISH_LANG_CODES = {'spa', 'es', 'es-mx', 'es-es', 'spa-es', 'spa-mx', 'spanish', 'español'}


def get_spanish_subtitles(imdb_id):
    """
    Fetches available Spanish subtitles for a given IMDb ID across multiple sources.
    Returns a list of dicts:
    [{ 'title': ..., 'download_url': ..., 'zip_url': ..., 'source': ..., 'lang': 'Español' }, ...]
    """
    if not imdb_id:
        return []

    if imdb_id in _SUBS_CACHE:
        return _SUBS_CACHE[imdb_id]

    results = []

    # 1. Primary: OpenSubtitles v3 via Stremio CDN (broadest movie coverage, fast JSON, no API key needed)
    try:
        url = f"https://opensubtitles-v3.strem.io/subtitles/movie/{imdb_id}.json"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            subs = data.get('subtitles', [])
            for s in subs:
                lang = (s.get('lang') or '').lower()
                if lang in SPANISH_LANG_CODES:
                    sub_title = (
                        s.get('subtitleFileName')
                        or s.get('movieReleaseName')
                        or f"{imdb_id} Español ({s.get('releaseGroup', 'HD')})"
                    )
                    results.append({
                        'title': sub_title,
                        'download_url': s.get('url'),
                        'source': 'OpenSubtitles v3',
                        'lang': 'Español'
                    })
    except Exception as e:
        print(f"[subtitles] OpenSubtitles lookup failed for {imdb_id}: {e}")

    # 2. Secondary: YIFY Subtitles (specifically synchronized with YTS rips)
    try:
        url = f"https://yifysubtitles.ch/movie-imdb/{imdb_id}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'html.parser')
            rows = soup.select('table tr')
            for r in rows:
                row_text = r.text.lower()
                if 'spanish' in row_text or 'español' in row_text:
                    link_el = r.find('a', href=re.compile(r'/subtitles/'))
                    if link_el:
                        sub_name = link_el.text.strip().replace('subtitle ', '')
                        detail_path = link_el['href']
                        full_detail_url = f"https://yifysubtitles.ch{detail_path}" if not detail_path.startswith('http') else detail_path
                        
                        slug_match = re.search(r'/subtitles/([^/]+)', detail_path)
                        zip_url = None
                        if slug_match:
                            zip_url = f"https://yifysubtitles.ch/subtitle/{slug_match.group(1)}.zip"

                        results.append({
                            'title': sub_name,
                            'detail_url': full_detail_url,
                            'zip_url': zip_url,
                            'source': 'YTS / YIFY Subtitles',
                            'lang': 'Español'
                        })
    except Exception as e:
        print(f"[subtitles] YifySubtitles lookup failed for {imdb_id}: {e}")

    _SUBS_CACHE[imdb_id] = results
    return results


def download_first_spanish_srt(imdb_id):
    """
    Downloads the first available Spanish subtitle for the IMDb ID.
    Returns (srt_text, filename).
    """
    subs = get_spanish_subtitles(imdb_id)
    if not subs:
        return None, None

    cache_key = f"srt_{imdb_id}"
    if cache_key in _FILE_CACHE:
        return _FILE_CACHE[cache_key]

    for sub in subs:
        # A. Direct download URL (from OpenSubtitles v3)
        if sub.get('download_url'):
            dl_url = sub['download_url']
            try:
                req = urllib.request.Request(dl_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    raw = resp.read()
                    for enc in ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']:
                        try:
                            srt_text = raw.decode(enc)
                            fname = sub.get('title', f"{imdb_id}_es.srt")
                            if not fname.endswith('.srt'):
                                fname += '.srt'
                            _FILE_CACHE[cache_key] = (srt_text, fname)
                            return srt_text, fname
                        except UnicodeDecodeError:
                            continue
            except Exception as e:
                print(f"[subtitles] Direct download failed for {dl_url}: {e}")

        # B. Zip download URL (from YIFY Subtitles)
        zip_url = sub.get('zip_url')
        detail_url = sub.get('detail_url')

        if not zip_url and detail_url:
            try:
                req = urllib.request.Request(detail_url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=6) as resp:
                    soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'html.parser')
                    dl_link = soup.find('a', href=re.compile(r'\.zip$'))
                    if dl_link:
                        zip_url = dl_link['href']
                        if not zip_url.startswith('http'):
                            zip_url = f"https://yifysubtitles.ch{zip_url}"
            except Exception as e:
                print(f"[subtitles] Error extracting zip from detail page: {e}")

        if zip_url:
            try:
                req_headers = dict(HEADERS)
                if detail_url:
                    req_headers['Referer'] = detail_url
                req = urllib.request.Request(zip_url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    zip_bytes = resp.read()
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        for fname in zf.namelist():
                            if fname.lower().endswith('.srt'):
                                raw_content = zf.read(fname)
                                for enc in ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']:
                                    try:
                                        srt_text = raw_content.decode(enc)
                                        _FILE_CACHE[cache_key] = (srt_text, fname)
                                        return srt_text, fname
                                    except UnicodeDecodeError:
                                        continue
            except Exception as e:
                print(f"[subtitles] Error downloading zip {zip_url}: {e}")

    return None, None


def srt_to_vtt(srt_text):
    """
    Converts SubRip (.srt) format to WebVTT format for HTML5 video <track>.
    """
    if not srt_text:
        return "WEBVTT\n\n"

    # Normalize line endings
    text = srt_text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Replace timestamp comma with dot: 00:01:23,456 --> 00:01:23.456
    text = re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})', r'\1.\2', text)
    
    return "WEBVTT\n\n" + text.strip() + "\n"
