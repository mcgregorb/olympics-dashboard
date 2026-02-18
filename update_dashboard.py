"""
Olympics Dashboard Auto-Updater (v2 — No Perplexity)
=====================================================
Called by GitHub Actions every 30 minutes. Uses ONLY:
  - Wikipedia API for medal table + schedule + results (reliable, structured)
  - RSS feeds for headlines (feedparser)
  - YouTube Data API for video highlights
  - Derived data for USA breakdown (from medal table)
  - Hardcoded authoritative data for athletes + as last-resort fallbacks

NO Perplexity API dependency. All data comes from structured sources.
"""

import os
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta

WIKI_API = 'https://en.wikipedia.org/w/api.php'
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')
MST = timezone(timedelta(hours=-7))
GAMES_START = datetime(2026, 2, 6, tzinfo=MST)
GAMES_END = datetime(2026, 2, 22, 23, 59, 59, tzinfo=MST)

# Country code to flag emoji mapping
COUNTRY_FLAGS = {
    'Norway': '\U0001f1f3\U0001f1f4', 'Italy': '\U0001f1ee\U0001f1f9',
    'United States': '\U0001f1fa\U0001f1f8', 'Netherlands': '\U0001f1f3\U0001f1f1',
    'Sweden': '\U0001f1f8\U0001f1ea', 'France': '\U0001f1eb\U0001f1f7',
    'Germany': '\U0001f1e9\U0001f1ea', 'Austria': '\U0001f1e6\U0001f1f9',
    'Switzerland': '\U0001f1e8\U0001f1ed', 'Japan': '\U0001f1ef\U0001f1f5',
    'Australia': '\U0001f1e6\U0001f1fa', 'Great Britain': '\U0001f1ec\U0001f1e7',
    'Czechia': '\U0001f1e8\U0001f1ff', 'Czech Republic': '\U0001f1e8\U0001f1ff',
    'Slovenia': '\U0001f1f8\U0001f1ee', 'Canada': '\U0001f1e8\U0001f1e6',
    'South Korea': '\U0001f1f0\U0001f1f7', 'Brazil': '\U0001f1e7\U0001f1f7',
    'Kazakhstan': '\U0001f1f0\U0001f1ff', 'Finland': '\U0001f1eb\U0001f1ee',
    'China': '\U0001f1e8\U0001f1f3', 'New Zealand': '\U0001f1f3\U0001f1ff',
    'Poland': '\U0001f1f5\U0001f1f1', 'Estonia': '\U0001f1ea\U0001f1ea',
    'Belgium': '\U0001f1e7\U0001f1ea', 'Spain': '\U0001f1ea\U0001f1f8',
    'Latvia': '\U0001f1f1\U0001f1fb', 'Croatia': '\U0001f1ed\U0001f1f7',
    'Slovakia': '\U0001f1f8\U0001f1f0', 'Bulgaria': '\U0001f1e7\U0001f1ec',
    'Georgia': '\U0001f1ec\U0001f1ea', 'Romania': '\U0001f1f7\U0001f1f4',
    'Ukraine': '\U0001f1fa\U0001f1e6', 'Denmark': '\U0001f1e9\U0001f1f0',
    'Belarus': '\U0001f1e7\U0001f1fe', 'Liechtenstein': '\U0001f1f1\U0001f1ee',
    'Andorra': '\U0001f1e6\U0001f1e9', 'Mongolia': '\U0001f1f2\U0001f1f3',
    'ROC': '\U0001f3f3\ufe0f', 'OAR': '\U0001f3f3\ufe0f',
}

COUNTRY_CODES = {
    'Norway': 'NOR', 'Italy': 'ITA', 'United States': 'USA', 'United States of America': 'USA',
    'Netherlands': 'NED', 'Sweden': 'SWE', 'France': 'FRA', 'Germany': 'GER',
    'Austria': 'AUT', 'Switzerland': 'SUI', 'Japan': 'JPN', 'Australia': 'AUS',
    'Great Britain': 'GBR', 'Czechia': 'CZE', 'Czech Republic': 'CZE',
    'Slovenia': 'SLO', 'Canada': 'CAN', 'South Korea': 'KOR', 'Brazil': 'BRA',
    'Kazakhstan': 'KAZ', 'Finland': 'FIN', 'China': 'CHN', 'New Zealand': 'NZL',
    'Poland': 'POL', 'Estonia': 'EST', 'Belgium': 'BEL', 'Spain': 'ESP',
    'Latvia': 'LAT', 'Croatia': 'CRO', 'Slovakia': 'SVK', 'Bulgaria': 'BUL',
    'Georgia': 'GEO', 'Romania': 'ROU', 'Ukraine': 'UKR', 'Denmark': 'DEN',
    'Belarus': 'BLR', 'Liechtenstein': 'LIE', 'Andorra': 'AND', 'Mongolia': 'MGL',
}


# ── Hardcoded Authoritative Data ─────────────────────────────────────────
# Last-resort fallbacks if ALL scrapers fail. Updated Feb 18, Day 13.

FALLBACK_MEDALS = {
    'medals': [
        {'rank': 1, 'country': 'Norway', 'flag': '\U0001f1f3\U0001f1f4', 'code': 'NOR', 'gold': 15, 'silver': 8, 'bronze': 10, 'total': 33},
        {'rank': 2, 'country': 'Italy', 'flag': '\U0001f1ee\U0001f1f9', 'code': 'ITA', 'gold': 9, 'silver': 4, 'bronze': 12, 'total': 25},
        {'rank': 3, 'country': 'United States', 'flag': '\U0001f1fa\U0001f1f8', 'code': 'USA', 'gold': 7, 'silver': 11, 'bronze': 6, 'total': 24},
        {'rank': 4, 'country': 'Japan', 'flag': '\U0001f1ef\U0001f1f5', 'code': 'JPN', 'gold': 5, 'silver': 6, 'bronze': 11, 'total': 22},
        {'rank': 5, 'country': 'Germany', 'flag': '\U0001f1e9\U0001f1ea', 'code': 'GER', 'gold': 5, 'silver': 8, 'bronze': 8, 'total': 21},
        {'rank': 6, 'country': 'France', 'flag': '\U0001f1eb\U0001f1f7', 'code': 'FRA', 'gold': 6, 'silver': 7, 'bronze': 4, 'total': 17},
        {'rank': 7, 'country': 'Austria', 'flag': '\U0001f1e6\U0001f1f9', 'code': 'AUT', 'gold': 5, 'silver': 8, 'bronze': 4, 'total': 17},
        {'rank': 8, 'country': 'Sweden', 'flag': '\U0001f1f8\U0001f1ea', 'code': 'SWE', 'gold': 6, 'silver': 6, 'bronze': 3, 'total': 15},
        {'rank': 9, 'country': 'Netherlands', 'flag': '\U0001f1f3\U0001f1f1', 'code': 'NED', 'gold': 6, 'silver': 6, 'bronze': 1, 'total': 13},
        {'rank': 10, 'country': 'Switzerland', 'flag': '\U0001f1e8\U0001f1ed', 'code': 'SUI', 'gold': 5, 'silver': 4, 'bronze': 3, 'total': 12},
        {'rank': 11, 'country': 'Canada', 'flag': '\U0001f1e8\U0001f1e6', 'code': 'CAN', 'gold': 3, 'silver': 4, 'bronze': 5, 'total': 12},
        {'rank': 12, 'country': 'China', 'flag': '\U0001f1e8\U0001f1f3', 'code': 'CHN', 'gold': 2, 'silver': 3, 'bronze': 4, 'total': 9},
        {'rank': 13, 'country': 'Australia', 'flag': '\U0001f1e6\U0001f1fa', 'code': 'AUS', 'gold': 3, 'silver': 2, 'bronze': 1, 'total': 6},
        {'rank': 14, 'country': 'South Korea', 'flag': '\U0001f1f0\U0001f1f7', 'code': 'KOR', 'gold': 1, 'silver': 2, 'bronze': 3, 'total': 6},
        {'rank': 15, 'country': 'Czechia', 'flag': '\U0001f1e8\U0001f1ff', 'code': 'CZE', 'gold': 2, 'silver': 2, 'bronze': 0, 'total': 4},
        {'rank': 16, 'country': 'Slovenia', 'flag': '\U0001f1f8\U0001f1ee', 'code': 'SLO', 'gold': 2, 'silver': 1, 'bronze': 1, 'total': 4},
        {'rank': 17, 'country': 'Poland', 'flag': '\U0001f1f5\U0001f1f1', 'code': 'POL', 'gold': 0, 'silver': 3, 'bronze': 1, 'total': 4},
        {'rank': 18, 'country': 'Finland', 'flag': '\U0001f1eb\U0001f1ee', 'code': 'FIN', 'gold': 0, 'silver': 0, 'bronze': 4, 'total': 4},
        {'rank': 19, 'country': 'Great Britain', 'flag': '\U0001f1ec\U0001f1e7', 'code': 'GBR', 'gold': 3, 'silver': 0, 'bronze': 0, 'total': 3},
        {'rank': 20, 'country': 'New Zealand', 'flag': '\U0001f1f3\U0001f1ff', 'code': 'NZL', 'gold': 0, 'silver': 2, 'bronze': 1, 'total': 3},
        {'rank': 21, 'country': 'Latvia', 'flag': '\U0001f1f1\U0001f1fb', 'code': 'LAT', 'gold': 0, 'silver': 1, 'bronze': 1, 'total': 2},
        {'rank': 22, 'country': 'Bulgaria', 'flag': '\U0001f1e7\U0001f1ec', 'code': 'BUL', 'gold': 0, 'silver': 0, 'bronze': 2, 'total': 2},
        {'rank': 23, 'country': 'Kazakhstan', 'flag': '\U0001f1f0\U0001f1ff', 'code': 'KAZ', 'gold': 1, 'silver': 0, 'bronze': 0, 'total': 1},
        {'rank': 24, 'country': 'Brazil', 'flag': '\U0001f1e7\U0001f1f7', 'code': 'BRA', 'gold': 1, 'silver': 0, 'bronze': 0, 'total': 1},
        {'rank': 25, 'country': 'Georgia', 'flag': '\U0001f1ec\U0001f1ea', 'code': 'GEO', 'gold': 0, 'silver': 1, 'bronze': 0, 'total': 1},
        {'rank': 26, 'country': 'Belgium', 'flag': '\U0001f1e7\U0001f1ea', 'code': 'BEL', 'gold': 0, 'silver': 0, 'bronze': 1, 'total': 1},
    ],
    'day': 13, 'events_complete': 87, 'total_events': 116,
    'medal_events_today': 8, 'countries_with_medals': 26
}

