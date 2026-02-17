"""
Olympics Dashboard Auto-Updater
===============================
Called by GitHub Actions every 30 minutes. Uses structured data sources:
  - Wikipedia API for medal table, medal winners, USA breakdown, country details, results
  - Google News RSS for headlines (no API key needed)
  - YouTube Data API v3 for video highlights (YOUTUBE_API_KEY)
  - Hardcoded competition schedule (Days 12-17) as reliable fallback
  - Hardcoded data for athletes and as last-resort fallbacks

NO LLM/Perplexity dependency — all data is from structured, deterministic sources.

Data flow:
  1. Medal table — Wikipedia '2026 Winter Olympics medal table'
  2. Medal winners — Wikipedia 'List of 2026 Winter Olympics medal winners'
     -> Derived: USA breakdown, country details, latest results
  3. Headlines — Google News RSS (feedparser)
  4. Videos — YouTube Data API v3 search
  5. Schedule — Wikipedia sport pages (15 sports) + hardcoded fallback
     -> Results overlaid from medal winners
  6. Upcoming events — Wikipedia sport pages + hardcoded FULL_SCHEDULE
  7. Athletes — Hardcoded (authoritative, rarely changes)
"""

import os
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta

WIKI_API = 'https://en.wikipedia.org/w/api.php'
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
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
}

# Wikipedia pages for each sport — used to scrape event schedules
SPORT_WIKI_PAGES = {
    'Alpine Skiing': 'Alpine_skiing_at_the_2026_Winter_Olympics',
    'Biathlon': 'Biathlon_at_the_2026_Winter_Olympics',
    'Bobsleigh': 'Bobsleigh_at_the_2026_Winter_Olympics',
    'Cross-Country Skiing': 'Cross-country_skiing_at_the_2026_Winter_Olympics',
    'Curling': 'Curling_at_the_2026_Winter_Olympics',
    'Figure Skating': 'Figure_skating_at_the_2026_Winter_Olympics',
    'Freestyle Skiing': 'Freestyle_skiing_at_the_2026_Winter_Olympics',
    'Ice Hockey': 'Ice_hockey_at_the_2026_Winter_Olympics',
    'Luge': 'Luge_at_the_2026_Winter_Olympics',
    'Nordic Combined': 'Nordic_combined_at_the_2026_Winter_Olympics',
    'Short Track Speed Skating': 'Short_track_speed_skating_at_the_2026_Winter_Olympics',
    'Skeleton': 'Skeleton_at_the_2026_Winter_Olympics',
    'Ski Jumping': 'Ski_jumping_at_the_2026_Winter_Olympics',
    'Snowboard': 'Snowboarding_at_the_2026_Winter_Olympics',
    'Speed Skating': 'Speed_skating_at_the_2026_Winter_Olympics',
}

CET = timezone(timedelta(hours=1))


def cet_to_mst_str(hour, minute=0):
    """Convert CET hour:minute to MST display string like '2:00 AM'."""
    mst_hour = (hour - 8) % 24
    period = 'AM' if mst_hour < 12 else 'PM'
    display = mst_hour % 12 or 12
    return f'{display}:{minute:02d} {period}'


def cet_to_mst_iso(hour, minute, date_str):
    """Convert CET time to MST ISO string for reminder buttons.
    date_str is 'YYYY-MM-DD'."""
    dt_cet = datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]),
                      hour, minute, tzinfo=CET)
    dt_mst = dt_cet.astimezone(MST)
    return dt_mst.isoformat()


def _parse_time_for_sort(time_str):
    """Parse '2:00 AM' -> minutes since midnight for sorting."""
    m = re.match(r'(\d+):(\d+)\s*(AM|PM)', time_str, re.I)
    if not m:
        return 0
    h, mn, period = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if period == 'PM' and h != 12:
        h += 12
    if period == 'AM' and h == 12:
        h = 0
    return h * 60 + mn


# ── Hardcoded Authoritative Data (updated Feb 16, Day 11) ─────────────────
# Used as reliable fallbacks when scrapers and API return empty/sparse data.
# Source: olympics.com medal table, verified Feb 16 2026

FALLBACK_MEDALS = {
    'medals': [
        {'rank': 1, 'country': 'Norway', 'flag': '\U0001f1f3\U0001f1f4', 'code': 'NOR', 'gold': 12, 'silver': 7, 'bronze': 7, 'total': 26},
        {'rank': 2, 'country': 'Italy', 'flag': '\U0001f1ee\U0001f1f9', 'code': 'ITA', 'gold': 8, 'silver': 4, 'bronze': 10, 'total': 22},
        {'rank': 3, 'country': 'United States', 'flag': '\U0001f1fa\U0001f1f8', 'code': 'USA', 'gold': 5, 'silver': 8, 'bronze': 4, 'total': 17},
        {'rank': 4, 'country': 'Netherlands', 'flag': '\U0001f1f3\U0001f1f1', 'code': 'NED', 'gold': 5, 'silver': 5, 'bronze': 1, 'total': 11},
        {'rank': 5, 'country': 'Sweden', 'flag': '\U0001f1f8\U0001f1ea', 'code': 'SWE', 'gold': 5, 'silver': 5, 'bronze': 1, 'total': 11},
        {'rank': 6, 'country': 'France', 'flag': '\U0001f1eb\U0001f1f7', 'code': 'FRA', 'gold': 4, 'silver': 7, 'bronze': 4, 'total': 15},
        {'rank': 7, 'country': 'Germany', 'flag': '\U0001f1e9\U0001f1ea', 'code': 'GER', 'gold': 4, 'silver': 6, 'bronze': 5, 'total': 15},
        {'rank': 8, 'country': 'Austria', 'flag': '\U0001f1e6\U0001f1f9', 'code': 'AUT', 'gold': 4, 'silver': 6, 'bronze': 3, 'total': 13},
        {'rank': 9, 'country': 'Switzerland', 'flag': '\U0001f1e8\U0001f1ed', 'code': 'SUI', 'gold': 4, 'silver': 2, 'bronze': 3, 'total': 9},
        {'rank': 10, 'country': 'Japan', 'flag': '\U0001f1ef\U0001f1f5', 'code': 'JPN', 'gold': 3, 'silver': 5, 'bronze': 9, 'total': 17},
        {'rank': 11, 'country': 'Australia', 'flag': '\U0001f1e6\U0001f1fa', 'code': 'AUS', 'gold': 3, 'silver': 1, 'bronze': 1, 'total': 5},
        {'rank': 12, 'country': 'Great Britain', 'flag': '\U0001f1ec\U0001f1e7', 'code': 'GBR', 'gold': 3, 'silver': 0, 'bronze': 0, 'total': 3},
        {'rank': 13, 'country': 'Czechia', 'flag': '\U0001f1e8\U0001f1ff', 'code': 'CZE', 'gold': 2, 'silver': 2, 'bronze': 0, 'total': 4},
        {'rank': 14, 'country': 'Slovenia', 'flag': '\U0001f1f8\U0001f1ee', 'code': 'SLO', 'gold': 2, 'silver': 1, 'bronze': 1, 'total': 4},
        {'rank': 15, 'country': 'Canada', 'flag': '\U0001f1e8\U0001f1e6', 'code': 'CAN', 'gold': 1, 'silver': 3, 'bronze': 5, 'total': 9},
    ],
    'day': 11, 'events_complete': 76, 'total_events': 116,
    'medal_events_today': 8, 'countries_with_medals': 26
}

_FALLBACK_USA_SPORTS = [
    {'sport': 'Speed Skating', 'gold': 2, 'silver': 0, 'bronze': 0},       # Stolz 500m G, 1000m G
    {'sport': 'Freestyle Skiing', 'gold': 1, 'silver': 3, 'bronze': 1},     # Lemley moguls G + dual moguls B, Kauf moguls S + dual moguls S, Hall slopestyle S
    {'sport': 'Figure Skating', 'gold': 1, 'silver': 1, 'bronze': 0},       # Team event G, Chock/Bates ice dance S
    {'sport': 'Alpine Skiing', 'gold': 1, 'silver': 1, 'bronze': 1},        # Johnson downhill G, + team event B (Wiles/Moltzan)
    {'sport': 'Cross-Country Skiing', 'gold': 0, 'silver': 1, 'bronze': 1}, # Ogden sprint S, Diggins bronze
    {'sport': 'Snowboarding', 'gold': 0, 'silver': 1, 'bronze': 0},         # Kim halfpipe S
    {'sport': 'Short Track', 'gold': 0, 'silver': 1, 'bronze': 1},          # Mixed relay
]
# Auto-compute totals so they can never be inconsistent
FALLBACK_USA = {
    'sports': _FALLBACK_USA_SPORTS,
    'total_gold': sum(s['gold'] for s in _FALLBACK_USA_SPORTS),
    'total_silver': sum(s['silver'] for s in _FALLBACK_USA_SPORTS),
    'total_bronze': sum(s['bronze'] for s in _FALLBACK_USA_SPORTS),
    'total': sum(s['gold'] + s['silver'] + s['bronze'] for s in _FALLBACK_USA_SPORTS),
}

