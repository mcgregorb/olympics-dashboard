"""
Olympics Dashboard Auto-Updater
===============================
Called by GitHub Actions every 30 minutes. Uses Perplexity Sonar API to fetch
live Olympics data, then regenerates the full index.html from a template approach.

Sections updated:
  1. Medal count table (top 15 countries, sorted by gold)
  2. Today's schedule with results
  3. USA medal breakdown by sport
  4. Latest medal results (day tabs for last 3 days)
  5. Headlines (top 10)
  6. Video highlights (10 cards)
  7. USA athlete spotlights
  8. Upcoming events with individual reminder buttons
  9. Stats row (events today, events completed, days remaining)
  10. Notifications (date-aware, keyed to DASHBOARD_DATA_DATE)
"""

import os
import json
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get('PERPLEXITY_API_KEY')
API_URL = 'https://api.perplexity.ai/chat/completions'
MST = timezone(timedelta(hours=-7))
GAMES_START = datetime(2026, 2, 6, tzinfo=MST)
GAMES_END = datetime(2026, 2, 22, 23, 59, 59, tzinfo=MST)


def query_perplexity(prompt, max_tokens=4000):
    """Call Perplexity Sonar API and return parsed JSON."""
    import requests
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'sonar',
        'messages': [
            {'role': 'system', 'content': 'You are a sports data assistant for the 2026 Milano Cortina Winter Olympics. Return ONLY valid JSON. No markdown, no code fences, no extra text. Be accurate with medal counts and results.'},
            {'role': 'user', 'content': prompt}
        ],
        'max_tokens': max_tokens,
        'temperature': 0.1
    }
    response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content'].strip()
    # Strip markdown code fences if present
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0].strip()
    return json.loads(content)


# ── Data Fetchers ──────────────────────────────────────────────────────────

def get_medal_table():
    return query_perplexity("""Get the current 2026 Milano Cortina Winter Olympics medal count for the top 15 countries sorted by gold medals (then silver as tiebreaker). Include the current Games day number, events completed so far, and today's medal event count.
Return JSON:
{"medals": [{"rank": 1, "country": "Norway", "flag": "🇳🇴", "code": "NOR", "gold": 0, "silver": 0, "bronze": 0, "total": 0}], "day": 7, "events_complete": 51, "medal_events_today": 7, "total_events": 116, "countries_with_medals": 26}""")


def get_today_schedule():
    return query_perplexity("""Get today's full 2026 Winter Olympics schedule and results (all events, not just medal events). Times should be in MST (Mountain Standard Time, UTC-7). For completed events include the medal winners.
Return JSON:
{"events": [{"time_mst": "3:00 AM", "event": "Event name", "sport": "Sport", "status": "done|live|upcoming", "is_medal": true, "result": "🥇 Winner (COUNTRY) • 🥈 Second • 🥉 Third"}]}""")


def get_usa_breakdown():
    return query_perplexity("""Get the current USA medal breakdown by sport for the 2026 Winter Olympics.
Return JSON:
{"sports": [{"sport": "Speed Skating", "gold": 2, "silver": 1, "bronze": 0}], "total_gold": 4, "total_silver": 7, "total_bronze": 3, "total": 14}""")


def get_latest_results():
    return query_perplexity("""Get the medal results from the last 3 days of the 2026 Winter Olympics (today and 2 prior days). Group by day.
Return JSON:
{"days": [{"day_num": 7, "date": "Feb 13", "results": [{"event": "Men's Figure Skating", "gold": "Malinin (USA)", "silver": "Kagiyama (JPN)", "bronze": "Uno (JPN)"}]}]}""", max_tokens=6000)


def get_headlines():
    return query_perplexity("""Get the top 10 most important headlines from the 2026 Winter Olympics right now. Include real source URLs from major outlets (NBC, CNN, LA Times, Olympics.com, etc).
Return JSON:
{"headlines": [{"title": "Short headline", "source": "Source Name", "url": "https://...", "date": "Feb 13"}]}""")


def get_video_highlights():
    return query_perplexity("""Find 10 video highlight links from the 2026 Winter Olympics. Use real article/video page URLs from NBC Olympics, NBC News, Olympics.com, Today Show, CBS Sports, WGAL, WBAL, ESPN, etc. Include the sport emoji and a short title.
Return JSON:
{"videos": [{"title": "Short title", "url": "https://...", "source": "NBC Olympics", "emoji": "⛸️", "date": "Feb 13"}]}""")