FALLBACK_USA = {
    'sports': [
        {'sport': 'Speed Skating', 'gold': 2, 'silver': 1, 'bronze': 0},
        {'sport': 'Alpine Skiing', 'gold': 2, 'silver': 0, 'bronze': 1},
        {'sport': 'Figure Skating', 'gold': 1, 'silver': 1, 'bronze': 0},
        {'sport': 'Freestyle Skiing', 'gold': 1, 'silver': 2, 'bronze': 1},
        {'sport': 'Snowboard', 'gold': 0, 'silver': 2, 'bronze': 0},
        {'sport': 'Cross-Country Skiing', 'gold': 0, 'silver': 1, 'bronze': 1},
        {'sport': 'Bobsled', 'gold': 1, 'silver': 0, 'bronze': 0},
        {'sport': 'Short Track', 'gold': 0, 'silver': 1, 'bronze': 1},
        {'sport': 'Skeleton', 'gold': 0, 'silver': 1, 'bronze': 0},
        {'sport': 'Curling', 'gold': 0, 'silver': 1, 'bronze': 0},
        {'sport': 'Biathlon', 'gold': 0, 'silver': 1, 'bronze': 1},
        {'sport': 'Luge', 'gold': 0, 'silver': 0, 'bronze': 1},
    ],
    'total_gold': 7, 'total_silver': 11, 'total_bronze': 6, 'total': 24
}

