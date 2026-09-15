"""
latino_sources.py - Sources for Latin American Spanish (Doblaje Latino) movies.
Scrapes DonTorrent for Spanish torrents and integrates MultiEmbed Latino audio streams.
"""

import urllib.request
import urllib.parse
import ssl
import re
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www21.dontorrent.link/descargar-peliculas'
}

# SSL context for sites with custom/self-signed certs
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# In-memory cache: query -> list of torrent dicts
_LATINO_CACHE = {}

# Active mirror base
_DONTORRENT_BASE = 'https://www21.dontorrent.link'


def get_active_dontorrent_base():
    """Returns the working base URL for DonTorrent, checking for redirects."""
    global _DONTORRENT_BASE
    candidate_urls = [_DONTORRENT_BASE, 'https://dontorrent.in/', 'https://dontorrent.link/']
    for u in candidate_urls:
        try:
            req = urllib.request.Request(u, headers=HEADERS)
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=4) as resp:
                final_url = resp.geturl().rstrip('/')
                _DONTORRENT_BASE = final_url
                return _DONTORRENT_BASE
        except Exception:
            continue
    return _DONTORRENT_BASE


def search_dontorrent(title, year=None):
    """
    Searches DonTorrent for releases in Spanish / Latin.
    Returns list of dicts:
    [{ 'title': ..., 'quality': ..., 'detail_url': ..., 'torrent_url': ... }, ...]
    """
    if not title:
        return []

    # Clean title for searching (strip punctuation, colons, subtitles)
    clean_title = re.sub(r'[:\-–—].*$', '', title).strip()
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', clean_title).strip()
    if not clean_title:
        clean_title = title

    cache_key = f"{clean_title}_{year or ''}"
    if cache_key in _LATINO_CACHE:
        return _LATINO_CACHE[cache_key]

    base = get_active_dontorrent_base()
    search_url = f"{base}/peliculas/buscar"
    results = []

    try:
        data = urllib.parse.urlencode({'campo': 'titulo', 'valor': clean_title}).encode('utf-8')
        req = urllib.request.Request(search_url, data=data, headers=HEADERS)
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=7) as resp:
            soup = BeautifulSoup(resp.read().decode('utf-8', errors='ignore'), 'html.parser')
            # Look for movie links: <a href="/pelicula/...">Quality</a>
            links = soup.find_all('a', href=re.compile(r'/pelicula/'))
            seen_urls = set()

            for a in links:
                href = a.get('href', '')
                quality_text = a.text.strip() or 'HD'
                if not href or href in seen_urls:
                    continue
                seen_urls.add(href)

                full_detail = f"{base}{href}" if href.startswith('/') else href

                # Extract movie slug/title from href: /pelicula/12345/Movie-Name
                slug_parts = href.strip('/').split('/')
                slug_name = slug_parts[-1] if len(slug_parts) >= 3 else clean_title
                display_name = slug_name.replace('-', ' ')

                # Determine quality tag
                q_match = re.search(r'(4K|1080p|720p|DVDRip|MicroHD|BluRay|BDremux)', href, re.IGNORECASE)
                qual = q_match.group(1).upper() if q_match else quality_text

                results.append({
                    'title': f"{display_name} ({qual})",
                    'quality': qual,
                    'detail_url': full_detail,
                    'torrent_url': None,
                    'source': 'DonTorrent'
                })

            # For top 3 matches, eagerly extract the direct .torrent URL
            for item in results[:3]:
                try:
                    d_req = urllib.request.Request(item['detail_url'], headers=HEADERS)
                    with urllib.request.urlopen(d_req, context=_SSL_CTX, timeout=5) as d_resp:
                        d_soup = BeautifulSoup(d_resp.read().decode('utf-8', errors='ignore'), 'html.parser')
                        t_link = d_soup.find('a', href=re.compile(r'\.torrent$'))
                        if t_link and t_link.get('href'):
                            t_url = t_link['href']
                            if t_url.startswith('//'):
                                t_url = f"https:{t_url}"
                            elif t_url.startswith('/'):
                                t_url = f"{base}{t_url}"
                            item['torrent_url'] = t_url
                except Exception as e:
                    print(f"[latino_sources] Failed to extract torrent link for {item['detail_url']}: {e}")

    except Exception as e:
        print(f"[latino_sources] Search error on DonTorrent for '{clean_title}': {e}")

    _LATINO_CACHE[cache_key] = results
    return results


def get_latino_stream_url(imdb_id):
    """
    Returns the instant CDN streaming URL with Latin American Spanish audio option.
    MultiEmbed includes [LAT] audio server natively.
    """
    if not imdb_id:
        return None
    return f"https://multiembed.mov/?video_id={imdb_id}"
