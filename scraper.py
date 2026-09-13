"""
Scraper and Evaluator Module for YTS Movies with IMDb and Rotten Tomatoes Filtering.
Filters:
  - IMDb Rating >= min_rating (default: 7.0)
  - IMDb Vote Count > min_votes (default: 500)
  - Rotten Tomatoes: Tomatometer >= 60% and Popcornmeter >= 60% (modes: if_available, strict, off)
"""

import urllib.request
import urllib.parse
import json
import re
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

OMDB_KEY_POOL = ['trilogy', 'thewdb']

# In-memory cache for ratings to speed up multiple runs
_RATINGS_CACHE = {}


def fetch_url(url, timeout=8):
    """Fetches URL content as string safely."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception:
        return ""


def build_yts_url(keyword="", quality="all", genre="all", rating="7", year="2026", order_by="latest", page=1):
    """Builds YTS browse-movies URL with filters."""
    base = "https://en.yts-official.biz/browse-movies"
    params = {
        'keyword': keyword or '',
        'quality': quality or 'all',
        'genre': genre or 'all',
        'rating': rating if rating is not None else '7',
        'year': year or '2026',
        'order_by': order_by or 'latest',
        'page': str(page)
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def parse_movie_card(wrap):
    """Parses basic card info from YTS browse page."""
    title_el = wrap.select_one(".browse-movie-title")
    year_el = wrap.select_one(".browse-movie-year")
    rating_el = wrap.select_one(".rating")
    link_el = wrap.select_one("a.browse-movie-link")
    img_el = wrap.select_one("img")

    title = title_el.text.strip() if title_el else "Unknown Title"
    year = year_el.text.strip() if year_el else ""
    yts_rating = rating_el.text.strip() if rating_el else ""
    link = link_el['href'] if link_el and 'href' in link_el.attrs else ""
    if link and link.startswith('/'):
        link = f"https://en.yts-official.biz{link}"

    img = img_el['src'] if img_el and 'src' in img_el.attrs else ""
    if img and img.startswith('/'):
        img = f"https://en.yts-official.biz{img}"

    return {
        'title': title,
        'year': year,
        'yts_rating': yts_rating,
        'yts_url': link,
        'img': img
    }


def parse_movie_detail(movie_info):
    """Fetches and parses detail page for IMDb ID, genres, synopsis, and torrents/magnets."""
    url = movie_info.get('yts_url')
    if not url:
        return movie_info

    html = fetch_url(url, timeout=8)
    if not html:
        return movie_info

    soup = BeautifulSoup(html, "html.parser")

    # IMDb ID
    imdb_id = None
    imdb_link = soup.find('a', href=re.compile(r'imdb\.com/title/(tt\d+)'))
    if imdb_link:
        m = re.search(r'tt\d+', imdb_link['href'])
        if m:
            imdb_id = m.group(0)

    # Fallback search for tt in any link/script
    if not imdb_id:
        m_any = re.search(r'tt\d{6,9}', html)
        if m_any:
            imdb_id = m_any.group(0)

    movie_info['imdb_id'] = imdb_id
    movie_info['imdb_url'] = f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else None

    # Synopsis
    synopsis = ""
    syn_el = soup.select_one("#synopsis p, .summary p, #movie-info p")
    if syn_el:
        synopsis = syn_el.text.strip()
    movie_info['synopsis'] = synopsis

    # Genres
    genres = []
    genre_els = soup.select(".sub-nav a, h2 a[href*='genre']")
    for g in genre_els:
        g_text = g.text.strip()
        if g_text and g_text not in genres:
            genres.append(g_text)
    movie_info['genres'] = genres

    # Torrents & Magnets
    torrents = []
    modals = soup.select(".modal-torrent")
    seen_magnets = set()

    for m in modals:
        qual_el = m.select_one(".modal-quality span")
        quality = qual_el.text.strip() if qual_el else "Unknown"

        p_types = [p.text.strip() for p in m.select("p.quality-size")]
        t_type = p_types[0] if len(p_types) > 0 else ""
        t_size = p_types[1] if len(p_types) > 1 else ""

        magnet_el = m.select_one("a.magnet-download, a[href^='magnet:']")
        magnet_href = magnet_el['href'] if magnet_el and 'href' in magnet_el.attrs else ""

        if magnet_href and magnet_href not in seen_magnets:
            seen_magnets.add(magnet_href)
            torrents.append({
                'quality': quality,
                'type': t_type,
                'size': t_size,
                'magnet': magnet_href
            })

    # Fallback to any magnets on page if modal-torrent was empty
    if not torrents:
        for a in soup.find_all('a', href=re.compile(r'^magnet:\?')):
            href = a['href']
            if href not in seen_magnets:
                seen_magnets.add(href)
                # extract quality from title
                m_q = re.search(r'(720p|1080p|2160p|4K)', href, re.I)
                qual = m_q.group(1) if m_q else "Torrent"
                torrents.append({
                    'quality': qual,
                    'type': '',
                    'size': '',
                    'magnet': href
                })

    movie_info['torrents'] = torrents
    return movie_info


def get_imdb_omdb_data(imdb_id, title="", year="", custom_key=None):
    """Retrieves IMDb rating, votes, and metadata from OMDb."""
    if not imdb_id and not title:
        return {'imdb_rating': 0.0, 'imdb_votes': 0, 'omdb_rt': None}

    cache_key = f"omdb_{imdb_id or title}"
    if cache_key in _RATINGS_CACHE:
        return _RATINGS_CACHE[cache_key]

    keys = [custom_key] if custom_key else []
    keys += [k for k in OMDB_KEY_POOL if k not in keys]

    data = None
    for k in keys:
        try:
            if imdb_id:
                url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={k}"
            else:
                url = f"http://www.omdbapi.com/?t={urllib.parse.quote(title)}&y={year}&apikey={k}"

            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=4) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get('Response') == 'True':
                    data = res
                    break
        except Exception:
            continue

    if not data:
        result = {
            'imdb_rating': 0.0,
            'imdb_votes': 0,
            'omdb_rt': None,
            'director': '',
            'actors': '',
            'runtime': '',
            'plot': ''
        }
        _RATINGS_CACHE[cache_key] = result
        return result

    # Rating
    raw_rating = data.get('imdbRating')
    rating = 0.0
    if raw_rating and raw_rating != 'N/A':
        try:
            rating = float(raw_rating)
        except ValueError:
            rating = 0.0

    # Votes
    raw_votes = data.get('imdbVotes')
    votes = 0
    if raw_votes and raw_votes != 'N/A':
        try:
            votes = int(raw_votes.replace(',', ''))
        except ValueError:
            votes = 0

    # RT rating in OMDb
    omdb_rt = None
    for r_entry in data.get('Ratings', []):
        if r_entry.get('Source') == 'Rotten Tomatoes':
            val = r_entry.get('Value', '').replace('%', '').strip()
            if val.isdigit():
                omdb_rt = int(val)

    result = {
        'imdb_rating': rating,
        'imdb_votes': votes,
        'omdb_rt': omdb_rt,
        'director': data.get('Director', ''),
        'actors': data.get('Actors', ''),
        'runtime': data.get('Runtime', ''),
        'plot': data.get('Plot', '')
    }
    _RATINGS_CACHE[cache_key] = result
    return result


def get_rotten_tomatoes_data(title, year=None, known_tomatometer=None):
    """
    Retrieves Tomatometer and Popcornmeter (Audience Score) directly from Rotten Tomatoes.
    """
    cache_key = f"rt_{title}_{year}"
    if cache_key in _RATINGS_CACHE:
        return _RATINGS_CACHE[cache_key]

    clean_title = re.sub(r'\(.*?\)', '', title).strip()
    search_url = f"https://www.rottentomatoes.com/search?search={urllib.parse.quote(clean_title)}"

    try:
        req = urllib.request.Request(search_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("search-page-media-row")

        target_link = None
        target_tomatometer = known_tomatometer

        for r in rows:
            r_year = r.get('release-year', '').strip()
            link_el = r.select_one("a[slot='title']")
            if not link_el:
                continue

            r_title = link_el.text.strip().lower()
            if r_title == clean_title.lower() or (year and r_year == str(year)):
                target_link = link_el['href']
                t_score = r.get('tomatometer-score')
                if t_score and t_score.isdigit():
                    target_tomatometer = int(t_score)
                break

        if not target_link and rows:
            first_link = rows[0].select_one("a[slot='title']")
            if first_link:
                target_link = first_link['href']
                t_score = rows[0].get('tomatometer-score')
                if t_score and t_score.isdigit():
                    target_tomatometer = int(t_score)

        if not target_link:
            res = {
                'rt_url': None,
                'tomatometer': known_tomatometer,
                'popcornmeter': None
            }
            _RATINGS_CACHE[cache_key] = res
            return res

        # Fetch detail page for audience score / popcornmeter
        req2 = urllib.request.Request(target_link, headers=HEADERS)
        with urllib.request.urlopen(req2, timeout=6) as resp2:
            m_html = resp2.read().decode('utf-8', errors='ignore')

        popcornmeter = None
        tomatometer = target_tomatometer

        # Look for audienceScore & criticsScore json
        m = re.search(r'("audienceScore":\{.*?"criticsScore":\{.*?\})', m_html)
        if m:
            frag = "{" + m.group(1) + "}"
            try:
                data = json.loads(frag)
                aud = data.get('audienceScore', {}).get('score')
                if aud and str(aud).isdigit():
                    popcornmeter = int(aud)
                crit = data.get('criticsScore', {}).get('score')
                if crit and str(crit).isdigit():
                    tomatometer = int(crit)
            except Exception:
                pass

        if not tomatometer:
            m_crit = re.search(r'"criticsScore":\{.*?"score":"?(\d+)"?', m_html)
            if m_crit:
                tomatometer = int(m_crit.group(1))

        if not popcornmeter:
            m_aud = re.search(r'"audienceScore":\{.*?"score":"?(\d+)"?', m_html)
            if m_aud:
                popcornmeter = int(m_aud.group(1))

        res = {
            'rt_url': target_link,
            'tomatometer': tomatometer,
            'popcornmeter': popcornmeter
        }
        _RATINGS_CACHE[cache_key] = res
        return res

    except Exception:
        res = {
            'rt_url': None,
            'tomatometer': known_tomatometer,
            'popcornmeter': None
        }
        _RATINGS_CACHE[cache_key] = res
        return res


def evaluate_movie(movie, min_rating=7.0, min_votes=500, rt_mode='if_available', custom_omdb_key=None):
    """
    Evaluates a movie against the criteria:
    - Rating >= min_rating
    - IMDb Votes > min_votes
    - Rotten Tomatoes (+60% Tomatometer & Popcornmeter depending on rt_mode)
    """
    # 1. Detail page enrichment (IMDb ID, magnets, synopsis)
    parse_movie_detail(movie)

    # 2. IMDb Rating & Votes via OMDb
    omdb = get_imdb_omdb_data(
        movie.get('imdb_id'),
        title=movie.get('title'),
        year=movie.get('year'),
        custom_key=custom_omdb_key
    )

    # Determine IMDb rating
    imdb_rating = omdb.get('imdb_rating') or 0.0
    if imdb_rating == 0.0 and movie.get('yts_rating'):
        m_r = re.search(r'([\d.]+)', movie['yts_rating'])
        if m_r:
            try:
                imdb_rating = float(m_r.group(1))
            except ValueError:
                pass

    imdb_votes = omdb.get('imdb_votes', 0)
    movie['imdb_rating'] = imdb_rating
    movie['imdb_votes'] = imdb_votes
    movie['omdb_plot'] = omdb.get('plot') or movie.get('synopsis', '')
    movie['director'] = omdb.get('director', '')
    movie['actors'] = omdb.get('actors', '')
    movie['runtime'] = omdb.get('runtime', '')

    # 3. Rotten Tomatoes
    rt_data = get_rotten_tomatoes_data(
        movie.get('title', ''),
        year=movie.get('year'),
        known_tomatometer=omdb.get('omdb_rt')
    )
    movie['rt_tomatometer'] = rt_data.get('tomatometer')
    movie['rt_popcornmeter'] = rt_data.get('popcornmeter')
    movie['rt_url'] = rt_data.get('rt_url')

    # 4. Evaluation Logic
    passed = True
    reason = "Cumple con todos los filtros"

    # Step A: Rating check
    if imdb_rating < min_rating:
        passed = False
        reason = f"Calificación IMDb {imdb_rating:.1f} es menor al mínimo requerido ({min_rating:.1f})"
    # Step B: Vote count check
    elif imdb_votes <= min_votes:
        passed = False
        reason = f"Votos en IMDb insuficientes: {imdb_votes:,} votos (se requiere más de {min_votes:,})"
    # Step C: Rotten Tomatoes check
    else:
        tom = movie['rt_tomatometer']
        pop = movie['rt_popcornmeter']

        if rt_mode == 'strict':
            if tom is None or pop is None:
                passed = False
                reason = "Sin registro completo en Rotten Tomatoes (Modo Estricto exige ambos scores)"
            elif tom < 60 or pop < 60:
                passed = False
                reason = f"Rotten Tomatoes no alcanza 60%: Tomatómetro {tom}% | Popcornómetro {pop}%"
            else:
                passed = True
                reason = f"Cumple filtros: IMDb {imdb_rating:.1f} ({imdb_votes:,} votos) y RT {tom}%/{pop}%"

        elif rt_mode == 'if_available':
            if tom is not None or pop is not None:
                # If either score exists, check if any fail the 60% requirement
                failed_tom = (tom is not None and tom < 60)
                failed_pop = (pop is not None and pop < 60)
                if failed_tom or failed_pop:
                    passed = False
                    reason = f"Rotten Tomatoes bajo el 60%: Tomatómetro {tom or 'N/A'}% | Popcornómetro {pop or 'N/A'}%"
                else:
                    passed = True
                    reason = f"Cumple filtros: IMDb {imdb_rating:.1f} ({imdb_votes:,} votos) y RT aprobado"
            else:
                passed = True
                reason = f"Cumple filtros: IMDb {imdb_rating:.1f} ({imdb_votes:,} votos). Sin calificar en RT"
        else:
            # rt_mode == 'off'
            passed = True
            reason = f"Cumple filtros: IMDb {imdb_rating:.1f} ({imdb_votes:,} votos)"

    movie['passed'] = passed
    movie['reason'] = reason
    return movie


def scan_yts_page(page=1, keyword="", quality="all", genre="all", rating="7", year="2026", order_by="latest",
                  min_rating=7.0, min_votes=500, rt_mode='if_available', custom_omdb_key=None, max_workers=6):
    """
    Scans a single YTS browse page and evaluates all movies.
    Yields or returns the evaluated movies.
    """
    url = build_yts_url(keyword, quality, genre, rating, year, order_by, page)
    html = fetch_url(url, timeout=10)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    wraps = soup.select(".browse-movie-wrap")
    if not wraps:
        return []

    movies_raw = [parse_movie_card(w) for w in wraps]

    # Evaluate in parallel
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_movie = {
            executor.submit(evaluate_movie, m, min_rating, min_votes, rt_mode, custom_omdb_key): m
            for m in movies_raw
        }
        for future in as_completed(future_to_movie):
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                m_orig = future_to_movie[future]
                m_orig['passed'] = False
                m_orig['reason'] = f"Error evaluando película: {e}"
                results.append(m_orig)

    return results


def scan_yts_stream(keyword="", quality="all", genre="all", rating="7", year="2026", order_by="latest",
                    min_rating=7.0, min_votes=500, rt_mode='if_available', custom_omdb_key=None,
                    start_page=1, max_pages=3, max_workers=6):
    """
    Generator that scans multiple pages and yields progress events for Server-Sent Events (SSE).
    """
    total_evaluated = 0
    total_passed = 0
    total_discarded = 0

    yield {
        'type': 'start',
        'year': year,
        'genre': genre,
        'min_rating': min_rating,
        'min_votes': min_votes,
        'rt_mode': rt_mode,
        'max_pages': max_pages
    }

    for p in range(start_page, start_page + max_pages):
        page_url = build_yts_url(keyword, quality, genre, rating, year, order_by, p)
        yield {
            'type': 'page_start',
            'page': p,
            'url': page_url
        }

        html = fetch_url(page_url, timeout=10)
        if not html:
            yield {
                'type': 'page_empty',
                'page': p,
                'message': 'No se pudo obtener la página de YTS o no hay más resultados.'
            }
            break

        soup = BeautifulSoup(html, "html.parser")
        wraps = soup.select(".browse-movie-wrap")
        if not wraps:
            yield {
                'type': 'page_empty',
                'page': p,
                'message': 'No se encontraron más películas en esta página.'
            }
            break

        movies_raw = [parse_movie_card(w) for w in wraps]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_movie = {
                executor.submit(evaluate_movie, m, min_rating, min_votes, rt_mode, custom_omdb_key): m
                for m in movies_raw
            }
            for future in as_completed(future_to_movie):
                try:
                    m = future.result()
                except Exception as e:
                    m = future_to_movie[future]
                    m['passed'] = False
                    m['reason'] = f"Error: {e}"

                total_evaluated += 1
                if m['passed']:
                    total_passed += 1
                else:
                    total_discarded += 1

                yield {
                    'type': 'movie',
                    'movie': m,
                    'total_evaluated': total_evaluated,
                    'total_passed': total_passed,
                    'total_discarded': total_discarded
                }

    yield {
        'type': 'complete',
        'total_evaluated': total_evaluated,
        'total_passed': total_passed,
        'total_discarded': total_discarded
    }