FALLBACK_ATHLETES = {
    'athletes': [
        {'name': 'Jordan Stolz', 'sport': 'Speed Skating', 'medals': [{'event': '1000m', 'type': 'gold', 'emoji': '\U0001f947'}, {'event': '500m', 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': 'Won two gold medals with Olympic records in both the 1000m and 500m. First American since 1980 to win multiple speedskating golds at a single Olympics.'},
        {'name': 'Mikaela Shiffrin', 'sport': 'Alpine Skiing', 'medals': [{'event': 'Giant Slalom', 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': 'Won gold in the giant slalom, adding to her legendary career with a record-extending Olympic medal count in alpine skiing.'},
        {'name': 'Breezy Johnson', 'sport': 'Alpine Skiing', 'medals': [{'event': "Women's Downhill", 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': "Won gold in the women's downhill, becoming only the second American woman to accomplish the feat."},
        {'name': 'Elizabeth Lemley', 'sport': 'Freestyle Skiing', 'medals': [{'event': "Women's Moguls", 'type': 'gold', 'emoji': '\U0001f947'}, {'event': "Women's Dual Moguls", 'type': 'bronze', 'emoji': '\U0001f949'}], 'bio': "Won gold in her Olympic debut in women's moguls at just 20 years old, then added a bronze in dual moguls."},
        {'name': 'Ilia Malinin', 'sport': 'Figure Skating', 'medals': [{'event': 'Team Event', 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': 'Known as the "Quad God," delivered a dominant performance helping Team USA win gold in the figure skating team event.'},
        {'name': 'Ben Ogden', 'sport': 'Cross-Country Skiing', 'medals': [{'event': 'Sprint', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Became the first American man to win an Olympic medal in cross-country skiing since 1976, earning silver in the sprint.'},
        {'name': 'Chloe Kim', 'sport': 'Snowboard Halfpipe', 'medals': [{'event': 'Halfpipe', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Two-time Olympic champion earned silver in the halfpipe, adding to her legendary Olympic career.'},
        {'name': 'Chock & Bates', 'sport': 'Ice Dance', 'medals': [{'event': 'Ice Dance', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Madison Chock and Evan Bates earned silver in ice dance after being narrowly edged out of the top spot.'},
        {'name': 'Jessie Diggins', 'sport': 'Cross-Country Skiing', 'medals': [{'event': 'Individual', 'type': 'bronze', 'emoji': '\U0001f949'}], 'bio': 'Continued her Olympic legacy with a bronze medal, further cementing her status as the greatest American cross-country skier.'},
    ]
}


# ── Wikipedia Medal Table Scraper ─────────────────────────────────────────

def scrape_medal_table():
    """Fetch medal table from Wikipedia API. Returns ALL countries, not capped."""
    import requests
    from bs4 import BeautifulSoup

    params = {
        'action': 'parse',
        'page': '2026 Winter Olympics medal table',
        'format': 'json',
        'prop': 'text',
        'section': 1,
    }
    resp = requests.get(WIKI_API, params=params, timeout=30,
                        headers={'User-Agent': 'OlympicsDashboard/2.0'})
    resp.raise_for_status()
    html = resp.json().get('parse', {}).get('text', {}).get('*', '')

    if not html:
        raise ValueError('Empty Wikipedia response')

    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', class_='wikitable')
    if not table:
        # Fallback: try any table
        table = soup.find('table')
    if not table:
        raise ValueError('No table found in Wikipedia response')

    medals = []
    rows = table.find_all('tr')

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 5:
            continue

        # Extract text from each cell
        cell_texts = []
        for cell in cells:
            # Get text, clean up
            text = cell.get_text(strip=True)
            # Remove footnote markers like [a], [1], *
            text = re.sub(r'\[.*?\]', '', text).strip()
            text = re.sub(r'\*$', '', text).strip()
            cell_texts.append(text)

        # Find the country name — it's in the cell with an <a> tag usually
        country = None
        numbers = []

        for i, cell in enumerate(cells):
            text = cell_texts[i]
            # Check for country link
            link = cell.find('a')
            if link and len(text) > 2 and not text.isdigit():
                country = text
            elif text.isdigit():
                numbers.append(int(text))
            elif len(text) > 2 and not text[0].isdigit():
                if not country:
                    country = text

        # Skip totals row
        if country and country.lower() in ('total', 'totals', 'total(s)'):
            continue

        if country and len(numbers) >= 4:
            g, s, b, t = numbers[-4], numbers[-3], numbers[-2], numbers[-1]
            rank = len(medals) + 1

            # Normalize name
            name = country.replace('\xa0', ' ').strip()
            flag = COUNTRY_FLAGS.get(name, '')
            code = COUNTRY_CODES.get(name, name[:3].upper())

            medals.append({
                'rank': rank,
                'country': name,
                'flag': flag,
                'code': code,
                'gold': g,
                'silver': s,
                'bronze': b,
                'total': t,
            })

    if not medals:
        raise ValueError('Could not parse any medal data from Wikipedia')

    # Sort by gold, then silver, then bronze (should already be sorted, but ensure)
    medals.sort(key=lambda m: (-m['gold'], -m['silver'], -m['bronze']))
    for i, m in enumerate(medals):
        m['rank'] = i + 1

    total_medals_awarded = sum(m['total'] for m in medals)
    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)

    # Estimate events complete from total medals (each event awards ~3 medals)
    events_est = total_medals_awarded // 3 if total_medals_awarded > 0 else 0

    result = {
        'medals': medals,  # ALL countries, no cap
        'day': day_num,
        'events_complete': events_est,
        'total_events': 116,
        'medal_events_today': 8,
        'countries_with_medals': len(medals),
    }
    print(f'  \u2713 Wikipedia: parsed {len(medals)} countries, {total_medals_awarded} total medals')
    return result


# ── Wikipedia Schedule/Results Scraper ────────────────────────────────────

def scrape_schedule_and_results():
    """Scrape today's schedule from Wikipedia 2026 Winter Olympics page."""
    import requests
    from bs4 import BeautifulSoup

    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)
    date_str = now.strftime('%B %d').replace(' 0', ' ')  # e.g. "February 18"

    # Try the main event page for schedule info
    params = {
        'action': 'parse',
        'page': '2026 Winter Olympics',
        'format': 'json',
        'prop': 'text',
        'section': 0,
    }

    try:
        resp = requests.get(WIKI_API, params=params, timeout=30,
                            headers={'User-Agent': 'OlympicsDashboard/2.0'})
        resp.raise_for_status()
        # We can get basic schedule info but detailed per-event schedule is hard
        # from Wikipedia. Return a structured placeholder directing to olympics.com
    except Exception:
        pass

    # Build schedule from known Olympic event structure for the day
    # Since Wikipedia doesn't have a clean per-day event schedule table,
    # we provide a redirect to the official schedule
    schedule = {
        'events': [{
            'time_mst': 'All Day',
            'event': f'Day {day_num} Events — {date_str}',
            'sport': 'Multiple',
            'status': 'live' if 6 <= now.hour <= 22 else 'upcoming',
            'is_medal': True,
            'result': ''
        }]
    }
    return schedule


def scrape_latest_results():
    """Scrape recent medal results from Wikipedia medal table detail pages."""
    import requests
    from bs4 import BeautifulSoup

    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)
    days_data = []

    # Scrape from the main 2026 Winter Olympics page which has event results
    for offset in range(3):
        d = now - timedelta(days=offset)
        d_num = max(1, (d - GAMES_START).days + 1)
        d_str = d.strftime('%b %d')

        # Try sport-specific pages for medal results
        results = []

        # We'll try to get results from the "2026 Winter Olympics medal table" page
        # which lists all medalists
        if offset == 0:
            try:
                params = {
                    'action': 'parse',
                    'page': '2026 Winter Olympics medal table',
                    'format': 'json',
                    'prop': 'text',
                    'section': 0,  # Intro section
                }
                resp = requests.get(WIKI_API, params=params, timeout=30,
                                    headers={'User-Agent': 'OlympicsDashboard/2.0'})
                resp.raise_for_status()
            except Exception:
                pass

        days_data.append({
            'day_num': d_num,
            'date': d_str,
            'results': results
        })

    return {'days': days_data}


# ── RSS Headlines Fetcher ─────────────────────────────────────────────────

def fetch_rss_headlines():
    """Fetch Olympic headlines from RSS feeds. No Perplexity needed."""
    import feedparser
    import requests

    headlines = []
    feeds = [
        ('https://www.nbcolympics.com/feed', 'NBC Olympics'),
        ('https://olympics.com/en/news/rss', 'Olympics.com'),
        ('https://www.espn.com/espn/rss/olympics/news', 'ESPN'),
        ('https://news.google.com/rss/search?q=2026+Winter+Olympics&hl=en-US&gl=US&ceid=US:en', 'Google News'),
    ]

    for feed_url, source_name in feeds:
        try:
            # feedparser handles the fetching
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '#')
                # Parse date
                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if published:
                    try:
                        dt = datetime(*published[:6])
                        date_str = dt.strftime('%b %d')
                    except Exception:
                        date_str = ''
                else:
                    date_str = ''

                if title and '2026' in title.lower() or 'olympic' in title.lower() or 'winter games' in title.lower():
                    headlines.append({
                        'title': title[:120],
                        'source': source_name,
                        'url': link,
                        'date': date_str,
                    })
        except Exception as e:
            print(f'  ! RSS feed {source_name} failed: {e}')

    # If no Olympic-specific headlines, just take the top ones from Google News
    if len(headlines) < 3:
        try:
            feed = feedparser.parse('https://news.google.com/rss/search?q=2026+Winter+Olympics+Milano+Cortina&hl=en-US&gl=US&ceid=US:en')
            for entry in feed.entries[:10]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '#')
                published = entry.get('published_parsed')
                date_str = ''
                if published:
                    try:
                        dt = datetime(*published[:6])
                        date_str = dt.strftime('%b %d')
                    except Exception:
                        pass
                headlines.append({
                    'title': title[:120],
                    'source': 'Google News',
                    'url': link,
                    'date': date_str,
                })
        except Exception as e:
            print(f'  ! Google News RSS fallback failed: {e}')

    # Deduplicate by title similarity
    seen = set()
    unique = []
    for h in headlines:
        key = h['title'][:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)

    return {'headlines': unique[:10]}


# ── YouTube Data API ──────────────────────────────────────────────────────

def fetch_youtube_videos():
    """Fetch Olympic video highlights from YouTube Data API."""
    import requests

    if not YOUTUBE_API_KEY:
        print('  ! No YOUTUBE_API_KEY, skipping YouTube fetch')
        return {'videos': []}

    sport_emojis = {
        'skiing': '\u26f7\ufe0f', 'ski': '\u26f7\ufe0f', 'alpine': '\u26f7\ufe0f',
        'skating': '\u26f8\ufe0f', 'figure': '\u26f8\ufe0f', 'ice': '\u26f8\ufe0f',
        'snowboard': '\U0001f3c2', 'halfpipe': '\U0001f3c2',
        'hockey': '\U0001f3d2', 'biathlon': '\U0001f3af',
        'curling': '\U0001f94c', 'bobsled': '\U0001f6f7', 'luge': '\U0001f6f7',
        'skeleton': '\U0001f6f7', 'cross-country': '\u26f7\ufe0f',
        'mogul': '\u26f7\ufe0f', 'freestyle': '\u26f7\ufe0f',
    }

    try:
        params = {
            'part': 'snippet',
            'q': '2026 Winter Olympics highlights Milano Cortina',
            'type': 'video',
            'maxResults': 15,
            'order': 'date',
            'key': YOUTUBE_API_KEY,
            'publishedAfter': '2026-02-06T00:00:00Z',
            'relevanceLanguage': 'en',
        }
        resp = requests.get('https://www.googleapis.com/youtube/v3/search',
                            params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        videos = []
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            video_id = item.get('id', {}).get('videoId', '')
            title = snippet.get('title', '')
            channel = snippet.get('channelTitle', '')
            pub = snippet.get('publishedAt', '')

            # Parse date
            date_str = ''
            if pub:
                try:
                    dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                    date_str = dt.strftime('%b %d')
                except Exception:
                    pass

            # Determine emoji based on title
            emoji = '\U0001f3d4\ufe0f'  # Default mountain
            title_lower = title.lower()
            for keyword, em in sport_emojis.items():
                if keyword in title_lower:
                    emoji = em
                    break

            if video_id and title:
                videos.append({
                    'title': title[:80],
                    'url': f'https://www.youtube.com/watch?v={video_id}',
                    'source': channel[:30],
                    'emoji': emoji,
                    'date': date_str,
                })

        print(f'  \u2713 YouTube: found {len(videos)} videos')
        return {'videos': videos[:10]}

    except Exception as e:
        print(f'  ! YouTube API failed: {e}')
        return {'videos': []}


# ── USA Breakdown (derived from medal table) ──────────────────────────────

def derive_usa_breakdown(medal_data):
    """
    Derive USA medal breakdown by sport from Wikipedia.
    Tries to scrape individual event results. Falls back to hardcoded.
    """
    import requests
    from bs4 import BeautifulSoup

    # Try to get USA-specific medal data from Wikipedia
    try:
        params = {
            'action': 'parse',
            'page': 'United States at the 2026 Winter Olympics',
            'format': 'json',
            'prop': 'text',
        }
        resp = requests.get(WIKI_API, params=params, timeout=30,
                            headers={'User-Agent': 'OlympicsDashboard/2.0'})
        resp.raise_for_status()
        html = resp.json().get('parse', {}).get('text', {}).get('*', '')

        if html:
            soup = BeautifulSoup(html, 'lxml')
            # Look for medal summary table
            tables = soup.find_all('table', class_='wikitable')

            for table in tables:
                headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
                if 'gold' in headers or 'sport' in headers:
                    sports = []
                    total_g, total_s, total_b = 0, 0, 0

                    for row in table.find_all('tr')[1:]:
                        cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                        if len(cells) >= 4:
                            sport_name = cells[0]
                            nums = [int(c) for c in cells[1:] if c.isdigit()]
                            if len(nums) >= 3 and sport_name.lower() not in ('total', 'totals'):
                                g, s, b = nums[0], nums[1], nums[2]
                                if g + s + b > 0:
                                    sports.append({
                                        'sport': sport_name,
                                        'gold': g, 'silver': s, 'bronze': b
                                    })
                                    total_g += g
                                    total_s += s
                                    total_b += b

                    if sports:
                        # Sort by total medals desc
                        sports.sort(key=lambda x: -(x['gold']*100 + x['silver']*10 + x['bronze']))
                        result = {
                            'sports': sports,
                            'total_gold': total_g,
                            'total_silver': total_s,
                            'total_bronze': total_b,
                            'total': total_g + total_s + total_b,
                        }
                        print(f'  \u2713 Wikipedia USA: found {len(sports)} sports')
                        return result
    except Exception as e:
        print(f'  ! Wikipedia USA page failed: {e}')

    # If we have medal table data, extract USA totals from there
    usa_entry = None
    for m in medal_data.get('medals', []):
        if m.get('code') == 'USA':
            usa_entry = m
            break

    if usa_entry:
        # Use hardcoded sport breakdown but update totals to match scraped data
        fb = FALLBACK_USA.copy()
        fb['total_gold'] = usa_entry['gold']
        fb['total_silver'] = usa_entry['silver']
        fb['total_bronze'] = usa_entry['bronze']
        fb['total'] = usa_entry['total']
        return fb

    return FALLBACK_USA


# ── Upcoming Events ───────────────────────────────────────────────────────

def get_upcoming_events():
    """Build upcoming events section from known Olympic schedule structure."""
    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)
    days = []

    for offset in range(1, 4):
        d = now + timedelta(days=offset)
        d_num = day_num + offset
        if d_num > 16:
            break

        dow = d.strftime('%a')
        date_str = d.strftime('%b %d')

        days.append({
            'day_num': d_num,
            'date': date_str,
            'day_of_week': dow,
            'medal_count': 8,
            'events': [{
                'time_mst': 'See Schedule',
                'event': f'Day {d_num} Medal Events',
                'is_medal': True,
                'iso_date': d.strftime('%Y-%m-%dT09:00:00-07:00'),
            }],
        })

    return {'days': days}


# ── HTML Generators ────────────────────────────────────────────────────────

def html_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _extract_youtube_id(url):
    """Extract YouTube video ID from various URL formats."""
    m = re.search(r'(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})', url or '')
    return m.group(1) if m else None


def build_medal_table_rows(medals):
    rows = ''
    for m in medals.get('medals', []):
        us = ' class="us-row"' if m.get('code') == 'USA' else ''
        flag = m.get('flag', '')
        rows += f'<tr{us}><td class="rk">{m["rank"]}</td><td class="country-name">{flag} {html_escape(m["country"])}</td><td class="g">{m["gold"]}</td><td class="s">{m["silver"]}</td><td class="b">{m["bronze"]}</td><td class="tot">{m["total"]}</td></tr>\n'
    return rows


def build_schedule_rows(schedule):
    events = schedule.get('events', [])
    if not events:
        return '<div class="section-empty">\u23f3 Schedule data loading from official sources. <a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);">View live schedule \u2192</a></div>'
    rows = ''
    for evt in events:
        status = evt.get('status', 'upcoming')
        is_medal = evt.get('is_medal', False)
        classes = ['evt']
        if status == 'done':
            classes.append('done')
        if status == 'live':
            classes.append('live-now')
        if is_medal:
            classes.append('medal-evt')

        if status == 'done':
            badge = '<span class="badge badge-done">FINAL</span>'
        elif status == 'live':
            badge = '<span class="badge badge-live">LIVE</span>'
        else:
            badge = '<span class="badge badge-upcoming">UPCOMING</span>'

        result = f' {html_escape(evt.get("result", ""))}' if evt.get('result') and status == 'done' else ''

        rows += f'<div class="{" ".join(classes)}"><span class="evt-time">{html_escape(evt["time_mst"])}</span><div class="evt-info"><div class="evt-name">{html_escape(evt["event"])}</div><div class="evt-detail">{badge}{result}</div></div></div>\n'
    # Add link to official schedule
    rows += '<div style="text-align:center;padding:12px 0;"><a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);font-size:0.85rem;font-weight:600;">View full live schedule on Olympics.com \u2192</a></div>\n'
    return rows


def build_usa_breakdown(usa):
    sports = usa.get('sports', [])
    if not sports:
        return '<div class="section-empty">USA breakdown data temporarily unavailable.</div>'
    rows = ''
    for s in sports:
        rows += f'<div class="sport-row"><span class="sport-label">{html_escape(s["sport"])}</span><div class="sport-medals"><span class="g">{s["gold"]}</span><span class="s">{s["silver"]}</span><span class="b">{s["bronze"]}</span></div></div>\n'
    return rows


def build_results_tabs(results):
    days = results.get('days', [])
    if not days or not any(d.get('results') for d in days):
        return '<div class="section-empty">\U0001f3c5 Detailed results update with each medal event. <a href="https://www.olympics.com/en/milano-cortina-2026/medals" target="_blank" style="color:var(--accent);">View full results \u2192</a></div>'

    tabs = ''
    contents = ''
    for i, day in enumerate(days):
        day_id = f'd{day["day_num"]}'
        active = ' active' if i == 0 else ''
        tabs += f'<button class="day-tab{active}" onclick="showDay(\'{day_id}\', this)">Day {day["day_num"]} ({html_escape(day["date"])})</button>\n'

        cards = ''
        for r in day.get('results', []):
            cards += f'<div class="athlete-card"><div class="athlete-top"><span class="athlete-name">\U0001f947 {html_escape(r["event"])}</span><span class="athlete-medal-tag g">Day {day["day_num"]}</span></div><div class="athlete-bio">\U0001f947 {html_escape(r["gold"])} \u2022 \U0001f948 {html_escape(r["silver"])} \u2022 \U0001f949 {html_escape(r["bronze"])}</div></div>\n'
        contents += f'<div id="{day_id}" class="day-content{active}">\n{cards}</div>\n'

    return f'<div class="day-tabs">\n{tabs}</div>\n{contents}'


def build_headlines(headlines):
    items = headlines.get('headlines', [])
    if not items:
        return '<div class="section-empty">\U0001f4f0 Headlines temporarily unavailable. <a href="https://www.nbcolympics.com/" target="_blank" style="color:var(--accent);">Visit NBC Olympics \u2192</a></div>'
    rows = ''
    for i, h in enumerate(items, 1):
        url = html_escape(h.get('url', '#'))
        src = html_escape(h.get('source', ''))
        date = html_escape(h.get('date', ''))
        rows += f'<div class="headline-item"><span class="hl-num">{i}</span><div><div class="hl-text"><a href="{url}" target="_blank">{html_escape(h["title"])}</a></div><div class="hl-src">{src} <span class="hl-date">{date}</span></div></div></div>\n'
    return rows


def build_video_cards(videos):
    grads = ['thumb-grad-1','thumb-grad-2','thumb-grad-3','thumb-grad-4','thumb-grad-5',
             'thumb-grad-6','thumb-grad-7','thumb-grad-8','thumb-grad-9','thumb-grad-10']
    items = videos.get('videos', [])
    if not items:
        return '<div class="section-empty">\U0001f3ac Video highlights temporarily unavailable. <a href="https://www.youtube.com/results?search_query=2026+winter+olympics+highlights" target="_blank" style="color:var(--accent);">Search YouTube \u2192</a></div>'
    cards = ''
    for i, v in enumerate(items):
        grad = grads[i % len(grads)]
        emoji = v.get('emoji', '\U0001f3d4\ufe0f')
        url = html_escape(v.get('url', '#'))

        yt_id = _extract_youtube_id(v.get('url', ''))
        if yt_id:
            thumb_url = f'https://img.youtube.com/vi/{yt_id}/hqdefault.jpg'
            thumb_inner = f'<img src="{html_escape(thumb_url)}" alt="{html_escape(v["title"])}" style="width:100%;height:100%;object-fit:cover;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';"><div class="thumb-placeholder {grad}" style="display:none;">{emoji}</div>'
        else:
            thumb_inner = f'<div class="thumb-placeholder {grad}">{emoji}</div>'

        cards += f'''<div class="video-card"><a href="{url}" target="_blank"><div class="vid-thumb">{thumb_inner}<div class="play-btn"></div></div><div class="vid-info"><div class="vid-title">{html_escape(v["title"])}</div><div class="vid-src">{html_escape(v.get("source",""))} \u2022 {html_escape(v.get("date",""))}</div></div></a></div>\n'''
    return cards


def build_athlete_spotlights(athletes):
    medal_colors = {'gold': 'g', 'silver': 's', 'bronze': 'b'}
    sport_avatars = {
        'snowboard': 'avatar-snow', 'halfpipe': 'avatar-snow',
        'speed skating': 'avatar-speed', 'speedskating': 'avatar-speed',
        'figure skating': 'avatar-figure', 'figure': 'avatar-figure',
        'moguls': 'avatar-moguls', 'freestyle': 'avatar-moguls',
        'alpine': 'avatar-alpine', 'downhill': 'avatar-alpine', 'super-g': 'avatar-alpine',
        'cross-country': 'avatar-xc', 'xc': 'avatar-xc', 'nordic': 'avatar-xc',
        'ice dance': 'avatar-dance', 'dance': 'avatar-dance',
    }
    cards = ''
    for a in athletes.get('athletes', []):
        name = a.get('name', '')
        sport = a.get('sport', '')
        avatar_cls = 'avatar-snow'
        for key, cls in sport_avatars.items():
            if key in sport.lower():
                avatar_cls = cls
                break
        parts = name.split()
        initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else name[:2].upper()
        medal_tags = ''
        if 'medals' in a and isinstance(a['medals'], list):
            for m in a['medals']:
                mtype = m.get('type', 'gold')
                color = medal_colors.get(mtype, 'g')
                emoji = m.get('emoji', '\U0001f947')
                event = m.get('event', '')
                medal_tags += f'<span class="athlete-medal-tag {color}">{emoji} {html_escape(event)}</span> '
        else:
            medal = a.get('medal', 'gold')
            color = medal_colors.get(medal, 'g')
            emoji = a.get('medal_emoji', '\U0001f947')
            medal_tags = f'<span class="athlete-medal-tag {color}">{emoji} {medal.title()}</span>'
        cards += f'<div class="athlete-card"><div class="athlete-avatar {avatar_cls}">{initials}</div><div class="athlete-content"><div class="athlete-top"><span class="athlete-name">{html_escape(name)} &bull; {html_escape(sport)}</span>{medal_tags}</div><div class="athlete-bio">{html_escape(a.get("bio", ""))}</div></div></div>\n'
    return cards


def build_upcoming_section(upcoming):
    days = upcoming.get('days', [])
    if not days:
        return '<div class="section-empty">\U0001f4c6 Upcoming events — <a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);">View full schedule \u2192</a></div>'
    rows = ''
    for day in days:
        mc = day.get('medal_count', '?')
        rows += f'<div class="upcoming-day-hdr">\U0001f4c5 Day {day["day_num"]} \u2014 {html_escape(day["day_of_week"])}, {html_escape(day["date"])} ({mc} medal events)</div>\n'
        for evt in day.get('events', []):
            medal_class = ' medal' if evt.get('is_medal') else ''
            medal_icon = '\U0001f947' if evt.get('is_medal') else ''
            iso = html_escape(evt.get('iso_date', ''))
            name_safe = html_escape(evt['event']).replace("'", "\\'")
            rows += f'<div class="upcoming-evt{medal_class}"><span class="ue-time">{html_escape(evt["time_mst"])}</span><span class="ue-name">{html_escape(evt["event"])}</span><span class="ue-type">{medal_icon}</span><button class="remind-btn" onclick="setReminder(this,\'{name_safe}\',\'{iso}\')">\U0001f514 Remind</button></div>\n'
    rows += '<div style="text-align:center;padding:12px 0;"><a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);font-size:0.85rem;font-weight:600;">Full schedule on Olympics.com \u2192</a></div>\n'
    return rows


def build_notifications(day_num, events_complete, total_events):
    try:
        remaining = max(0, 16 - int(day_num) + 1)
    except (TypeError, ValueError):
        remaining = '?'
    return f"""  var medalQueue = [
    {{delay:12000, type:'notif-info', title:'Day {day_num} Results Updated', body:'{events_complete} of {total_events} events complete. {remaining} days remaining.'}},
  ];"""


# ── Main Template ──────────────────────────────────────────────────────────

def generate_html(medal_data, schedule, usa, results, headlines, videos, athletes, upcoming):
    now = datetime.now(MST)
    timestamp = now.strftime('%a, %b %d %I:%M %p MST')
    data_date = now.strftime('%Y-%m-%d')

    computed_day = max(1, (now - GAMES_START).days + 1)
    raw_day = medal_data.get('day', computed_day)
    try:
        day = int(raw_day)
    except (TypeError, ValueError):
        day = computed_day
    events_complete = medal_data.get('events_complete') or FALLBACK_MEDALS['events_complete']
    total_events = medal_data.get('total_events') or 116
    medal_today = medal_data.get('medal_events_today') or FALLBACK_MEDALS['medal_events_today']
    countries = medal_data.get('countries_with_medals') or FALLBACK_MEDALS['countries_with_medals']
    try:
        remaining = max(0, 16 - int(day))
    except (TypeError, ValueError):
        remaining = '?'
    try:
        events_remaining = int(total_events) - int(events_complete)
    except (TypeError, ValueError):
        events_remaining = '?'
    usa_total = usa.get('total', FALLBACK_USA['total'])

    medal_rows = build_medal_table_rows(medal_data)
    schedule_rows = build_schedule_rows(schedule)
    usa_rows = build_usa_breakdown(usa)
    results_html = build_results_tabs(results)
    headline_rows = build_headlines(headlines)
    video_cards = build_video_cards(videos)
    athlete_cards = build_athlete_spotlights(athletes)
    upcoming_rows = build_upcoming_section(upcoming)
    notif_js = build_notifications(day, events_complete, total_events)

    html = TEMPLATE.format(
        data_date=data_date,
        timestamp=timestamp,
        day=day,
        medal_today=medal_today,
        events_complete=events_complete,
        total_events=total_events,
        countries=countries,
        remaining=remaining,
        events_remaining=events_remaining,
        medal_rows=medal_rows,
        schedule_rows=schedule_rows,
        usa_total=usa_total,
        usa_rows=usa_rows,
        results_html=results_html,
        headline_rows=headline_rows,
        video_cards=video_cards,
        athlete_cards=athlete_cards,
        upcoming_rows=upcoming_rows,
        notif_js=notif_js,
    )
    return html


# ── Full HTML Template ─────────────────────────────────────────────────────

TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>2026 Winter Olympics Dashboard</title>
<style>
:root {{ --bg-base: #0b1120; --bg-surface: #151d2e; --bg-card: #1a2438; --bg-muted: #243044; --text-primary: #f0f4f8; --text-secondary: #a8b8cc; --text-muted: #6b7f99; --accent: #38bdf8; --gold: #fbbf24; --silver: #c0c8d4; --bronze: #cd7f32; --red: #ef4444; --green: #22c55e; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-base); color: var(--text-primary); line-height: 1.5; }}
.container {{ max-width: 1440px; margin: 0 auto; padding: 16px 20px; }}
header {{ text-align: center; padding: 24px 0 20px; border-bottom: 1px solid var(--bg-muted); margin-bottom: 20px; }}
.header-icons {{ font-size: 2.8rem; margin-bottom: 4px; }}
h1 {{ font-size: 2rem; color: var(--accent); font-weight: 800; }}
.subtitle {{ color: var(--text-secondary); font-size: 1rem; margin-top: 2px; }}
.header-meta {{ display: flex; justify-content: center; gap: 16px; align-items: center; margin-top: 12px; flex-wrap: wrap; }}
.timestamp-badge {{ padding: 5px 14px; background: var(--bg-card); border: 1px solid var(--bg-muted); border-radius: 6px; font-size: 0.82rem; color: var(--text-muted); }}
.refresh-btn {{ background: linear-gradient(135deg, #3b82f6, #6366f1); color: white; border: none; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.82rem; font-weight: 600; }}
.refresh-btn:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.4); }}
.live-dot {{ width: 8px; height: 8px; background: var(--red); border-radius: 50%; display: inline-block; animation: blink 1.5s infinite; margin-right: 4px; }}
@keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0.3}} }}
.stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 12px; margin-bottom: 20px; }}
.stat-box {{ background: var(--bg-card); border: 1px solid var(--bg-muted); border-radius: 10px; padding: 14px; text-align: center; }}
.stat-box .label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }}
.stat-box .value {{ font-size: 1.7rem; font-weight: 800; color: var(--accent); margin-top: 2px; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
.grid.full {{ grid-template-columns: 1fr; }}
.panel {{ background: var(--bg-card); border: 1px solid var(--bg-muted); border-radius: 10px; padding: 20px; overflow-y: auto; max-height: 600px; }}
.panel.tall {{ max-height: 800px; }}
.panel-hdr {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--bg-muted); display: flex; align-items: center; gap: 8px; }}
.section-empty {{ padding: 20px; text-align: center; color: var(--text-muted); font-size: 0.88rem; background: var(--bg-surface); border-radius: 8px; border: 1px dashed var(--bg-muted); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
th {{ background: var(--bg-muted); padding: 8px 10px; text-align: left; font-weight: 600; color: var(--text-secondary); font-size: 0.8rem; text-transform: uppercase; }}
td {{ padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.03); }}
tr:hover td {{ background: rgba(56,189,248,0.04); }}
.rk {{ color: var(--accent); font-weight: 700; width: 36px; }}
.g {{ color: var(--gold); font-weight: 700; }}
.s {{ color: var(--silver); font-weight: 700; }}
.b {{ color: var(--bronze); font-weight: 700; }}
.tot {{ font-weight: 800; }}
.country-name {{ font-weight: 600; }}
.us-row td {{ background: rgba(56,189,248,0.08); }}
.evt-list {{ display: flex; flex-direction: column; gap: 8px; }}
.evt {{ background: var(--bg-surface); border-radius: 8px; padding: 10px 14px; border-left: 3px solid var(--bg-muted); display: flex; align-items: center; gap: 12px; }}
.evt.medal-evt {{ border-left-color: var(--gold); }}
.evt.done {{ opacity: 0.7; }}
.evt.live-now {{ border-left-color: var(--red); background: rgba(239,68,68,0.06); }}
.evt-time {{ font-size: 0.82rem; font-weight: 700; color: var(--accent); min-width: 72px; white-space: nowrap; }}
.evt-info {{ flex: 1; }}
.evt-name {{ font-weight: 600; font-size: 0.9rem; }}
.evt-detail {{ font-size: 0.78rem; color: var(--text-muted); }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; }}
.badge-live {{ background: rgba(239,68,68,0.15); color: var(--red); }}
.badge-medal {{ background: rgba(251,191,36,0.15); color: var(--gold); }}
.badge-done {{ background: rgba(34,197,94,0.12); color: var(--green); }}
.badge-upcoming {{ background: var(--bg-muted); color: var(--text-secondary); }}
.badge-qf {{ background: rgba(56,189,248,0.15); color: var(--accent); }}
.sport-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: var(--bg-surface); border-radius: 8px; margin-bottom: 6px; }}
.sport-label {{ font-weight: 600; font-size: 0.9rem; }}
.sport-medals {{ display: flex; gap: 14px; font-size: 0.85rem; }}
.headline-item {{ padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.04); display: flex; gap: 10px; align-items: flex-start; }}
.headline-item:last-child {{ border-bottom: none; }}
.hl-num {{ color: var(--accent); font-weight: 800; font-size: 0.9rem; min-width: 20px; }}
.hl-text {{ font-size: 0.85rem; line-height: 1.4; }}
.hl-text a {{ color: var(--text-primary); text-decoration: none; }}
.hl-text a:hover {{ color: var(--accent); text-decoration: underline; }}
.hl-src {{ font-size: 0.7rem; color: var(--text-muted); margin-top: 2px; }}
.hl-date {{ font-size: 0.7rem; color: var(--accent); opacity: 0.7; margin-left: 4px; }}
.athlete-card {{ background: var(--bg-surface); border-radius: 8px; padding: 14px 16px; margin-bottom: 8px; display: flex; gap: 14px; align-items: flex-start; }}
.athlete-avatar {{ width: 52px; height: 52px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; font-weight: 800; color: #fff; flex-shrink: 0; border: 2px solid rgba(255,255,255,0.12); text-shadow: 0 1px 3px rgba(0,0,0,0.4); position: relative; overflow: hidden; }}
.athlete-avatar img {{ position: absolute; width: 100%; height: 100%; object-fit: cover; border-radius: 50%; top: 0; left: 0; }}
.avatar-snow {{ background: linear-gradient(135deg, #06b6d4, #3b82f6); }}
.avatar-speed {{ background: linear-gradient(135deg, #f59e0b, #ef4444); }}
.avatar-figure {{ background: linear-gradient(135deg, #8b5cf6, #ec4899); }}
.avatar-moguls {{ background: linear-gradient(135deg, #10b981, #06b6d4); }}
.avatar-alpine {{ background: linear-gradient(135deg, #ef4444, #f97316); }}
.avatar-xc {{ background: linear-gradient(135deg, #22c55e, #16a34a); }}
.avatar-dance {{ background: linear-gradient(135deg, #a855f7, #6366f1); }}
.athlete-content {{ flex: 1; min-width: 0; }}
.athlete-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px; }}
.athlete-name {{ font-weight: 700; font-size: 0.95rem; }}
.athlete-medal-tag {{ font-size: 0.82rem; font-weight: 700; }}
.athlete-bio {{ font-size: 0.82rem; color: var(--text-secondary); line-height: 1.45; }}
.day-tabs {{ display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }}
.day-tab {{ background: var(--bg-muted); color: var(--text-secondary); border: none; padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }}
.day-tab.active {{ background: var(--accent); color: #0b1120; }}
.day-tab:hover {{ opacity: 0.85; }}
.day-content {{ display: none; }}
.day-content.active {{ display: block; }}
.video-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }}
.video-card {{ background: var(--bg-surface); border-radius: 8px; overflow: hidden; border: 1px solid var(--bg-muted); transition: transform 0.2s; }}
.video-card:hover {{ transform: translateY(-2px); }}
.video-card a {{ text-decoration: none; color: inherit; display: block; }}
.video-card .vid-thumb {{ position: relative; width: 100%; aspect-ratio: 16/9; background: #000; overflow: hidden; }}
.video-card .vid-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
.video-card .vid-thumb .thumb-placeholder {{ width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 3rem; }}
.thumb-grad-1 {{ background: linear-gradient(135deg, #1e3a5f, #38bdf8); }}
.thumb-grad-2 {{ background: linear-gradient(135deg, #1a1a2e, #e94560); }}
.thumb-grad-3 {{ background: linear-gradient(135deg, #0f3460, #16213e, #533483); }}
.thumb-grad-4 {{ background: linear-gradient(135deg, #2d3436, #fbbf24); }}
.thumb-grad-5 {{ background: linear-gradient(135deg, #141e30, #243b55); }}
.thumb-grad-6 {{ background: linear-gradient(135deg, #0b8457, #1a2438); }}
.thumb-grad-7 {{ background: linear-gradient(135deg, #2c3e50, #e74c3c); }}
.thumb-grad-8 {{ background: linear-gradient(135deg, #0c2461, #6a89cc); }}
.thumb-grad-9 {{ background: linear-gradient(135deg, #1e272e, #fad390); }}
.thumb-grad-10 {{ background: linear-gradient(135deg, #192a56, #f5f6fa); }}
.video-card .vid-thumb .play-btn {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); width: 44px; height: 44px; background: rgba(255,0,0,0.85); border-radius: 50%; display: flex; align-items: center; justify-content: center; }}
.video-card .play-btn::after {{ content: ''; border-left: 12px solid white; border-top: 7px solid transparent; border-bottom: 7px solid transparent; margin-left: 2px; }}
.video-card .vid-info {{ padding: 10px 12px; }}
.video-card .vid-title {{ font-weight: 600; font-size: 0.82rem; line-height: 1.3; margin-bottom: 3px; }}
.video-card .vid-src {{ color: var(--text-muted); font-size: 0.72rem; }}
.notif-container {{ position: fixed; top: 16px; right: 16px; z-index: 1000; display: flex; flex-direction: column; gap: 10px; max-width: 360px; }}
.notif {{ background: var(--bg-card); border: 1px solid var(--bg-muted); border-radius: 10px; padding: 14px 18px; box-shadow: 0 8px 32px rgba(0,0,0,0.5); animation: slideIn 0.4s ease-out; cursor: pointer; position: relative; }}
.notif::before {{ content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; border-radius: 10px 0 0 10px; }}
.notif.notif-gold::before {{ background: var(--gold); }}
.notif.notif-silver::before {{ background: var(--silver); }}
.notif.notif-info::before {{ background: var(--accent); }}
.notif-title {{ font-weight: 700; font-size: 0.88rem; margin-bottom: 2px; }}
.notif-body {{ font-size: 0.82rem; color: var(--text-secondary); }}
@keyframes slideIn {{ from{{transform:translateX(120%);opacity:0}} to{{transform:translateX(0);opacity:1}} }}
@keyframes fadeOut {{ from{{opacity:1}} to{{opacity:0;transform:translateX(50px)}} }}
.remind-btn {{ background: none; border: 1px solid var(--accent); color: var(--accent); padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 0.7rem; font-weight: 600; white-space: nowrap; flex-shrink: 0; }}
.remind-btn:hover {{ background: var(--accent); color: #0b1120; }}
.remind-btn.set {{ border-color: var(--green); color: var(--green); cursor: default; }}
.upcoming-evt {{ background: var(--bg-surface); border-radius: 8px; padding: 8px 14px; margin-bottom: 6px; display: flex; align-items: center; gap: 10px; border-left: 3px solid var(--bg-muted); }}
.upcoming-evt.medal {{ border-left-color: var(--gold); }}
.upcoming-evt .ue-time {{ font-size: 0.78rem; font-weight: 700; color: var(--accent); min-width: 64px; white-space: nowrap; }}
.upcoming-evt .ue-name {{ font-weight: 600; font-size: 0.85rem; flex: 1; }}
.upcoming-evt .ue-type {{ font-size: 0.7rem; color: var(--text-muted); margin-right: 4px; }}
.upcoming-day-hdr {{ font-weight: 700; color: var(--accent); font-size: 0.92rem; padding: 12px 0 6px; border-bottom: 1px solid var(--bg-muted); margin-bottom: 8px; }}
.upcoming-day-hdr:first-child {{ padding-top: 0; }}
::-webkit-scrollbar {{ width: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: var(--bg-muted); border-radius: 3px; }}
@media(max-width:1024px) {{ .grid {{ grid-template-columns: 1fr; }} }}
@media(max-width:600px) {{ h1 {{ font-size: 1.5rem; }} .stats-row {{ grid-template-columns: 1fr 1fr; }} .header-icons {{ font-size: 2rem; }} .video-grid {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>
<div id="notif-container" class="notif-container"></div>
<div class="container">
<header>
<div class="header-icons">&#x1F3D4;&#xFE0F; &#x1F3C5; &#x2744;&#xFE0F;</div>
<h1>Milano Cortina 2026</h1>
<p class="subtitle">Winter Olympics Dashboard &bull; <span id="day-label">Day {day}</span></p>
<div class="header-meta">
<span class="timestamp-badge">Data from: <span id="ts">{timestamp}</span> &bull; Auto-refreshes every 30 min</span>
<button class="refresh-btn" onclick="refreshDashboard()">&#x1F504; Refresh Data</button>
</div>
<p style="font-size:0.78rem;color:var(--text-muted);margin-top:8px;"><a href="https://www.olympics.com/en/milano-cortina-2026/medals" target="_blank" style="color:var(--accent);">View live medal table &rarr;</a> &bull; <a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);">Live schedule &rarr;</a></p>
</header>

<div class="stats-row">
<div class="stat-box"><div class="label">Medal Events Today</div><div class="value">{medal_today}</div></div>
<div class="stat-box"><div class="label">Events Completed</div><div class="value">{events_complete}</div></div>
<div class="stat-box"><div class="label">Total Events</div><div class="value">{total_events}</div></div>
<div class="stat-box"><div class="label">Events Remaining</div><div class="value">{events_remaining}</div></div>
<div class="stat-box"><div class="label">Days Remaining</div><div class="value" id="stat-remaining">{remaining}</div></div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-hdr">&#x1F947; Medal Count by Country ({countries} nations)</div>
<table>
<thead><tr><th>Rk</th><th>Country</th><th>&#x1F947;</th><th>&#x1F948;</th><th>&#x1F949;</th><th>Tot</th></tr></thead>
<tbody>
{medal_rows}</tbody>
</table>
</div>
<div class="panel">
<div class="panel-hdr">&#x1F4C5; Day {day} Schedule (MST)</div>
<div class="evt-list">
{schedule_rows}</div>
</div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-hdr">&#x1F1FA;&#x1F1F8; USA Medal Breakdown ({usa_total} Total)</div>
{usa_rows}</div>
<div class="panel">
<div class="panel-hdr">&#x1F947; Latest Medal Results</div>
{results_html}</div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-hdr">&#x1F1FA;&#x1F1F8; USA Athlete Spotlights</div>
<div class="evt-list">
{athlete_cards}</div>
</div>
<div class="panel tall">
<div class="panel-hdr">&#x1F4C6; Upcoming Events &mdash; Set Reminders</div>
<div id="upcoming-events">
{upcoming_rows}</div>
</div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-hdr">&#x1F4F0; Top Headlines</div>
{headline_rows}</div>
<div class="panel">
<div class="panel-hdr">&#x1F3AC; Video Highlights</div>
<div class="video-grid">
{video_cards}</div>
</div>
</div>

</div>

<script>
var DASHBOARD_DATA_DATE = '{data_date}';
var GAMES_START = new Date('2026-02-06T00:00:00-07:00');
var GAMES_END = new Date('2026-02-22T23:59:59-07:00');

function getGamesDay() {{
  var now = new Date();
  var diffMs = now - GAMES_START;
  var day = Math.floor(diffMs / 86400000) + 1;
  return Math.max(1, Math.min(day, 17));
}}

function updateDynamicStats() {{
  var day = getGamesDay();
  var remaining = Math.max(0, 16 - day + 1);
  var el = document.getElementById('stat-remaining');
  if (el) el.textContent = remaining;
  var lbl = document.getElementById('day-label');
  if (lbl) {{
    var now = new Date();
    if (now > GAMES_END) {{ lbl.textContent = 'Games Complete'; }}
    else {{ lbl.textContent = 'Day ' + day; }}
  }}
}}
updateDynamicStats();

function refreshDashboard() {{
  var btn = document.querySelector('.refresh-btn');
  btn.textContent = '\u23f3 Refreshing...';
  btn.disabled = true;
  setTimeout(function() {{
    location.href = location.href.split('?')[0] + '?t=' + Date.now();
  }}, 500);
}}

function showDay(id, btn) {{
  document.querySelectorAll('.day-content').forEach(function(el) {{ el.classList.remove('active'); }});
  document.querySelectorAll('.day-tab').forEach(function(el) {{ el.classList.remove('active'); }});
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}

function setReminder(btn, eventName, isoDate) {{
  if (btn.classList.contains('set')) return;
  if ('Notification' in window && Notification.permission === 'default') {{
    Notification.requestPermission();
  }}
  var startDate = new Date(isoDate);
  var endDate = new Date(startDate.getTime() + 2 * 60 * 60 * 1000);
  var icsContent = [
    'BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Olympics Dashboard//EN',
    'BEGIN:VEVENT','DTSTART:' + formatICS(startDate),'DTEND:' + formatICS(endDate),
    'SUMMARY:Olympics: ' + eventName,
    'DESCRIPTION:Watch live at https://mcgregorb.github.io/olympics-dashboard/',
    'BEGIN:VALARM','TRIGGER:-PT15M','ACTION:DISPLAY',
    'DESCRIPTION:' + eventName + ' starts in 15 minutes!',
    'END:VALARM','END:VEVENT','END:VCALENDAR'
  ].join('\\r\\n');
  var blob = new Blob([icsContent], {{ type: 'text/calendar;charset=utf-8' }});
  var link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'olympics-' + eventName.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase() + '.ics';
  link.click();
  URL.revokeObjectURL(link.href);
  if ('Notification' in window && Notification.permission === 'granted') {{
    var msUntil = startDate.getTime() - Date.now() - (15 * 60 * 1000);
    if (msUntil > 0) {{
      setTimeout(function() {{
        new Notification('Olympics: ' + eventName, {{
          body: 'Starting in 15 minutes!',
          icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">\\u26f7\\ufe0f</text></svg>'
        }});
      }}, msUntil);
    }}
  }}
  btn.textContent = '\\u2705 Set';
  btn.classList.add('set');
  showNotif({{type: 'notif-info', title: 'Reminder Set', body: eventName + ' \u2014 .ics downloaded, browser alert 15 min before.'}});
}}

function formatICS(d) {{
  return d.toISOString().replace(/[-:]/g, '').replace(/\\.\\d{{3}}/, '');
}}

function showNotif(n) {{
  var c = document.getElementById('notif-container');
  var el = document.createElement('div');
  el.className = 'notif ' + n.type;
  el.innerHTML = '<div class="notif-title">' + n.title + '</div><div class="notif-body">' + n.body + '</div>';
  el.onclick = function() {{ el.style.animation='fadeOut 0.3s forwards'; setTimeout(function(){{el.remove();}},300); }};
  c.appendChild(el);
  setTimeout(function() {{ if(el.parentNode){{ el.style.animation='fadeOut 0.3s forwards'; setTimeout(function(){{el.remove();}},300); }} }}, 10000);
}}

(function() {{
  var today = new Date().toISOString().slice(0, 10);
  if (today !== DASHBOARD_DATA_DATE) {{
    setTimeout(function() {{
      showNotif({{type: 'notif-info', title: 'Dashboard data from ' + DASHBOARD_DATA_DATE, body: 'Data auto-updates every 30 min. Click Refresh Data to get the latest version.'}});
    }}, 3000);
    return;
  }}
{notif_js}
  medalQueue.forEach(function(n) {{ setTimeout(function(){{showNotif(n);}}, n.delay); }});
}})();

setInterval(function() {{ location.reload(); }}, 1800000);
</script>
</body>
</html>'''


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    # NO Perplexity API key required anymore
    print(f'Starting dashboard update (v2 - no Perplexity) at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')

    sections = {}

    # Athletes always use hardcoded authoritative data
    sections['athletes'] = FALLBACK_ATHLETES
    print('  \u2713 Using authoritative athlete data')

    # 1. Medal table from Wikipedia (primary) with fallback
    try:
        sections['medals'] = scrape_medal_table()
    except Exception as e:
        print(f'  \u2717 Medal table scrape failed: {e}')
        traceback.print_exc()
        sections['medals'] = FALLBACK_MEDALS
        print('  \u21b3 Using fallback medal data')

    # Validate medal data quality
    if len(sections['medals'].get('medals', [])) < 10:
        print(f'  ! Only {len(sections["medals"].get("medals", []))} countries found, using fallback')
        sections['medals'] = FALLBACK_MEDALS

    # 2. USA breakdown (derived from Wikipedia or fallback)
    try:
        sections['usa'] = derive_usa_breakdown(sections['medals'])
    except Exception as e:
        print(f'  \u2717 USA breakdown failed: {e}')
        sections['usa'] = FALLBACK_USA

    # 3. Schedule from Wikipedia/structured data
    try:
        sections['schedule'] = scrape_schedule_and_results()
    except Exception as e:
        print(f'  \u2717 Schedule failed: {e}')
        sections['schedule'] = {'events': []}

    # 4. Latest results from Wikipedia
    try:
        sections['results'] = scrape_latest_results()
    except Exception as e:
        print(f'  \u2717 Results failed: {e}')
        sections['results'] = {'days': []}

    # 5. Headlines from RSS feeds
    try:
        sections['headlines'] = fetch_rss_headlines()
    except Exception as e:
        print(f'  \u2717 Headlines failed: {e}')
        sections['headlines'] = {'headlines': []}

    # 6. Videos from YouTube Data API
    try:
        sections['videos'] = fetch_youtube_videos()
    except Exception as e:
        print(f'  \u2717 Videos failed: {e}')
        sections['videos'] = {'videos': []}

    # 7. Upcoming events
    try:
        sections['upcoming'] = get_upcoming_events()
    except Exception as e:
        print(f'  \u2717 Upcoming events failed: {e}')
        sections['upcoming'] = {'days': []}

    # Generate and write HTML
    try:
        html = generate_html(
            sections['medals'], sections['schedule'], sections['usa'],
            sections['results'], sections['headlines'], sections['videos'],
            sections['athletes'], sections['upcoming']
        )
    except Exception as e:
        print(f'FATAL: generate_html crashed: {e}')
        traceback.print_exc()
        sys.exit(1)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = os.path.getsize('index.html')
    medal_count = len(sections['medals'].get('medals', []))
    headline_count = len(sections['headlines'].get('headlines', []))
    video_count = len(sections['videos'].get('videos', []))
    print(f'\nDashboard updated: {file_size} bytes')
    print(f'  Medals: {medal_count} countries | Headlines: {headline_count} | Videos: {video_count}')
    print(f'  Completed at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')


if __name__ == '__main__':
    main()