FALLBACK_UPCOMING = {
    'days': [
        {
            'day_num': 12, 'date': 'Feb 17', 'day_of_week': 'Tue', 'medal_count': 7,
            'events': [
                {'time_mst': '1:15 AM', 'event': "Snowboard - Women's Slopestyle Final", 'is_medal': True, 'iso_date': '2026-02-17T01:15:00-07:00'},
                {'time_mst': '2:00 AM', 'event': "Figure Skating - Women's Short Program", 'is_medal': False, 'iso_date': '2026-02-17T02:00:00-07:00'},
                {'time_mst': '3:30 AM', 'event': "Biathlon - Men's 4x7.5km Relay", 'is_medal': True, 'iso_date': '2026-02-17T03:30:00-07:00'},
                {'time_mst': '4:00 AM', 'event': "Speed Skating - Women's Team Pursuit Final", 'is_medal': True, 'iso_date': '2026-02-17T04:00:00-07:00'},
                {'time_mst': '4:30 AM', 'event': "Speed Skating - Men's Team Pursuit Final", 'is_medal': True, 'iso_date': '2026-02-17T04:30:00-07:00'},
                {'time_mst': '5:00 AM', 'event': "Freestyle Skiing - Men's Big Air Final", 'is_medal': True, 'iso_date': '2026-02-17T05:00:00-07:00'},
                {'time_mst': '5:30 AM', 'event': "Cross-Country - Nordic Combined 10km", 'is_medal': True, 'iso_date': '2026-02-17T05:30:00-07:00'},
                {'time_mst': '6:00 AM', 'event': 'Bobsled - Two-Man Final', 'is_medal': True, 'iso_date': '2026-02-17T06:00:00-07:00'},
                {'time_mst': '7:00 AM', 'event': "Ice Hockey - Women's Semifinal", 'is_medal': False, 'iso_date': '2026-02-17T07:00:00-07:00'},
            ]
        },
        {
            'day_num': 13, 'date': 'Feb 18', 'day_of_week': 'Wed', 'medal_count': 8,
            'events': [
                {'time_mst': '1:00 AM', 'event': "Alpine Skiing - Men's Slalom Run 1", 'is_medal': False, 'iso_date': '2026-02-18T01:00:00-07:00'},
                {'time_mst': '2:00 AM', 'event': "Freestyle Skiing - Women's Aerials Final", 'is_medal': True, 'iso_date': '2026-02-18T02:00:00-07:00'},
                {'time_mst': '3:00 AM', 'event': "Short Track - Men's 500m Final", 'is_medal': True, 'iso_date': '2026-02-18T03:00:00-07:00'},
                {'time_mst': '4:00 AM', 'event': "Alpine Skiing - Men's Slalom Run 2", 'is_medal': True, 'iso_date': '2026-02-18T04:00:00-07:00'},
                {'time_mst': '4:30 AM', 'event': "Biathlon - Women's 12.5km Mass Start", 'is_medal': True, 'iso_date': '2026-02-18T04:30:00-07:00'},
                {'time_mst': '5:00 AM', 'event': "Snowboard - Men's Big Air Final", 'is_medal': True, 'iso_date': '2026-02-18T05:00:00-07:00'},
                {'time_mst': '6:00 AM', 'event': "Cross-Country Skiing - Women's 10km", 'is_medal': True, 'iso_date': '2026-02-18T06:00:00-07:00'},
                {'time_mst': '8:00 AM', 'event': "Ice Hockey - Men's Quarterfinal", 'is_medal': False, 'iso_date': '2026-02-18T08:00:00-07:00'},
            ]
        },
    ]
}

FALLBACK_VIDEOS = {
    'videos': [
        {'title': 'Opening Ceremony — Milano Cortina 2026', 'url': 'https://www.youtube.com/watch?v=3S3NGDO3XLo', 'source': 'Olympics', 'emoji': '\U0001f3c6', 'date': 'Feb 6'},
        {'title': 'Jordan Stolz Wins 500m Gold — Olympic Record', 'url': 'https://www.olympics.com/en/milano-cortina-2026/videos/highlights', 'source': 'Olympics.com', 'emoji': '\u26f8\ufe0f', 'date': 'Feb 14'},
        {'title': 'Federica Brignone Giant Slalom Gold at Home', 'url': 'https://www.olympics.com/en/milano-cortina-2026/videos/highlights', 'source': 'Olympics.com', 'emoji': '\u26f7\ufe0f', 'date': 'Feb 15'},
        {'title': "Klaebo Makes History — 9th Winter Olympic Gold", 'url': 'https://www.olympics.com/en/milano-cortina-2026/videos/highlights', 'source': 'Olympics.com', 'emoji': '\U0001f3bf', 'date': 'Feb 15'},
        {'title': "Chloe Kim's Halfpipe Silver — Final Olympic Run", 'url': 'https://www.nbcolympics.com/videos', 'source': 'NBC Olympics', 'emoji': '\U0001f3c2', 'date': 'Feb 12'},
        {'title': "Ilia Malinin's Quad God Moment — Team Event Gold", 'url': 'https://www.nbcolympics.com/videos', 'source': 'NBC Olympics', 'emoji': '\u26f8\ufe0f', 'date': 'Feb 10'},
        {'title': 'Jessie Diggins Bronze — Cross-Country Legend', 'url': 'https://www.nbcolympics.com/videos', 'source': 'NBC Olympics', 'emoji': '\u26f7\ufe0f', 'date': 'Feb 13'},
        {'title': 'Elizabeth Lemley Moguls Gold at 20 Years Old', 'url': 'https://www.nbcolympics.com/videos', 'source': 'NBC Olympics', 'emoji': '\U0001f3d4\ufe0f', 'date': 'Feb 11'},
        {'title': 'Femke Kok Breaks Olympic Record — Women\'s 500m', 'url': 'https://www.olympics.com/en/milano-cortina-2026/videos/highlights', 'source': 'Olympics.com', 'emoji': '\u26f8\ufe0f', 'date': 'Feb 15'},
        {'title': 'Best of Week 1 — Milano Cortina 2026', 'url': 'https://www.olympics.com/en/milano-cortina-2026/videos/highlights', 'source': 'Olympics.com', 'emoji': '\u2744\ufe0f', 'date': 'Feb 14'},
    ]
}

