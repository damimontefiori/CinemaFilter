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
                            # Eagerly compute magnet link so it can be used with Stremio or WebTorrent
                            t_bytes = download_torrent_file(t_url)
                            if t_bytes:
                                ih = extract_info_hash_from_torrent(t_bytes)
                                if ih:
                                    item['info_hash'] = ih
                                    item['magnet'] = f"magnet:?xt=urn:btih:{ih}&dn={urllib.parse.quote(item['title'])}&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fopen.demonii.com%3A1337%2Fannounce"
                except Exception as e:
                    print(f"[latino_sources] Failed to extract torrent link for {item['detail_url']}: {e}")

    except Exception as e:
        print(f"[latino_sources] Search error on DonTorrent for '{clean_title}': {e}")

    _LATINO_CACHE[cache_key] = results
    return results


import hashlib

def extract_info_hash_from_torrent(b):
    """Parses bencoded info dict from torrent bytes and returns hex SHA-1 info_hash."""
    idx = b.find(b'4:info')
    if idx == -1:
        return None
    start = idx + 6
    if b[start:start+1] != b'd':
        return None
    depth = 0
    pos = start
    while pos < len(b):
        char = b[pos:pos+1]
        if char == b'd' or char == b'l':
            depth += 1
            pos += 1
        elif char == b'e':
            depth -= 1
            pos += 1
            if depth == 0:
                info_bytes = b[start:pos]
                return hashlib.sha1(info_bytes).hexdigest()
        elif char == b'i':
            e_idx = b.find(b'e', pos)
            if e_idx == -1:
                break
            pos = e_idx + 1
        elif char.isdigit():
            colon_idx = b.find(b':', pos)
            if colon_idx == -1:
                break
            str_len = int(b[pos:colon_idx])
            pos = colon_idx + 1 + str_len
        else:
            pos += 1
    return None


def download_torrent_file(torrent_url):
    """
    Downloads raw .torrent bytes with proper headers and SSL context.
    Returns bytes or None.
    """
    if not torrent_url:
        return None
    try:
        req = urllib.request.Request(torrent_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=8) as resp:
            return resp.read()
    except Exception as e:
        print(f"[latino_sources] Failed to download torrent file from {torrent_url}: {e}")
        return None