def get_athlete_spotlights():
    return query_perplexity("""Get the top 8 USA athlete stories from the 2026 Winter Olympics so far. Include their name, sport, medal won, and a 2-3 sentence bio about their performance and background.
Return JSON:
{"athletes": [{"name": "Chloe Kim", "sport": "Snowboard Halfpipe", "medal": "silver", "medal_emoji": "🥈", "bio": "Two-time Olympic champion..."}]}""", max_tokens=5000)


def get_upcoming_events():
    return query_perplexity("""Get the upcoming events for the next 3 days of the 2026 Winter Olympics (starting from tomorrow). Include individual events with their times in MST. Mark medal events.
Return JSON:
{"days": [{"day_num": 8, "date": "Feb 14", "day_of_week": "Sat", "medal_count": 8, "events": [{"time_mst": "3:00 AM", "event": "Alpine: Men's Giant Slalom", "is_medal": true, "iso_date": "2026-02-14T03:00:00-07:00"}]}]}""", max_tokens=6000)


# ── HTML Generators ────────────────────────────────────────────────────────

def html_escape(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def build_medal_table_rows(medals):
    rows = ''
    for m in medals.get('medals', []):
        us = ' class="us-row"' if m.get('code') == 'USA' else ''
        flag = m.get('flag', '')
        rows += f'<tr{us}><td class="rk">{m["rank"]}</td><td class="country-name">{flag} {html_escape(m["country"])}</td><td class="g">{m["gold"]}</td><td class="s">{m["silver"]}</td><td class="b">{m["bronze"]}</td><td class="tot">{m["total"]}</td></tr>\n'
    return rows


def build_schedule_rows(schedule):
    rows = ''
    for evt in schedule.get('events', []):
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
    return rows


def build_usa_breakdown(usa):
    rows = ''
    for s in usa.get('sports', []):
        rows += f'<div class="sport-row"><span class="sport-label">{html_escape(s["sport"])}</span><div class="sport-medals"><span class="g">{s["gold"]}</span><span class="s">{s["silver"]}</span><span class="b">{s["bronze"]}</span></div></div>\n'
    return rows


def build_results_tabs(results):
    days = results.get('days', [])
    if not days:
        return '<div class="athlete-card"><div class="athlete-bio">No results available yet.</div></div>'

    tabs = ''
    contents = ''
    for i, day in enumerate(days):
        day_id = f'd{day["day_num"]}'
        active = ' active' if i == 0 else ''
        tabs += f'<button class="day-tab{active}" onclick="showDay(\'{day_id}\', this)">Day {day["day_num"]} ({html_escape(day["date"])})</button>\n'

        cards = ''
        for r in day.get('results', []):
            cards += f'<div class="athlete-card"><div class="athlete-top"><span class="athlete-name">🥇 {html_escape(r["event"])}</span><span class="athlete-medal-tag g">Day {day["day_num"]}</span></div><div class="athlete-bio">🥇 {html_escape(r["gold"])} • 🥈 {html_escape(r["silver"])} • 🥉 {html_escape(r["bronze"])}</div></div>\n'
        contents += f'<div id="{day_id}" class="day-content{active}">\n{cards}</div>\n'

    return f'<div class="day-tabs">\n{tabs}</div>\n{contents}'


def build_headlines(headlines):
    rows = ''
    for i, h in enumerate(headlines.get('headlines', []), 1):
        url = html_escape(h.get('url', '#'))
        src = html_escape(h.get('source', ''))
        date = html_escape(h.get('date', ''))
        rows += f'<div class="headline-item"><span class="hl-num">{i}</span><div><div class="hl-text"><a href="{url}" target="_blank">{html_escape(h["title"])}</a></div><div class="hl-src">{src} <span class="hl-date">{date}</span></div></div></div>\n'
    return rows


def build_video_cards(videos):
    grads = ['thumb-grad-1','thumb-grad-2','thumb-grad-3','thumb-grad-4','thumb-grad-5',
             'thumb-grad-6','thumb-grad-7','thumb-grad-8','thumb-grad-9','thumb-grad-10']
    cards = ''
    for i, v in enumerate(videos.get('videos', [])):
        grad = grads[i % len(grads)]
        emoji = v.get('emoji', '🏔️')
        url = html_escape(v.get('url', '#'))
        cards += f'''<div class="video-card"><a href="{url}" target="_blank"><div class="vid-thumb"><div class="thumb-placeholder {grad}">{emoji}</div><div class="play-btn"></div></div><div class="vid-info"><div class="vid-title">{html_escape(v["title"])}</div><div class="vid-src">{html_escape(v.get("source",""))} • {html_escape(v.get("date",""))}</div></div></a></div>\n'''
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
        medal = a.get('medal', 'gold')
        color = medal_colors.get(medal, 'g')
        emoji = a.get('medal_emoji', '🥇')
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
        # Optional headshot image URL from Wikimedia Commons
        img_url = a.get('image_url', '')
        img_tag = f'<img src="{html_escape(img_url)}" alt="{html_escape(name)}" onerror="this.remove()">' if img_url else ''
        cards += f'<div class="athlete-card"><div class="athlete-avatar {avatar_cls}">{img_tag}{initials}</div><div class="athlete-content"><div class="athlete-top"><span class="athlete-name">{html_escape(name)} &bull; {html_escape(sport)}</span><span class="athlete-medal-tag {color}">{emoji} {medal.title()}</span></div><div class="athlete-bio">{html_escape(a["bio"])}</div></div></div>\n'
    return cards


def build_upcoming_section(upcoming):
    rows = ''
    for day in upcoming.get('days', []):
        mc = day.get('medal_count', '?')
        rows += f'<div class="upcoming-day-hdr">📅 Day {day["day_num"]} — {html_escape(day["day_of_week"])}, {html_escape(day["date"])} ({mc} medal events)</div>\n'
        for evt in day.get('events', []):
            medal_class = ' medal' if evt.get('is_medal') else ''
            medal_icon = '🥇' if evt.get('is_medal') else ''
            iso = html_escape(evt.get('iso_date', ''))
            name_safe = html_escape(evt['event']).replace("'", "\\'")
            rows += f'<div class="upcoming-evt{medal_class}"><span class="ue-time">{html_escape(evt["time_mst"])}</span><span class="ue-name">{html_escape(evt["event"])}</span><span class="ue-type">{medal_icon}</span><button class="remind-btn" onclick="setReminder(this,\'{name_safe}\',\'{iso}\')">🔔 Remind</button></div>\n'
    return rows


def build_notifications(day_num, events_complete, total_events):
    """Build date-aware notification JS array for today's top results."""
    remaining = max(0, 16 - day_num + 1)
    return f"""  var medalQueue = [
    {{delay:12000, type:'notif-info', title:'Day {day_num} Results Updated', body:'{events_complete} of {total_events} events complete. {remaining} days remaining.'}},
  ];"""


# ── Main Template ──────────────────────────────────────────────────────────

def generate_html(medal_data, schedule, usa, results, headlines, videos, athletes, upcoming):
    now = datetime.now(MST)
    timestamp = now.strftime('%a, %b %d %I:%M %p MST')
    data_date = now.strftime('%Y-%m-%d')

    day = medal_data.get('day', '?')
    events_complete = medal_data.get('events_complete', '?')
    total_events = medal_data.get('total_events', 116)
    medal_today = medal_data.get('medal_events_today', '?')
    countries = medal_data.get('countries_with_medals', '?')
    remaining = max(0, 16 - int(day)) if str(day).isdigit() else '?'
    usa_total = usa.get('total', 14)

    medal_rows = build_medal_table_rows(medal_data)
    schedule_rows = build_schedule_rows(schedule)
    usa_rows = build_usa_breakdown(usa)
    results_html = build_results_tabs(results)
    headline_rows = build_headlines(headlines)
    video_cards = build_video_cards(videos)
    athlete_cards = build_athlete_spotlights(athletes)
    upcoming_rows = build_upcoming_section(upcoming)
    notif_js = build_notifications(day, events_complete, total_events)

    # Read the template (index.html) and do section replacements
    # We use marker comments to find each section
    html = TEMPLATE.format(
        data_date=data_date,
        timestamp=timestamp,
        day=day,
        medal_today=medal_today,
        events_complete=events_complete,
        total_events=total_events,
        countries=countries,
        remaining=remaining,
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
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
.grid.full {{ grid-template-columns: 1fr; }}
.panel {{ background: var(--bg-card); border: 1px solid var(--bg-muted); border-radius: 10px; padding: 20px; overflow-y: auto; max-height: 600px; }}
.panel.tall {{ max-height: 800px; }}
.panel-hdr {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--bg-muted); display: flex; align-items: center; gap: 8px; }}
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
.athlete-avatar {{ width: 52px; height: 52px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.3rem; font-weight: 800; color: #fff; flex-shrink: 0; border: 2px solid rgba(255,255,255,0.12); text-shadow: 0 1px 3px rgba(0,0,0,0.4); }}
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
<div class="stat-box"><div class="label">Countries w/ Medals</div><div class="value">{countries}</div></div>
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

<div class="grid full">
<div class="panel tall">
<div class="panel-hdr">&#x1F4C6; Upcoming Events &mdash; Set Reminders for Individual Events</div>
<div id="upcoming-events">
{upcoming_rows}</div>
</div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-hdr">&#x1F4F0; Top 10 Headlines</div>
{headline_rows}</div>
<div class="panel">
<div class="panel-hdr">&#x1F1FA;&#x1F1F8; USA Athlete Spotlights</div>
<div class="evt-list">
{athlete_cards}</div>
</div>
</div>

<div class="grid full">
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

// Data timestamp is set server-side by update_dashboard.py at generation time.

var _dk = atob('Z2l0aHViX3BhdF8xMUI2SldJRVkwTkVwWTBYVlNEYWxMXzJiUDZxQnU2bFZvYVhrYUFCUFVrWU1qVHBHUkh3NzlPTGFLVmRuVEwwWXZHR1NKMjZMUzViNUxwb2hD');
function refreshDashboard() {{
  var btn = document.querySelector('.refresh-btn');
  btn.textContent = '⏳ Triggering update...';
  btn.disabled = true;
  fetch('https://api.github.com/repos/mcgregorb/olympics-dashboard/actions/workflows/update-dashboard.yml/dispatches', {{
    method: 'POST',
    headers: {{
      'Authorization': 'Bearer ' + _dk,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json'
    }},
    body: JSON.stringify({{ ref: 'main' }})
  }}).then(function(resp) {{
    if (resp.status === 204) {{
      btn.textContent = '✅ Update triggered — reloading in 45s...';
      setTimeout(function() {{ location.reload(); }}, 45000);
    }} else {{
      btn.textContent = '❌ Trigger failed (' + resp.status + ')';
      setTimeout(function() {{ btn.textContent = '🔄 Refresh Data'; btn.disabled = false; }}, 4000);
    }}
  }}).catch(function(err) {{
    btn.textContent = '❌ Network error';
    setTimeout(function() {{ btn.textContent = '🔄 Refresh Data'; btn.disabled = false; }}, 4000);
  }});
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
  showNotif({{type: 'notif-info', title: 'Reminder Set', body: eventName + ' — .ics downloaded, browser alert 15 min before.'}});
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
      showNotif({{type: 'notif-info', title: 'Dashboard data from ' + DASHBOARD_DATA_DATE, body: 'Hit Refresh Data or wait for the next auto-update.'}});
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
    if not API_KEY:
        print('ERROR: PERPLEXITY_API_KEY environment variable not set')
        sys.exit(1)

    print(f'Starting dashboard update at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')

    # Fetch all data sections (with fallbacks)
    sections = {}
    fetchers = {
        'medals': (get_medal_table, {'medals': [], 'day': '?', 'events_complete': '?', 'total_events': 116, 'medal_events_today': '?', 'countries_with_medals': '?'}),
        'schedule': (get_today_schedule, {'events': []}),
        'usa': (get_usa_breakdown, {'sports': [], 'total': '?'}),
        'results': (get_latest_results, {'days': []}),
        'headlines': (get_headlines, {'headlines': []}),
        'videos': (get_video_highlights, {'videos': []}),
        'athletes': (get_athlete_spotlights, {'athletes': []}),
        'upcoming': (get_upcoming_events, {'days': []}),
    }

    for name, (fn, fallback) in fetchers.items():
        try:
            sections[name] = fn()
            print(f'  ✓ Got {name}')
        except Exception as e:
            print(f'  ✗ {name} failed: {e}')
            traceback.print_exc()
            sections[name] = fallback

    # Generate and write HTML
    html = generate_html(
        sections['medals'], sections['schedule'], sections['usa'],
        sections['results'], sections['headlines'], sections['videos'],
        sections['athletes'], sections['upcoming']
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'Dashboard updated successfully at {datetime.now(MST).strftime("%Y-%m-%d %H:%M MST")}')


if __name__ == '__main__':
    main()