FALLBACK_ATHLETES = {
    'athletes': [
        {'name': 'Jordan Stolz', 'sport': 'Speed Skating', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/26864_HEADSHOT_1.png', 'medals': [{'event': '1000m', 'type': 'gold', 'emoji': '\U0001f947'}, {'event': '500m', 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': 'Won two gold medals with Olympic records in both the 1000m and 500m. First American since 1980 to win multiple speedskating golds at a single Olympics.'},
        {'name': 'Breezy Johnson', 'sport': 'Alpine Skiing', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/25476_HEADSHOT_1.png', 'medals': [{'event': "Women's Downhill", 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': "Won gold in the women's downhill, becoming only the second American woman to accomplish the feat. First gold medal for Team USA at these Games."},
        {'name': 'Elizabeth Lemley', 'sport': 'Freestyle Skiing', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/24147_HEADSHOT_1.png', 'medals': [{'event': "Women's Moguls", 'type': 'gold', 'emoji': '\U0001f947'}, {'event': "Women's Dual Moguls", 'type': 'bronze', 'emoji': '\U0001f949'}], 'bio': "Won gold in her Olympic debut in women's moguls at just 20 years old, then added a bronze in dual moguls."},
        {'name': 'Ilia Malinin', 'sport': 'Figure Skating', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/24783_HEADSHOT_1.png', 'medals': [{'event': 'Team Event', 'type': 'gold', 'emoji': '\U0001f947'}], 'bio': 'Known as the "Quad God," delivered a dominant performance helping Team USA win gold in the figure skating team event.'},
        {'name': 'Ben Ogden', 'sport': 'Cross-Country Skiing', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/23880_HEADSHOT_1.png', 'medals': [{'event': 'Sprint', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Became the first American man to win an Olympic medal in cross-country skiing since 1976, earning silver in the sprint.'},
        {'name': 'Chloe Kim', 'sport': 'Snowboard Halfpipe', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/25527_HEADSHOT_1.png', 'medals': [{'event': 'Halfpipe', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Two-time Olympic champion earned silver in the halfpipe, adding to her legendary Olympic career.'},
        {'name': 'Chock & Bates', 'sport': 'Ice Dance', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/24804_HEADSHOT_1.png', 'medals': [{'event': 'Ice Dance', 'type': 'silver', 'emoji': '\U0001f948'}], 'bio': 'Madison Chock and Evan Bates earned silver in ice dance after being narrowly edged out of the top spot.'},
        {'name': 'Jessie Diggins', 'sport': 'Cross-Country Skiing', 'image': 'https://wmr-static-assets.scd.dgplatform.net/wmr/static/_IMAGE/OWG2026/DT_PIC/23904_HEADSHOT_1.png', 'medals': [{'event': 'Individual', 'type': 'bronze', 'emoji': '\U0001f949'}], 'bio': 'Continued her Olympic legacy with a bronze medal, further cementing her status as the greatest American cross-country skier.'},
    ]
}

FALLBACK_HEADLINES = {
    'headlines': [
        {'title': 'Norway leads medal count with dominant Winter Olympics performance', 'source': 'NBC Sports', 'url': 'https://www.nbcolympics.com/', 'date': 'Feb 16'},
        {'title': 'Italy thrills home crowd with record-breaking medal haul', 'source': 'Olympics.com', 'url': 'https://www.olympics.com/en/milano-cortina-2026', 'date': 'Feb 16'},
        {'title': 'Team USA climbs to third in medal standings at Milano Cortina', 'source': 'Team USA', 'url': 'https://www.teamusa.com/', 'date': 'Feb 16'},
        {'title': 'Figure skating pairs final highlights Day 10 in Milan', 'source': 'NBC Sports', 'url': 'https://www.nbcolympics.com/', 'date': 'Feb 16'},
        {'title': 'Speed skating records continue to fall at Milano Cortina oval', 'source': 'Olympics.com', 'url': 'https://www.olympics.com/en/milano-cortina-2026', 'date': 'Feb 15'},
        {'title': 'Freestyle skiing Big Air events draw massive crowds', 'source': 'Reuters', 'url': 'https://www.reuters.com/sports/', 'date': 'Feb 15'},
        {'title': 'Winter Olympics 2026: Complete guide to the final week', 'source': 'ESPN', 'url': 'https://www.espn.com/olympics/', 'date': 'Feb 15'},
        {'title': 'Ice hockey semifinals set as tournament reaches business end', 'source': 'NBC Sports', 'url': 'https://www.nbcolympics.com/', 'date': 'Feb 15'},
        {'title': 'Biathlon delivers thrilling mass start races in Anterselva', 'source': 'Olympics.com', 'url': 'https://www.olympics.com/en/milano-cortina-2026', 'date': 'Feb 14'},
        {'title': 'Medal count update: 76 of 116 events completed at Milano Cortina', 'source': 'AP News', 'url': 'https://apnews.com/hub/winter-olympics', 'date': 'Feb 14'},
    ]
}

# ── Full Competition Schedule (Days 11–17) ─────────────────────────────────
# Authoritative schedule for remaining days of the Games.
# Times are in CET (hour, minute) — converted to MST at runtime.
# Events marked is_medal=True are medal-deciding finals/events.
# Source: Official Olympic schedule published by IOC / olympics.com
# This data is STATIC (the schedule is set before the Games begin)
# and never depends on an LLM. Results are overlaid dynamically from
# Wikipedia medal winners.

FULL_SCHEDULE = {
    11: {
        'date': 'Feb 16', 'date_iso': '2026-02-16', 'day_of_week': 'Mon',
        'events': [
            {'h': 8, 'm': 5, 'sport': 'Curling', 'event': "Women's Round Robin Session 7", 'is_medal': False},
            {'h': 9, 'm': 0, 'sport': 'Alpine Skiing', 'event': "Men's Slalom Run 1", 'is_medal': False},
            {'h': 9, 'm': 0, 'sport': 'Bobsleigh', 'event': "Two-Man Heat 1", 'is_medal': False},
            {'h': 10, 'm': 0, 'sport': 'Short Track Speed Skating', 'event': "Women's 1000m Quarterfinals", 'is_medal': False},
            {'h': 10, 'm': 17, 'sport': 'Short Track Speed Skating', 'event': "Men's 500m Heats", 'is_medal': False},
            {'h': 10, 'm': 57, 'sport': 'Bobsleigh', 'event': "Two-Man Heat 2", 'is_medal': False},
            {'h': 12, 'm': 47, 'sport': 'Short Track Speed Skating', 'event': "Women's 1000m Final", 'is_medal': True},
            {'h': 13, 'm': 30, 'sport': 'Alpine Skiing', 'event': "Men's Slalom Run 2", 'is_medal': True},
            {'h': 17, 'm': 0, 'sport': 'Bobsleigh', 'event': "Women's Monobob Heat 3", 'is_medal': False},
            {'h': 18, 'm': 0, 'sport': 'Ski Jumping', 'event': "Men's Super Team 1st Round", 'is_medal': False},
            {'h': 18, 'm': 5, 'sport': 'Curling', 'event': "Women's Round Robin Session 8", 'is_medal': False},
            {'h': 18, 'm': 30, 'sport': 'Freestyle Skiing', 'event': "Women's Freeski Big Air Final", 'is_medal': True},
            {'h': 19, 'm': 0, 'sport': 'Figure Skating', 'event': "Pair Skating Free Skating", 'is_medal': True},
            {'h': 19, 'm': 31, 'sport': 'Ski Jumping', 'event': "Men's Super Team Final", 'is_medal': True},
            {'h': 20, 'm': 6, 'sport': 'Bobsleigh', 'event': "Women's Monobob Heat 4", 'is_medal': True},
            {'h': 20, 'm': 10, 'sport': 'Ice Hockey', 'event': "Women's Semifinal", 'is_medal': False},
        ],
    },
    12: {
        'date': 'Feb 17', 'date_iso': '2026-02-17', 'day_of_week': 'Tue',
        'events': [
            {'h': 9, 'm': 15, 'sport': 'Snowboard', 'event': "Women's Slopestyle Final", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Figure Skating', 'event': "Women's Short Program", 'is_medal': False},
            {'h': 10, 'm': 0, 'sport': 'Curling', 'event': "Men's Round Robin", 'is_medal': False},
            {'h': 11, 'm': 30, 'sport': 'Biathlon', 'event': "Men's 4x7.5km Relay", 'is_medal': True},
            {'h': 12, 'm': 0, 'sport': 'Speed Skating', 'event': "Women's Team Pursuit Final", 'is_medal': True},
            {'h': 12, 'm': 30, 'sport': 'Speed Skating', 'event': "Men's Team Pursuit Final", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Freestyle Skiing', 'event': "Men's Big Air Final", 'is_medal': True},
            {'h': 13, 'm': 30, 'sport': 'Nordic Combined', 'event': "Individual Normal Hill/10km", 'is_medal': True},
            {'h': 14, 'm': 0, 'sport': 'Bobsleigh', 'event': "Two-Man Final (Runs 3-4)", 'is_medal': True},
            {'h': 14, 'm': 30, 'sport': 'Ice Hockey', 'event': "Women's Semifinal 1", 'is_medal': False},
            {'h': 18, 'm': 0, 'sport': 'Ice Hockey', 'event': "Women's Semifinal 2", 'is_medal': False},
        ],
    },
    13: {
        'date': 'Feb 18', 'date_iso': '2026-02-18', 'day_of_week': 'Wed',
        'events': [
            {'h': 9, 'm': 0, 'sport': 'Alpine Skiing', 'event': "Men's Slalom Run 1", 'is_medal': False},
            {'h': 10, 'm': 0, 'sport': 'Freestyle Skiing', 'event': "Women's Aerials Final", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Curling', 'event': "Women's Round Robin", 'is_medal': False},
            {'h': 11, 'm': 0, 'sport': 'Short Track Speed Skating', 'event': "Men's 500m Final", 'is_medal': True},
            {'h': 12, 'm': 0, 'sport': 'Alpine Skiing', 'event': "Men's Slalom Run 2", 'is_medal': True},
            {'h': 12, 'm': 30, 'sport': 'Biathlon', 'event': "Women's 12.5km Mass Start", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Snowboard', 'event': "Men's Big Air Final", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Cross-Country Skiing', 'event': "Women's 10km Classic", 'is_medal': True},
            {'h': 14, 'm': 0, 'sport': 'Short Track Speed Skating', 'event': "Women's 1000m Final", 'is_medal': True},
            {'h': 15, 'm': 0, 'sport': 'Ski Jumping', 'event': "Men's Large Hill Individual", 'is_medal': True},
            {'h': 16, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Quarterfinal", 'is_medal': False},
        ],
    },
    14: {
        'date': 'Feb 19', 'date_iso': '2026-02-19', 'day_of_week': 'Thu',
        'events': [
            {'h': 9, 'm': 30, 'sport': 'Alpine Skiing', 'event': "Women's Slalom Run 1", 'is_medal': False},
            {'h': 10, 'm': 0, 'sport': 'Freestyle Skiing', 'event': "Men's Aerials Final", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Curling', 'event': "Men's Semifinal", 'is_medal': False},
            {'h': 11, 'm': 0, 'sport': 'Biathlon', 'event': "Men's 15km Mass Start", 'is_medal': True},
            {'h': 12, 'm': 0, 'sport': 'Speed Skating', 'event': "Women's 5000m", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Alpine Skiing', 'event': "Women's Slalom Run 2", 'is_medal': True},
            {'h': 13, 'm': 30, 'sport': 'Cross-Country Skiing', 'event': "Men's 50km Mass Start Free", 'is_medal': True},
            {'h': 14, 'm': 0, 'sport': 'Figure Skating', 'event': "Women's Free Skate", 'is_medal': True},
            {'h': 15, 'm': 0, 'sport': 'Ice Hockey', 'event': "Women's Bronze Medal Game", 'is_medal': True},
            {'h': 16, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Quarterfinal", 'is_medal': False},
        ],
    },
    15: {
        'date': 'Feb 20', 'date_iso': '2026-02-20', 'day_of_week': 'Fri',
        'events': [
            {'h': 9, 'm': 30, 'sport': 'Freestyle Skiing', 'event': "Women's Ski Cross Final", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Alpine Skiing', 'event': "Team Parallel Event", 'is_medal': True},
            {'h': 10, 'm': 30, 'sport': 'Curling', 'event': "Women's Semifinal", 'is_medal': False},
            {'h': 11, 'm': 0, 'sport': 'Short Track Speed Skating', 'event': "Men's 5000m Relay Final", 'is_medal': True},
            {'h': 11, 'm': 30, 'sport': 'Short Track Speed Skating', 'event': "Women's 3000m Relay Final", 'is_medal': True},
            {'h': 12, 'm': 0, 'sport': 'Speed Skating', 'event': "Men's 10000m", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Bobsleigh', 'event': "Four-Man Runs 1-2", 'is_medal': False},
            {'h': 14, 'm': 0, 'sport': 'Ski Jumping', 'event': "Men's Team Large Hill", 'is_medal': True},
            {'h': 15, 'm': 0, 'sport': 'Ice Hockey', 'event': "Women's Gold Medal Game", 'is_medal': True},
            {'h': 16, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Semifinal 1", 'is_medal': False},
        ],
    },
    16: {
        'date': 'Feb 21', 'date_iso': '2026-02-21', 'day_of_week': 'Sat',
        'events': [
            {'h': 9, 'm': 0, 'sport': 'Freestyle Skiing', 'event': "Men's Ski Cross Final", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Cross-Country Skiing', 'event': "Women's 30km Mass Start Free", 'is_medal': True},
            {'h': 10, 'm': 0, 'sport': 'Curling', 'event': "Men's Gold Medal Game", 'is_medal': True},
            {'h': 11, 'm': 0, 'sport': 'Bobsleigh', 'event': "Four-Man Final (Runs 3-4)", 'is_medal': True},
            {'h': 12, 'm': 0, 'sport': 'Speed Skating', 'event': "Women's Mass Start", 'is_medal': True},
            {'h': 12, 'm': 30, 'sport': 'Speed Skating', 'event': "Men's Mass Start", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Figure Skating', 'event': "Exhibition Gala", 'is_medal': False},
            {'h': 14, 'm': 0, 'sport': 'Curling', 'event': "Women's Gold Medal Game", 'is_medal': True},
            {'h': 15, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Bronze Medal Game", 'is_medal': True},
            {'h': 16, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Semifinal 2", 'is_medal': False},
        ],
    },
    17: {
        'date': 'Feb 22', 'date_iso': '2026-02-22', 'day_of_week': 'Sun',
        'events': [
            {'h': 10, 'm': 0, 'sport': 'Cross-Country Skiing', 'event': "Men's 50km Mass Start Classic", 'is_medal': True},
            {'h': 13, 'm': 0, 'sport': 'Ice Hockey', 'event': "Men's Gold Medal Game", 'is_medal': True},
            {'h': 20, 'm': 0, 'sport': 'Ceremony', 'event': "Closing Ceremony", 'is_medal': False},
        ],
    },
}


# ── Wikipedia Scraper ─────────────────────────────────────────────────────

def scrape_medal_table():
    """Fetch medal table from Wikipedia API. Returns parsed data dict."""
    import requests
    params = {
        'action': 'parse',
        'page': '2026 Winter Olympics medal table',
        'format': 'json',
        'prop': 'text',
        'section': 1,  # Usually the medal table section
    }
    resp = requests.get(WIKI_API, params=params, timeout=30,
                        headers={'User-Agent': 'OlympicsDashboard/1.0'})
    resp.raise_for_status()
    html = resp.json().get('parse', {}).get('text', {}).get('*', '')

    if not html:
        raise ValueError('Empty Wikipedia response')

    # Parse the wikitable HTML for medal data
    # Rows look like: <td>1</td><td>...<a ...>Norway</a>...</td><td>12</td><td>7</td><td>7</td><td>26</td>
    medals = []
    # Find table rows (skip header rows with <th>)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)

    for row in rows:
        # Skip header rows
        if '<th' in row and '<td' not in row:
            continue
        # Extract all cell values
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL)
        if len(cells) < 5:
            continue

        # Clean HTML tags from cells
        clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]

        # Try to find country name (longest text cell) and numbers
        # Typical format: rank, country, gold, silver, bronze, total
        # But Wikipedia may have extra columns
        country = None
        numbers = []
        for c in clean:
            # Check if it's a number
            if re.match(r'^\d+$', c):
                numbers.append(int(c))
            elif len(c) > 2 and not re.match(r'^\d', c) and c != '*':
                country = c

        if country and len(numbers) >= 4:
            # Last 4 numbers are typically: gold, silver, bronze, total
            # But there might be a rank number first
            g, s, b, t = numbers[-4], numbers[-3], numbers[-2], numbers[-1]
            rank = len(medals) + 1

            # Normalize country name
            name = country.replace('\xa0', ' ').strip()
            # Remove footnote markers like [a] or *
            name = re.sub(r'\s*\[.*?\]', '', name).strip()
            name = re.sub(r'\s*\*$', '', name).strip()

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

    # Compute stats
    total_medals_awarded = sum(m['total'] for m in medals)
    # Rough estimate: ~7 medals per event day, 116 total events
    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)

    result = {
        'medals': medals[:15],  # Top 15
        'day': day_num,
        'events_complete': total_medals_awarded // 3 if total_medals_awarded > 0 else 0,
        'total_events': 116,
        'medal_events_today': 8,  # Will be updated by schedule data
        'countries_with_medals': len(medals),
    }
    print(f'  \u2713 Wikipedia: parsed {len(medals)} countries, {total_medals_awarded} total medals')
    return result


# ── Wikipedia Medal Winners Scraper ───────────────────────────────────────

def scrape_medal_winners():
    """Parse 'List of 2026 Winter Olympics medal winners' from Wikipedia.

    Returns a list of dicts: [{'sport': 'Alpine Skiing', 'event': "Men's Downhill",
    'gold': 'Name (CODE)', 'silver': 'Name (CODE)', 'bronze': 'Name (CODE)'}]
    """
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(WIKI_API, params={
        'action': 'parse',
        'page': 'List of 2026 Winter Olympics medal winners',
        'format': 'json',
        'prop': 'text',
    }, timeout=30, headers={'User-Agent': 'OlympicsDashboard/1.0'})
    resp.raise_for_status()
    html = resp.json().get('parse', {}).get('text', {}).get('*', '')
    if not html:
        raise ValueError('Empty Wikipedia medal winners response')

    soup = BeautifulSoup(html, 'lxml')
    results = []
    current_sport = ''
    processed_tables = set()  # Track tables already parsed to avoid duplicates
    skip_headings = {'References', 'See also', 'Notes', 'External links', 'Contents'}

    # Wikipedia structures this as multiple tables, one per sport, each preceded by an h2/h3 heading.
    # Modern Wikipedia API: headings are plain <h2>/<h3> tags wrapped in <div class="mw-heading">.
    # Old format used <span class="mw-headline"> inside headings — no longer present.
    for heading in soup.find_all(['h2', 'h3']):
        heading_text = heading.get_text(strip=True)
        if not heading_text or heading_text in skip_headings:
            continue

        # h2 = sport name (Alpine skiing, Biathlon, etc.)
        # h3 = sub-category (Men's events, Women's events, Mixed events, etc.)
        if heading.name == 'h2':
            current_sport = heading_text

        # Skip if no sport context yet
        if not current_sport:
            continue

        # Find the next wikitable after this heading
        table = heading.find_next('table', class_='wikitable')
        if not table:
            continue

        # Skip tables we've already processed (h2 and h3 may point to same table)
        table_id = id(table)
        if table_id in processed_tables:
            continue
        processed_tables.add(table_id)

        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if len(cells) < 4:
                continue
            # Skip header rows (all th, no td)
            if row.find('th') and not row.find('td'):
                continue

            texts = [c.get_text(strip=True) for c in cells]
            # Typical format: Event | Gold | Silver | Bronze
            event = texts[0] if texts[0] else ''
            if not event or event.startswith('Event') or event.startswith('Discipline'):
                continue
            # Clean "details" link text that Wikipedia appends
            event = re.sub(r'details$', '', event).strip()

            # Extract medalists — get text with country names, replacing <br> with separator
            def extract_medalist(cell):
                """Extract medalist as 'Name (CODE)' or 'CODE' for team-only entries."""
                import copy
                cell_copy = copy.deepcopy(cell)
                # Remove flag images
                for img in cell_copy.find_all('img'):
                    img.decompose()
                # Replace <br> with newline for segment splitting
                for br in cell_copy.find_all('br'):
                    br.replace_with('\n')
                text = cell_copy.get_text(strip=False)
                text = re.sub(r'\[.*?\]', '', text)  # Remove footnotes
                text = re.sub(r'\xa0', ' ', text)
                parts = [p.strip() for p in text.split('\n') if p.strip()]
                if not parts:
                    return ''
                # Separate country names from athlete names
                country_code = None
                athlete_parts = []
                for p in parts:
                    matched_country = False
                    for cname, code in COUNTRY_CODES.items():
                        if p.lower() == cname.lower():
                            country_code = code
                            matched_country = True
                            break
                    if not matched_country:
                        # Check if it's a bare 3-letter IOC code
                        if re.match(r'^[A-Z]{3}$', p) and p in COUNTRY_CODES.values():
                            country_code = p
                        else:
                            athlete_parts.append(p)
                if athlete_parts and country_code:
                    return f'{", ".join(athlete_parts)} ({country_code})'
                elif country_code:
                    return country_code
                else:
                    return ', '.join(parts)

            gold = extract_medalist(cells[1]) if len(cells) > 1 else ''
            silver = extract_medalist(cells[2]) if len(cells) > 2 else ''
            bronze = extract_medalist(cells[3]) if len(cells) > 3 else ''

            if gold or silver or bronze:
                results.append({
                    'sport': current_sport,
                    'event': event,
                    'gold': gold,
                    'silver': silver,
                    'bronze': bronze,
                })

    if not results:
        raise ValueError('Could not parse any medal winners from Wikipedia')

    print(f'  \u2713 Wikipedia medal winners: parsed {len(results)} events across {len(set(r["sport"] for r in results))} sports')
    return results


def derive_usa_breakdown(medal_winners):
    """Derive USA medal breakdown by sport from the full medal winners list."""
    sport_medals = {}
    for r in medal_winners:
        sport = r['sport']
        if sport not in sport_medals:
            sport_medals[sport] = {'sport': sport, 'gold': 0, 'silver': 0, 'bronze': 0}
        # Check if USA/United States appears in each medal position
        if re.search(r'\bUSA\b|\bUnited States\b', r.get('gold', '')):
            sport_medals[sport]['gold'] += 1
        if re.search(r'\bUSA\b|\bUnited States\b', r.get('silver', '')):
            sport_medals[sport]['silver'] += 1
        if re.search(r'\bUSA\b|\bUnited States\b', r.get('bronze', '')):
            sport_medals[sport]['bronze'] += 1

    # Filter to sports where USA has at least one medal
    sports = [s for s in sport_medals.values() if s['gold'] + s['silver'] + s['bronze'] > 0]
    sports.sort(key=lambda s: (s['gold'], s['silver'], s['bronze']), reverse=True)

    total_g = sum(s['gold'] for s in sports)
    total_s = sum(s['silver'] for s in sports)
    total_b = sum(s['bronze'] for s in sports)

    return {
        'sports': sports,
        'total_gold': total_g,
        'total_silver': total_s,
        'total_bronze': total_b,
        'total': total_g + total_s + total_b,
    }


def derive_country_details(medal_winners):
    """Derive per-country medal event details from the full winners list."""
    countries = {}

    def _find_country_code(text):
        """Find country code from medalist text — handles both '(USA)' codes and full names."""
        # First try 3-letter codes like (NOR), USA, etc.
        codes = re.findall(r'\b([A-Z]{3})\b', text)
        for code in codes:
            # Verify it's a real country code
            for name, c in COUNTRY_CODES.items():
                if c == code:
                    return code, name
        # Fall back to full country name matching
        for name, code in COUNTRY_CODES.items():
            if name.lower() in text.lower():
                return code, name
        return None, None

    for r in medal_winners:
        for medal_type in ['gold', 'silver', 'bronze']:
            text = r.get(medal_type, '')
            if not text:
                continue
            code, country_name = _find_country_code(text)
            if not code:
                continue
            if code not in countries:
                countries[code] = {'country': country_name, 'code': code, 'events': []}
            countries[code]['events'].append({
                'event': f'{r["sport"]} - {r["event"]}',
                'medal': medal_type,
                'athlete': text,
            })

    return {'countries': list(countries.values())}


def derive_latest_results(medal_winners, day_num):
    """Derive the latest 3 days of results from the medal winners list.

    This is approximate — Wikipedia doesn't always include dates in the medal winners table.
    We return all results grouped as "recent" since we can't reliably assign days.
    """
    now = datetime.now(MST)

    # We'll try to parse chronological summary for day-specific data
    # But as a baseline, return all results as the current day
    # The medal table is cumulative, so all listed events are completed
    all_results = []
    for r in medal_winners:
        all_results.append({
            'event': f'{r["sport"]} - {r["event"]}',
            'gold': r.get('gold', 'TBD'),
            'silver': r.get('silver', 'TBD'),
            'bronze': r.get('bronze', 'TBD'),
        })

    # NOTE: Chronological summary scraper disabled — Wikipedia's table structure
    # varies (extra columns for country, sport vs event split) causing column
    # misalignment.  The fallback below uses medal_winners data which is reliable.
    # try:
    #     day_results = scrape_chronological_results(day_num)
    #     ...
    # except Exception as e:
    #     print(f'  ! Chronological summary scrape failed: {e}')
    print('  ℹ Using medal-winners fallback for latest results (chronological scraper disabled)')

    # Fallback: show most recent results (last N events) as today,
    # and earlier events as previous days
    events_per_day = max(1, len(all_results) // max(1, day_num))
    days = []
    for i in range(3):
        d = day_num - i
        if d < 1:
            break
        date_str = (now - timedelta(days=i)).strftime('%b %d')
        start = max(0, len(all_results) - events_per_day * (i + 1))
        end = len(all_results) - events_per_day * i
        day_events = all_results[start:end] if start < end else []
        if day_events:
            days.append({'day_num': d, 'date': date_str, 'results': day_events})

    return {'days': days} if days else {'days': []}


def scrape_chronological_results(day_num):
    """Try to get day-specific medal results from Wikipedia chronological summary."""
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(WIKI_API, params={
        'action': 'parse',
        'page': 'Chronological summary of the 2026 Winter Olympics',
        'format': 'json',
        'prop': 'text|sections',
    }, timeout=30, headers={'User-Agent': 'OlympicsDashboard/1.0'})
    resp.raise_for_status()

    data = resp.json().get('parse', {})
    sections = data.get('sections', [])
    html = data.get('text', {}).get('*', '')

    if not html:
        return None

    soup = BeautifulSoup(html, 'lxml')
    now = datetime.now(MST)
    days = []

    for i in range(3):
        d = day_num - i
        if d < 1:
            break
        date_str = (now - timedelta(days=i)).strftime('%b %d')
        target_date = (now - timedelta(days=i))

        # Find section for this day — look for headings like "Day 11 (February 16)"
        # Olympics.com may count days differently (±1), so check multiple day numbers
        day_heading = None
        for heading in soup.find_all(['h2', 'h3']):
            text = heading.get_text(strip=True)
            date_feb = target_date.strftime('%B %d').replace(' 0', ' ')  # "February 16"
            date_d_b = target_date.strftime('%-d %B')  # "16 February"
            if (f'Day {d}' in text or f'Day {d-1}' in text or f'Day {d+1}' in text
                    or date_feb in text or date_d_b in text
                    or target_date.strftime('%B %-d') in text):
                day_heading = heading
                break

        if not day_heading:
            continue

        # Find medal events listed under this day heading.
        # Modern Wikipedia wraps headings in <div class="mw-heading">, so
        # find_next_sibling() on the h2/h3 only finds siblings inside that div.
        # Navigate to the wrapper div first, then iterate its siblings.
        start_elem = day_heading
        if day_heading.parent and 'mw-heading' in ' '.join(day_heading.parent.get('class', [])):
            start_elem = day_heading.parent

        results = []
        elem = start_elem.find_next_sibling()
        while elem:
            # Stop at next heading (either bare h2/h3 or a mw-heading wrapper div)
            if elem.name in ['h2', 'h3']:
                break
            if elem.name == 'div' and 'mw-heading' in ' '.join(elem.get('class', [])):
                break
            if elem.name == 'table' and 'wikitable' in ' '.join(elem.get('class', [])):
                for row in elem.find_all('tr'):
                    cells = row.find_all(['td'])
                    if len(cells) >= 4:
                        event = cells[0].get_text(strip=True)
                        gold = cells[1].get_text(strip=True)
                        silver = cells[2].get_text(strip=True)
                        bronze = cells[3].get_text(strip=True)
                        if event and gold:
                            results.append({
                                'event': re.sub(r'\[.*?\]', '', event),
                                'gold': re.sub(r'\[.*?\]', '', gold),
                                'silver': re.sub(r'\[.*?\]', '', silver),
                                'bronze': re.sub(r'\[.*?\]', '', bronze),
                            })
            elif elem.name in ['ul', 'dl']:
                # Some days list medal events in list format
                for li in elem.find_all('li'):
                    text = li.get_text(strip=True)
                    if '\U0001f947' in text or 'gold' in text.lower() or 'medal' in text.lower():
                        results.append({
                            'event': text[:80],
                            'gold': '', 'silver': '', 'bronze': '',
                        })
            elem = elem.find_next_sibling()

        if results:
            days.append({'day_num': d, 'date': date_str, 'results': results})

    return {'days': days} if days else None


# ── Google News RSS ──────────────────────────────────────────────────────

def get_headlines_rss():
    """Fetch Olympics headlines from Google News RSS. No API key needed."""
    import feedparser

    feed_url = 'https://news.google.com/rss/search?q=2026+Winter+Olympics&hl=en-US&gl=US&ceid=US:en'
    feed = feedparser.parse(feed_url)

    if not feed.entries:
        raise ValueError('Google News RSS returned no entries')

    headlines = []
    for entry in feed.entries[:10]:
        # Parse publication date
        pub_date = ''
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            from time import mktime
            dt = datetime.fromtimestamp(mktime(entry.published_parsed))
            pub_date = dt.strftime('%b %d')

        # Extract source name
        source = ''
        if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
            source = entry.source.title
        elif ' - ' in entry.title:
            # Google News sometimes appends source to title
            parts = entry.title.rsplit(' - ', 1)
            if len(parts) == 2:
                source = parts[1].strip()

        headlines.append({
            'title': entry.title.rsplit(' - ', 1)[0].strip() if ' - ' in entry.title else entry.title,
            'source': source,
            'url': entry.link,
            'date': pub_date,
        })

    print(f'  \u2713 Google News RSS: got {len(headlines)} headlines')
    return {'headlines': headlines}


# ── YouTube Data API ─────────────────────────────────────────────────────

def get_video_highlights_youtube():
    """Fetch Olympics video highlights from YouTube Data API v3."""
    yt_key = YOUTUBE_API_KEY
    if not yt_key:
        raise ValueError('YOUTUBE_API_KEY not set')

    import requests as req

    # Search for recent Olympics highlight videos
    params = {
        'part': 'snippet',
        'q': '2026 Winter Olympics highlights',
        'type': 'video',
        'order': 'date',
        'maxResults': 10,
        'publishedAfter': (datetime.now(MST) - timedelta(days=14)).strftime('%Y-%m-%dT00:00:00Z'),
        'key': yt_key,
    }
    resp = req.get('https://www.googleapis.com/youtube/v3/search', params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json().get('items', [])

    if not items:
        raise ValueError('YouTube API returned no videos')

    # Sport emoji mapping based on title keywords
    sport_emojis = {
        'skating': '\u26f8\ufe0f', 'skate': '\u26f8\ufe0f', 'figure': '\u26f8\ufe0f',
        'hockey': '\U0001f3d2', 'ski': '\u26f7\ufe0f', 'alpine': '\u26f7\ufe0f',
        'slalom': '\u26f7\ufe0f', 'downhill': '\u26f7\ufe0f',
        'snowboard': '\U0001f3c2', 'halfpipe': '\U0001f3c2',
        'bobsled': '\U0001f6f7', 'luge': '\U0001f6f7', 'skeleton': '\U0001f6f7',
        'biathlon': '\U0001f3bf', 'cross-country': '\U0001f3bf', 'nordic': '\U0001f3bf',
        'curling': '\U0001f94c',
    }

    videos = []
    for item in items:
        snippet = item.get('snippet', {})
        title = snippet.get('title', '')
        video_id = item.get('id', {}).get('videoId', '')

        # Determine sport emoji from title
        emoji = '\U0001f3d4\ufe0f'  # default mountain
        for keyword, em in sport_emojis.items():
            if keyword in title.lower():
                emoji = em
                break

        # Parse publish date
        pub = snippet.get('publishedAt', '')
        pub_date = ''
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                pub_date = dt.strftime('%b %d')
            except (ValueError, TypeError):
                pass

        videos.append({
            'title': title,
            'url': f'https://www.youtube.com/watch?v={video_id}',
            'source': snippet.get('channelTitle', 'YouTube'),
            'emoji': emoji,
            'date': pub_date,
        })

    print(f'  \u2713 YouTube API: got {len(videos)} videos')
    return {'videos': videos}


# ── Wikipedia Sport Schedule Scraper ──────────────────────────────────────

def scrape_sport_page_events(wiki_page, sport_name):
    """Parse a sport's Wikipedia page for its event schedule.

    Looks for schedule/results tables and extracts events with dates, times,
    and medal indicators. Returns list of event dicts.
    """
    import requests
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(WIKI_API, params={
            'action': 'parse', 'page': wiki_page,
            'format': 'json', 'prop': 'text',
        }, timeout=20, headers={'User-Agent': 'OlympicsDashboard/1.0'})
        resp.raise_for_status()
    except Exception as e:
        print(f'    ! Could not fetch {wiki_page}: {e}')
        return []

    html = resp.json().get('parse', {}).get('text', {}).get('*', '')
    if not html:
        return []

    soup = BeautifulSoup(html, 'lxml')
    events = []

    for table in soup.find_all('table', class_='wikitable'):
        rows = table.find_all('tr')
        if not rows:
            continue

        # Check if table looks like a schedule
        table_text = table.get_text()
        if not re.search(r'February|Feb\s+\d|2026-02', table_text):
            continue

        current_date = None
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            cell_texts = [c.get_text(strip=True) for c in cells]
            row_text = ' '.join(cell_texts)

            # Extract date — handle both "February 7" and "7 February" formats
            # Use negative lookahead to avoid matching time components like "February 11:30"
            date_match = re.search(r'(?:February|Feb)[.,]?\s*(\d{1,2})(?!\s*:)', row_text)
            if not date_match:
                # European format: "7 February" or "7 Feb"
                date_match = re.search(r'(\d{1,2})\s+(?:February|Feb)\b', row_text)
            if date_match:
                day_val = int(date_match.group(1))
                if 1 <= day_val <= 28:  # Sanity check
                    current_date = f'2026-02-{day_val:02d}'

            # Also try ISO format dates
            iso_match = re.search(r'2026-02-(\d{2})', row_text)
            if iso_match and not date_match:
                current_date = f'2026-02-{iso_match.group(1)}'

            if not current_date:
                continue

            # Extract time (CET)
            time_match = re.search(r'(\d{1,2}):(\d{2})\s*(?:CET|CEST|local)?', row_text)
            time_cet = None
            if time_match:
                h, m = int(time_match.group(1)), int(time_match.group(2))
                if 0 <= h <= 23:
                    time_cet = (h, m)

            # Extract event name — longest substantive cell text
            event_name = ''
            for ct in cell_texts:
                ct_clean = re.sub(r'\[.*?\]', '', ct).strip()
                if re.match(r'^\d{1,2}:\d{2}', ct_clean):
                    continue
                if re.match(r'^(?:February|Feb)', ct_clean):
                    continue
                # Skip date headers like "Saturday, 7 February", "15 February", "Thursday, 12 February"
                if re.match(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]', ct_clean, re.I):
                    continue
                if re.match(r'^\d{1,2}\s+(?:February|Feb|January|Jan)\b', ct_clean, re.I):
                    continue
                if len(ct_clean) > len(event_name) and len(ct_clean) > 5:
                    event_name = ct_clean

            if not event_name:
                continue

            is_medal = bool(re.search(r'Final|Medal|Gold|medal\s*event', row_text, re.I))

            events.append({
                'sport': sport_name,
                'event': event_name,
                'date': current_date,
                'time_cet': time_cet or (10, 0),
                'is_medal': is_medal,
            })

    return events


def scrape_all_sport_schedules():
    """Scrape all Wikipedia sport pages for event schedules.
    Returns list of event dicts sorted by date and time.
    """
    import time as _time
    all_events = []
    for sport, page in SPORT_WIKI_PAGES.items():
        try:
            sport_events = scrape_sport_page_events(page, sport)
            all_events.extend(sport_events)
        except Exception as e:
            print(f'    ! Schedule scrape failed for {sport}: {e}')
        _time.sleep(0.1)  # Be nice to Wikipedia

    all_events.sort(key=lambda e: (e['date'], e['time_cet'][0], e['time_cet'][1]))

    if all_events:
        sports_found = len(set(e['sport'] for e in all_events))
        print(f'  ✓ Wikipedia sport schedules: {len(all_events)} events across {sports_found} sports')
    else:
        print('  ! Wikipedia sport schedule scraping returned no events')

    return all_events


def _match_event_in_winners(event_sport, event_name, medal_winners):
    """Try to find a medal winner entry matching this scheduled event.
    Returns the winner dict or None."""
    event_lower = event_name.lower()
    sport_lower = event_sport.lower()

    for w in medal_winners:
        w_event = w.get('event', '').lower()
        w_sport = w.get('sport', '').lower()
        # Direct match
        if w_event == event_lower:
            return w
        # Sport + event substring matching
        if sport_lower in w_sport or w_sport in sport_lower:
            if w_event in event_lower or event_lower in w_event:
                return w
            # Fuzzy: key words overlap
            event_words = set(re.findall(r"[a-z]+", event_lower))
            winner_words = set(re.findall(r"[a-z]+", w_event))
            overlap = event_words & winner_words - {'men', 'women', 'the', 'and', 'of'}
            if len(overlap) >= 2:
                return w
    return None


def build_today_schedule(wiki_events, medal_winners):
    """Build today's schedule from Wikipedia events + hardcoded fallback, with results overlay.

    Args:
        wiki_events: Events from scrape_all_sport_schedules() (may be empty)
        medal_winners: Events from scrape_medal_winners()
    Returns:
        {'events': [{'time_mst', 'event', 'sport', 'status', 'is_medal', 'result'}]}
    """
    now = datetime.now(MST)
    today_iso = now.strftime('%Y-%m-%d')
    day_num = max(1, (now - GAMES_START).days + 1)

    # Get today's events — prefer Wikipedia, fall back to hardcoded
    today_events = [e for e in wiki_events if e['date'] == today_iso]

    if not today_events:
        # Try by day_num first, then by date_iso match across all days
        sched = FULL_SCHEDULE.get(day_num)
        if not sched:
            for d, s in FULL_SCHEDULE.items():
                if s['date_iso'] == today_iso:
                    sched = s
                    break
        if sched:
            today_events = [{
                'sport': e['sport'], 'event': e['event'],
                'date': sched['date_iso'],
                'time_cet': (e['h'], e['m']),
                'is_medal': e['is_medal'],
            } for e in sched['events']]
            if today_events:
                print(f'  ↳ Using hardcoded schedule for Day {day_num} ({len(today_events)} events)')

    if not today_events:
        return {'events': []}

    schedule_events = []
    for e in today_events:
        tc = e['time_cet']
        time_mst = cet_to_mst_str(tc[0], tc[1])
        full_name = f'{e["sport"]} - {e["event"]}'

        # Determine event status using medal results + time-based logic
        result = ''
        status = 'upcoming'

        # First check: do we have medal results for this event?
        winner = _match_event_in_winners(e['sport'], e['event'], medal_winners)
        if winner:
            status = 'done'
            result = f'\U0001f947 {winner.get("gold", "")} \u2022 \U0001f948 {winner.get("silver", "")} \u2022 \U0001f949 {winner.get("bronze", "")}'
        else:
            # Time-based status: convert event CET time to MST for comparison
            event_date = now.date()
            try:
                event_cet_dt = datetime(event_date.year, event_date.month, event_date.day,
                                        tc[0], tc[1], tzinfo=CET)
                event_mst_dt = event_cet_dt.astimezone(MST)

                if now > event_mst_dt + timedelta(hours=3):
                    # Event ended 3+ hours ago — mark as done
                    status = 'done'
                elif now > event_mst_dt + timedelta(minutes=30):
                    # Event likely in progress or recently finished
                    status = 'live' if e['is_medal'] else 'done'
                elif now >= event_mst_dt - timedelta(minutes=15):
                    # Event starting soon or just started
                    status = 'live'
            except Exception:
                pass  # Keep as upcoming if time conversion fails

        schedule_events.append({
            'time_mst': time_mst,
            'event': full_name,
            'sport': e['sport'],
            'status': status,
            'is_medal': e['is_medal'],
            'result': result,
        })

    schedule_events.sort(key=lambda x: _parse_time_for_sort(x['time_mst']))
    return {'events': schedule_events}


def build_upcoming_events(wiki_events):
    """Build upcoming events for next 2-3 days from Wikipedia events + hardcoded fallback.

    Returns:
        {'days': [{'day_num', 'date', 'day_of_week', 'medal_count', 'events': [...]}]}
    """
    now = datetime.now(MST)
    days = []

    for offset in range(1, 4):
        target = now + timedelta(days=offset)
        target_iso = target.strftime('%Y-%m-%d')
        day_num = max(1, (target - GAMES_START).days + 1)

        if target > GAMES_END:
            break

        # Prefer Wikipedia events, fall back to hardcoded
        day_events = [e for e in wiki_events if e['date'] == target_iso]
        source = 'Wikipedia'

        if not day_events:
            # Try by day_num first, then by date_iso match
            sched = FULL_SCHEDULE.get(day_num)
            if not sched:
                for d, s in FULL_SCHEDULE.items():
                    if s['date_iso'] == target_iso:
                        sched = s
                        break
            if sched:
                day_events = [{
                    'sport': e['sport'], 'event': e['event'],
                    'date': sched['date_iso'],
                    'time_cet': (e['h'], e['m']),
                    'is_medal': e['is_medal'],
                } for e in sched['events']]
                source = 'hardcoded'

        if not day_events:
            continue

        formatted = []
        medal_count = 0
        for e in day_events:
            tc = e['time_cet']
            time_mst = cet_to_mst_str(tc[0], tc[1])
            iso_date = cet_to_mst_iso(tc[0], tc[1], target_iso)
            formatted.append({
                'time_mst': time_mst,
                'event': f'{e["sport"]} - {e["event"]}',
                'is_medal': e['is_medal'],
                'iso_date': iso_date,
            })
            if e['is_medal']:
                medal_count += 1

        formatted.sort(key=lambda x: _parse_time_for_sort(x['time_mst']))

        days.append({
            'day_num': day_num,
            'date': target.strftime('%b %d'),
            'day_of_week': target.strftime('%a'),
            'medal_count': medal_count,
            'events': formatted,
        })
        print(f'  ✓ Upcoming Day {day_num}: {len(formatted)} events ({source})')

    return {'days': days}


# ── Data Fetchers ──────────────────────────────────────────────────────────

def get_medal_table():
    """Fetch medal table from Wikipedia."""
    return scrape_medal_table()


# ── HTML Generators ────────────────────────────────────────────────────────

def html_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def _extract_youtube_id(url):
    """Extract YouTube video ID from various URL formats."""
    m = re.search(r'(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})', url or '')
    return m.group(1) if m else None


def build_medal_table_rows(medals, country_details=None):
    """Build medal table with expandable per-event details."""
    # Build lookup from country code to event details
    details_map = {}
    if country_details and 'countries' in country_details:
        for c in country_details['countries']:
            code = c.get('code', '')
            details_map[code] = c.get('events', [])

    rows = ''
    for m in medals.get('medals', []):
        code = m.get('code', '')
        us = ' us-row' if code == 'USA' else ''
        flag = m.get('flag', '')
        events = details_map.get(code, [])
        has_details = len(events) > 0
        expand_cls = ' expandable' if has_details else ''
        arrow = '<span class="expand-arrow">\u25B6</span> ' if has_details else ''
        onclick = f' onclick="toggleCountry(this)"' if has_details else ''

        rows += f'<tr class="country-row{us}{expand_cls}"{onclick}><td class="rk">{m["rank"]}</td><td class="country-name">{arrow}{flag} {html_escape(m["country"])}</td><td class="g">{m["gold"]}</td><td class="s">{m["silver"]}</td><td class="b">{m["bronze"]}</td><td class="tot">{m["total"]}</td></tr>\n'

        if has_details:
            detail_rows = ''
            for evt in events:
                medal_type = evt.get('medal', 'gold')
                medal_cls = {'gold': 'g', 'silver': 's', 'bronze': 'b'}.get(medal_type, 'g')
                medal_emoji = {'gold': '\U0001f947', 'silver': '\U0001f948', 'bronze': '\U0001f949'}.get(medal_type, '\U0001f947')
                # Strip country code suffix — the parent row already shows the country
                athlete_raw = evt.get('athlete', '')
                athlete_display = re.sub(r'\s*\([A-Z]{3}\)\s*$', '', athlete_raw).strip() or athlete_raw
                athlete = html_escape(athlete_display)
                event_name = html_escape(evt.get('event', ''))
                detail_rows += f'<div class="medal-detail-item"><span class="medal-detail-emoji {medal_cls}">{medal_emoji}</span><span class="medal-detail-event">{event_name}</span><span class="medal-detail-athlete">{athlete}</span></div>\n'
            rows += f'<tr class="country-detail-row" style="display:none;"><td colspan="6"><div class="medal-details">{detail_rows}</div></td></tr>\n'

    return rows


def build_schedule_rows(schedule):
    events = schedule.get('events', [])
    if not events:
        return '<div class="section-empty">\u23f3 Schedule data temporarily unavailable. <a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);">View live schedule \u2192</a></div>'
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

        raw_result = evt.get('result', '') if status == 'done' else ''
        # Filter out results containing TBD placeholders — show nothing rather than bogus data
        result = f' {html_escape(raw_result)}' if raw_result and 'TBD' not in raw_result else ''

        rows += f'<div class="{" ".join(classes)}"><span class="evt-time">{html_escape(evt["time_mst"])}</span><div class="evt-info"><div class="evt-name">{html_escape(evt["event"])}</div><div class="evt-detail">{badge}{result}</div></div></div>\n'
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
    if not days:
        return '<div class="section-empty">\U0001f3c5 Results data temporarily unavailable. <a href="https://www.olympics.com/en/milano-cortina-2026/medals" target="_blank" style="color:var(--accent);">View results \u2192</a></div>'

    tabs = ''
    contents = ''
    for i, day in enumerate(days):
        day_id = f'd{day["day_num"]}'
        active = ' active' if i == 0 else ''
        tabs += f'<button class="day-tab{active}" onclick="showDay(\'{day_id}\', this)">Day {day["day_num"]} ({html_escape(day["date"])})</button>\n'

        cards = ''
        results_list = day.get('results', [])
        if not results_list:
            cards = '<div class="section-empty">\u23f3 Results pending \u2014 medal events in progress or upcoming today. Check back soon!</div>\n'
        else:
            for r in results_list:
                cards += f'<div class="result-card"><div class="result-event">{html_escape(r["event"])}</div><div class="result-medals">\U0001f947 {html_escape(r["gold"])} &bull; \U0001f948 {html_escape(r["silver"])} &bull; \U0001f949 {html_escape(r["bronze"])}</div></div>\n'
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

        # Auto-generate YouTube thumbnail from video ID
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
        # Determine avatar class from sport
        avatar_cls = 'avatar-snow'
        for key, cls in sport_avatars.items():
            if key in sport.lower():
                avatar_cls = cls
                break
        # Generate initials
        parts = name.split()
        initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else name[:2].upper()
        # Build medal tags — support both new multi-medal and old single-medal format
        medal_tags = ''
        if 'medals' in a and isinstance(a['medals'], list):
            for m in a['medals']:
                mtype = m.get('type', 'gold')
                color = medal_colors.get(mtype, 'g')
                emoji = m.get('emoji', '\U0001f947')
                event = m.get('event', '')
                medal_tags += f'<span class="athlete-medal-tag {color}">{emoji} {html_escape(event)}</span> '
        else:
            # Legacy single-medal format
            medal = a.get('medal', 'gold')
            color = medal_colors.get(medal, 'g')
            emoji = a.get('medal_emoji', '\U0001f947')
            medal_tags = f'<span class="athlete-medal-tag {color}">{emoji} {medal.title()}</span>'
        # Add headshot image if URL available, fallback to initials
        image_url = a.get('image', '')
        if image_url:
            avatar_inner = f'{initials}<img src="{html_escape(image_url)}" alt="{html_escape(name)}" onerror="this.style.display=\'none\'">'
        else:
            avatar_inner = initials
        cards += f'<div class="athlete-card"><div class="athlete-avatar {avatar_cls}">{avatar_inner}</div><div class="athlete-content"><div class="athlete-top"><span class="athlete-name">{html_escape(name)} &bull; {html_escape(sport)}</span>{medal_tags}</div><div class="athlete-bio">{html_escape(a.get("bio", ""))}</div></div></div>\n'
    return cards


def build_upcoming_section(upcoming):
    days = upcoming.get('days', [])
    if not days:
        return '<div class="section-empty">\U0001f4c6 Upcoming events temporarily unavailable. <a href="https://www.olympics.com/en/milano-cortina-2026/schedule" target="_blank" style="color:var(--accent);">View schedule \u2192</a></div>'
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
    return rows


def build_notifications(day_num, events_complete, total_events):
    """Build date-aware notification JS array for today's top results."""
    try:
        remaining = max(0, 16 - int(day_num) + 1)
    except (TypeError, ValueError):
        remaining = '?'
    return f"""  var medalQueue = [
    {{delay:12000, type:'notif-info', title:'Day {day_num} Results Updated', body:'{events_complete} of {total_events} events complete. {remaining} days remaining.'}},
  ];"""


# ── Main Template ──────────────────────────────────────────────────────────

def generate_html(medal_data, schedule, usa, results, headlines, videos, athletes, upcoming, country_details=None):
    now = datetime.now(MST)
    timestamp = now.strftime('%a, %b %d %I:%M %p MST')
    data_date = now.strftime('%Y-%m-%d')

    # Always compute day from current date — never trust API-returned day number
    day = max(1, (now - GAMES_START).days + 1)
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
    usa_total = usa.get('total', 14)

    medal_rows = build_medal_table_rows(medal_data, country_details)
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
# Using Python format strings. Sections are injected via {{section_name}} style.
# Double curly braces {{ }} are used for literal JS braces.

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
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; align-items: stretch; }}
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
.country-row.expandable {{ cursor: pointer; }}
.country-row.expandable:hover td {{ background: rgba(56,189,248,0.08); }}
.expand-arrow {{ display: inline-block; font-size: 0.6rem; transition: transform 0.2s; margin-right: 4px; color: var(--text-muted); }}
.country-row.expanded .expand-arrow {{ transform: rotate(90deg); }}
.country-detail-row td {{ padding: 0 !important; border-bottom: 1px solid var(--bg-muted); }}
.medal-details {{ padding: 8px 16px 8px 46px; background: var(--bg-surface); display: flex; flex-direction: column; gap: 4px; }}
.medal-detail-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.78rem; padding: 3px 0; }}
.medal-detail-emoji {{ font-size: 0.82rem; min-width: 22px; }}
.medal-detail-event {{ color: var(--text-primary); font-weight: 600; flex: 1; }}
.medal-detail-athlete {{ color: var(--text-secondary); font-size: 0.75rem; }}
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
.result-card {{ background: var(--bg-surface); border-radius: 8px; padding: 12px 16px; margin-bottom: 6px; border-left: 3px solid var(--gold); }}
.result-card .result-event {{ font-weight: 700; font-size: 0.9rem; margin-bottom: 4px; }}
.result-card .result-medals {{ font-size: 0.82rem; color: var(--text-secondary); }}
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
<div class="panel-hdr">&#x1F947; Medal Count by Country</div>
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
<div class="panel tall">
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
<div class="panel-hdr">&#x1F4F0; Top 10 Headlines</div>
{headline_rows}</div>
<div class="panel">
<div class="panel-hdr">&#x1F3AC; Top Video Highlights</div>
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

function toggleCountry(row) {{
  var detailRow = row.nextElementSibling;
  if (detailRow && detailRow.classList.contains('country-detail-row')) {{
    var isVisible = detailRow.style.display !== 'none';
    detailRow.style.display = isVisible ? 'none' : 'table-row';
    row.classList.toggle('expanded', !isVisible);
  }}
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


# ── Post-Processing / Validation Helpers ──────────────────────────────────

def extract_results_from_schedule(schedule, day_num, date_str):
    """Extract medal results from today's schedule when results API returns empty.
    Uses events marked as 'done' with is_medal=True that have result text."""
    results = []
    for evt in schedule.get('events', []):
        if evt.get('status') == 'done' and evt.get('is_medal') and evt.get('result'):
            raw = evt.get('result', '')
            if 'TBD' in raw:
                continue
            # Parse result string like "🥇 Name (CODE) • 🥈 Name • 🥉 Name"
            parts = re.split(r'\s*[•·|]\s*', raw)
            gold = silver = bronze = ''
            for p in parts:
                p = p.strip()
                if '\U0001f947' in p or 'gold' in p.lower():
                    gold = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', p).strip()
                elif '\U0001f948' in p or 'silver' in p.lower():
                    silver = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', p).strip()
                elif '\U0001f949' in p or 'bronze' in p.lower():
                    bronze = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', p).strip()
            if not gold and len(parts) >= 1:
                gold = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', parts[0]).strip()
            if not silver and len(parts) >= 2:
                silver = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', parts[1]).strip()
            if not bronze and len(parts) >= 3:
                bronze = re.sub(r'[\U0001f947\U0001f948\U0001f949]', '', parts[2]).strip()
            if gold:
                results.append({
                    'event': evt.get('event', ''),
                    'gold': gold,
                    'silver': silver or 'TBD',
                    'bronze': bronze or 'TBD',
                })
    if results:
        return {'day_num': day_num, 'date': date_str, 'results': results}
    return None


def deduplicate_videos(videos):
    """Remove videos with duplicate YouTube IDs. First occurrence wins."""
    seen_ids = set()
    unique = []
    for v in videos.get('videos', []):
        yt_id = _extract_youtube_id(v.get('url', ''))
        if yt_id and yt_id in seen_ids:
            continue
        if yt_id:
            seen_ids.add(yt_id)
        unique.append(v)
    return {'videos': unique}


def validate_schedule_times(schedule):
    """Flag events with implausible MST times.
    Most events in Italy happen 8AM-11PM CET = midnight-4PM MST.
    Events outside midnight-5PM MST are suspicious."""
    events = schedule.get('events', [])
    validated = []
    for evt in events:
        time_str = evt.get('time_mst', '')
        # Parse hour from time string like "2:00 AM" or "3:40 PM"
        m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
        if m:
            hour = int(m.group(1))
            ampm = m.group(3).upper()
            if ampm == 'PM' and hour != 12:
                hour += 12
            elif ampm == 'AM' and hour == 12:
                hour = 0
            # Reject events after 5 PM MST (= midnight CET, events don't run that late)
            if hour > 17:
                print(f'  ! Dropping implausible schedule time: {time_str} for {evt.get("event", "")}')
                continue
        validated.append(evt)
    return {'events': validated}


# ── Data Validator ─────────────────────────────────────────────────────────

def validate_dashboard_data(medal_data, schedule, usa, results, country_details):
    """Validate dashboard data for consistency and formatting. Returns list of warnings."""
    warnings = []

    # 1. Medal table consistency
    medals = medal_data.get('medals', [])
    if not medals:
        warnings.append('CRITICAL: Medal table is empty')
    else:
        for m in medals:
            expected = m['gold'] + m['silver'] + m['bronze']
            if expected != m['total']:
                warnings.append(f"Medal math: {m['country']} {m['gold']}+{m['silver']}+{m['bronze']}={expected} != total={m['total']}")

    # 2. USA breakdown vs medal table cross-check
    if usa.get('sports'):
        computed_g = sum(s['gold'] for s in usa['sports'])
        computed_s = sum(s['silver'] for s in usa['sports'])
        computed_b = sum(s['bronze'] for s in usa['sports'])
        if computed_g != usa.get('total_gold', computed_g):
            warnings.append(f'USA gold mismatch: sports sum={computed_g}, declared={usa.get("total_gold")}')
        usa_row = next((m for m in medals if m.get('code') == 'USA'), None)
        if usa_row:
            table_total = usa_row['gold'] + usa_row['silver'] + usa_row['bronze']
            breakdown_total = computed_g + computed_s + computed_b
            if breakdown_total != table_total:
                warnings.append(f'USA breakdown total={breakdown_total} != medal table total={table_total}')

    # 3. Pipe character checks (formatting regression)
    pipe_found = False
    for e in schedule.get('events', []):
        if '|' in e.get('result', ''):
            pipe_found = True
            break
    for day in results.get('days', []):
        for r in day.get('results', []):
            for fld in ['gold', 'silver', 'bronze']:
                if '|' in r.get(fld, ''):
                    pipe_found = True
                    break
    if country_details:
        for c in country_details.get('countries', []):
            for evt in c.get('events', []):
                if '|' in evt.get('athlete', ''):
                    pipe_found = True
                    break
    if pipe_found:
        warnings.append('FORMATTING: Pipe characters "|" found in display data')

    # 4. TBD checks in results
    tbd_count = 0
    for day in results.get('days', []):
        for r in day.get('results', []):
            for fld in ['gold', 'silver', 'bronze']:
                if r.get(fld, '') == 'TBD':
                    tbd_count += 1
    if tbd_count > 0:
        warnings.append(f'DATA: {tbd_count} TBD medal entries in results')

    # 5. Schedule completeness
    events = schedule.get('events', [])
    if not events:
        warnings.append('WARNING: Schedule has no events')

    # 6. Results completeness
    if not results.get('days'):
        warnings.append('WARNING: No result days available')

    return warnings


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    print(f'Starting dashboard update at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')
    now = datetime.now(MST)
    day_num = max(1, (now - GAMES_START).days + 1)
    print(f'  Day {day_num} of the Games')

    sections = {}

    # ── Step 1: Medal table from Wikipedia ────────────────────────────────
    try:
        sections['medals'] = get_medal_table()
        print('  ✓ Medal table from Wikipedia')
    except Exception as e:
        print(f'  ✗ Medal table failed: {e}')
        sections['medals'] = FALLBACK_MEDALS

    if not sections['medals'].get('medals'):
        print('  ↳ Using fallback medal data')
        sections['medals'] = FALLBACK_MEDALS

    # ── Step 2: Medal winners from Wikipedia ──────────────────────────────
    medal_winners = []
    try:
        medal_winners = scrape_medal_winners()
    except Exception as e:
        print(f'  ✗ Medal winners scrape failed: {e}')
        traceback.print_exc()

    # ── Step 3: Derive USA breakdown ──────────────────────────────────────
    if medal_winners:
        try:
            sections['usa'] = derive_usa_breakdown(medal_winners)
            usa_row = next((m for m in sections['medals'].get('medals', []) if m.get('code') == 'USA'), None)
            if usa_row and sections['usa']['total'] != usa_row['total']:
                print(f'  ↳ USA breakdown total {sections["usa"]["total"]} != medal table {usa_row["total"]}, using fallback')
                sections['usa'] = FALLBACK_USA
            else:
                print(f'  ✓ USA breakdown: {sections["usa"]["total"]} medals across {len(sections["usa"]["sports"])} sports')
        except Exception as e:
            print(f'  ✗ USA breakdown failed: {e}')
            sections['usa'] = FALLBACK_USA
    else:
        sections['usa'] = FALLBACK_USA
        print('  ↳ Using fallback USA breakdown')

    # ── Step 4: Derive country details ────────────────────────────────────
    if medal_winners:
        try:
            sections['country_details'] = derive_country_details(medal_winners)
            print(f'  ✓ Country details: {len(sections["country_details"].get("countries", []))} countries')
        except Exception as e:
            print(f'  ✗ Country details failed: {e}')
            sections['country_details'] = {'countries': []}
    else:
        sections['country_details'] = {'countries': []}

    # ── Step 5: Derive latest results ─────────────────────────────────────
    if medal_winners:
        try:
            sections['results'] = derive_latest_results(medal_winners, day_num)
            total_results = sum(len(d.get('results', [])) for d in sections['results'].get('days', []))
            print(f'  ✓ Results: {total_results} events across {len(sections["results"].get("days", []))} days')
        except Exception as e:
            print(f'  ✗ Results derivation failed: {e}')
            sections['results'] = {'days': []}
    else:
        sections['results'] = {'days': []}

    # ── Step 6: Headlines from Google News RSS ────────────────────────────
    try:
        sections['headlines'] = get_headlines_rss()
    except Exception as e:
        print(f'  ✗ Headlines RSS failed: {e}')
        sections['headlines'] = {'headlines': []}

    if not sections['headlines'].get('headlines'):
        print('  ↳ Using fallback headlines')
        sections['headlines'] = FALLBACK_HEADLINES

    # ── Step 7: Videos from YouTube Data API ──────────────────────────────
    try:
        sections['videos'] = get_video_highlights_youtube()
    except Exception as e:
        print(f'  ✗ YouTube API failed: {e}')
        sections['videos'] = {'videos': []}

    sections['videos'] = deduplicate_videos(sections['videos'])
    if len(sections['videos'].get('videos', [])) < 4:
        print(f'  ↳ Using fallback videos ({len(sections["videos"].get("videos", []))} unique from API)')
        sections['videos'] = FALLBACK_VIDEOS

    # ── Step 8: Sport schedules from Wikipedia ────────────────────────────
    # Scrape all 15 sport pages for event schedules (dates, times, medal status).
    # This replaces Perplexity entirely for schedule + upcoming events.
    wiki_schedule_events = []
    try:
        wiki_schedule_events = scrape_all_sport_schedules()
    except Exception as e:
        print(f'  ✗ Sport schedule scraping failed: {e}')
        traceback.print_exc()

    # ── Step 9: Build today's schedule ────────────────────────────────────
    # Uses Wikipedia sport events → hardcoded FULL_SCHEDULE → empty
    # Results overlaid from medal_winners (Step 2)
    try:
        sections['schedule'] = build_today_schedule(wiki_schedule_events, medal_winners)
        event_count = len(sections['schedule'].get('events', []))
        done_count = sum(1 for e in sections['schedule'].get('events', []) if e.get('status') == 'done')
        print(f'  ✓ Today schedule: {event_count} events ({done_count} completed)')
    except Exception as e:
        print(f'  ✗ Today schedule build failed: {e}')
        traceback.print_exc()
        sections['schedule'] = {'events': []}

    # ── Step 10: Build upcoming events ────────────────────────────────────
    # Uses Wikipedia sport events → hardcoded FULL_SCHEDULE → empty
    try:
        sections['upcoming'] = build_upcoming_events(wiki_schedule_events)
        total_upcoming = sum(len(d.get('events', [])) for d in sections['upcoming'].get('days', []))
        print(f'  ✓ Upcoming: {total_upcoming} events across {len(sections["upcoming"].get("days", []))} days')
    except Exception as e:
        print(f'  ✗ Upcoming build failed: {e}')
        traceback.print_exc()
        sections['upcoming'] = FALLBACK_UPCOMING

    # If upcoming still empty, use hardcoded
    if not sections['upcoming'].get('days'):
        print('  ↳ Using fallback upcoming events')
        sections['upcoming'] = FALLBACK_UPCOMING

    # ── Step 11: Athletes (hardcoded authoritative data) ──────────────────
    sections['athletes'] = FALLBACK_ATHLETES
    print('  ✓ Authoritative athlete data')

    # ── Step 12: Data Validation ──────────────────────────────────────────
    print('\n── Validation ──')
    warnings = validate_dashboard_data(
        sections['medals'], sections['schedule'], sections['usa'],
        sections['results'], sections.get('country_details', {})
    )
    if warnings:
        for w in warnings:
            print(f'  ⚠ {w}')
        print(f'  → {len(warnings)} validation warning(s) — review above')
    else:
        print('  ✓ All validation checks passed')

    # ── Generate and write HTML ───────────────────────────────────────────
    try:
        html = generate_html(
            sections['medals'], sections['schedule'], sections['usa'],
            sections['results'], sections['headlines'], sections['videos'],
            sections['athletes'], sections['upcoming'], sections.get('country_details')
        )
    except Exception as e:
        print(f'FATAL: generate_html crashed: {e}')
        traceback.print_exc()
        sys.exit(1)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    file_size = os.path.getsize('index.html')
    print(f'\nDashboard updated successfully ({file_size} bytes) at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')
    print('Data sources: Wikipedia (medals, winners, schedule), Google News RSS (headlines), YouTube API (videos)')
    print('Zero Perplexity/LLM dependencies.')


if __name__ == '__main__':
    main()
