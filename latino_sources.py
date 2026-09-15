"""
latino_sources.py - Sources for Latin American Spanish (Doblaje Latino) & Spanish audio movies.
Combines Torrentio (indexing Cinecalidad, TorrentGalaxy, TPB Dual Audio) and DonTorrent.
"""

import urllib.request
import urllib.parse
import ssl
import re
import json
import hashlib
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://www21.dontorrent.link/descargar-peliculas'
}

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_LATINO_CACHE = {}
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
    """Downloads raw .torrent bytes with proper headers and SSL context."""
    if not torrent_url:
        return None
    try:
        req = urllib.request.Request(torrent_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=8) as resp:
            return resp.read()
    except Exception as e:
        print(f"[latino_sources] Failed to download torrent file from {torrent_url}: {e}")
        return None


def search_torrentio_latino(imdb_id, title=""):
    """
    Queries Torrentio for real Spanish/Latino streams (including Cinecalidad, TorrentGalaxy, etc.)
    using the verified IMDb ID.
    """
    if not imdb_id:
        return []
    
    url = f"https://torrentio.strem.fun/stream/movie/{imdb_id}.json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    results = []

    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            streams = data.get('streams', [])
            for s in streams:
                raw_title = s.get('title', '')
                raw_name = s.get('name', '')
                combined = f"{raw_name} {raw_title}"

                # Strict detection of Spanish / Latino audio
                is_latino = bool(re.search(r'(latino|cinecalidad|dual|audio latino|español latino|esp latino)', combined, re.IGNORECASE))
                is_spanish = bool(re.search(r'(castellano|spanish|español|spa)', combined, re.IGNORECASE))

                if not (is_latino or is_spanish):
                    continue

                info_hash = s.get('infoHash')
                if not info_hash:
                    continue

                # Extract quality
                q_match = re.search(r'(4k|2160p|1080p|720p|bluray|web-dl|remux)', combined, re.IGNORECASE)
                quality = q_match.group(1).upper() if q_match else 'HD'

                # Extract seeders
                seed_match = re.search(r'👤\s*(\d+)', raw_title)
                seeders = int(seed_match.group(1)) if seed_match else 0

                # Extract size
                size_match = re.search(r'💾\s*([\d\.]+\s*(?:GB|MB))', raw_title)
                size_str = size_match.group(1) if size_match else ''

                # Clean release title
                first_line = raw_title.split('\n')[0].strip()
                display_title = first_line if len(first_line) > 5 else (title or 'Película')

                lang_label = "🇲🇽 Audio Latino" if is_latino else "🇪🇸 Castellano"
                source_name = 'Cinecalidad (P2P)' if 'cinecalidad' in combined.lower() else 'TorrentGalaxy / P2P'

                clean_name = title or display_title
                trackers = "tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fopen.demonii.com%3A1337%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
                magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(clean_name)}&{trackers}"

                results.append({
                    'title': display_title,
                    'quality': quality,
                    'size': size_str,
                    'seeders': seeders,
                    'lang': lang_label,
                    'is_latino': is_latino,
                    'info_hash': info_hash,
                    'magnet': magnet,
                    'torrent_url': None,
                    'source': source_name
                })
    except Exception as e:
        print(f"[latino_sources] Torrentio search error for {imdb_id}: {e}")

    return results


def search_all_spanish_sources(imdb_id, title, year=None):
    """
    Unified search combining Torrentio (Cinecalidad, TorrentGalaxy Latino) and DonTorrent.
    Returns sorted list: Latin American Spanish first, then by seeders.
    """
    cache_key = f"{imdb_id}_{title}_{year or ''}"
    if cache_key in _LATINO_CACHE:
        return _LATINO_CACHE[cache_key]

    combined_results = []
    seen_hashes = set()

    # 1. First priority: Torrentio (Cinecalidad and Latin American audio streams)
    if imdb_id:
        t_streams = search_torrentio_latino(imdb_id, title)
        for s in t_streams:
            ih = s.get('info_hash')
            if ih and ih not in seen_hashes:
                seen_hashes.add(ih)
                combined_results.append(s)

    # 2. Second priority: DonTorrent (Spanish releases)
    dt_items = search_dontorrent(title, year)
    for it in dt_items:
        ih = it.get('info_hash')
        if ih and ih in seen_hashes:
            continue
        if ih:
            seen_hashes.add(ih)
        combined_results.append(it)

    # Sort: Latino first, then seeders descending
    combined_results.sort(key=lambda x: (1 if x.get('is_latino') else 0, x.get('seeders', 0)), reverse=True)
    _LATINO_CACHE[cache_key] = combined_results
    return combined_results

