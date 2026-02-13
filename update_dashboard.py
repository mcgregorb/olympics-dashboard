import os
import json
import requests
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get('PERPLEXITY_API_KEY')
API_URL = 'https://api.perplexity.ai/chat/completions'

def query_perplexity(prompt):
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': 'sonar',
        'messages': [
            {'role': 'system', 'content': 'You are a sports data assistant. Return ONLY valid JSON with no markdown formatting, no code blocks, no extra text.'},
            {'role': 'user', 'content': prompt}
        ],
        'max_tokens': 4000,
        'temperature': 0.1
    }
    response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content']
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]
    return json.loads(content)

def get_medal_data():
    prompt = """Get the current 2026 Milano Cortina Winter Olympics medal count for the top 10 countries. Return JSON:
    {"medals": [{"rank": 1, "country": "Country", "code": "XXX", "gold": 0, "silver": 0, "bronze": 0, "total": 0}], "day": 6, "events_complete": 44, "total_events": 116}"""
    return query_perplexity(prompt)

def get_schedule_data():
    prompt = """Get today's 2026 Winter Olympics schedule and results. Return JSON:
    {"today": [{"time_mst": "3:30 AM", "event": "Event name", "status": "done", "result": "Winner (COUNTRY)"}], "upcoming": [{"date": "Feb 13", "time_mst": "3:00 AM", "event": "Event name", "type": "Medal"}]}"""
    return query_perplexity(prompt)

def get_headlines():
    prompt = """Get the top 10 headlines from the 2026 Winter Olympics today. Return JSON:
    {"headlines": [{"title": "Headline text", "source": "Source Name", "url": "https://..."}]}"""
    return query_perplexity(prompt)

def build_html(medals, schedule, headlines):
    mst = timezone(timedelta(hours=-7))
    now = datetime.now(mst)
    timestamp = now.strftime('%b %d, %Y %I:%M %p MST')
    day = medals.get('day', '?')
    events_done = medals.get('events_complete', '?')
    total_events = medals.get('total_events', 116)

    medal_rows = ''
    for m in medals.get('medals', []):
        usa_class = ' class="usa"' if m.get('code','') == 'USA' else ''
        medal_rows += f'<tr{usa_class}><td>{m["rank"]}</td><td>{m["country"]}</td><td class="gold">{m["gold"]}</td><td class="silver">{m["silver"]}</td><td class="bronze">{m["bronze"]}</td><td>{m["total"]}</td></tr>\n'

    schedule_rows = ''
    for s in schedule.get('today', []):
        badge = 'done' if s.get('status') == 'done' else ('live' if s.get('status') == 'live' else 'upcoming')
        label = 'Final' if badge == 'done' else ('LIVE' if badge == 'live' else 'Upcoming')
        result = f'<span class="event-result">{s.get("result","")}</span>' if s.get('result') else ''
        schedule_rows += f'<div class="event-row"><span class="event-time">{s["time_mst"]}</span><span class="event-name">{s["event"]}</span><span class="badge {badge}">{label}</span>{result}</div>\n'

    upcoming_rows = ''
    for u in schedule.get('upcoming', []):
        upcoming_rows += f'<div class="event-row"><span class="event-time">{u["time_mst"]}</span><span class="event-name">{u["event"]}</span><span class="badge upcoming">{u.get("type","Medal")}</span></div>\n'

    headline_rows = ''
    for i, h in enumerate(headlines.get('headlines', []), 1):
        url = h.get('url', '#')
        src = h.get('source', '')
        headline_rows += f'<div class="headline-item"><span class="headline-num">{i}.</span><a href="{url}" target="_blank">{h["title"]}</a><span class="headline-src">{src}</span></div>\n'

    with open('index.html', 'r') as f:
        html = f.read()

    # Update timestamp
    import re
    html = re.sub(r'Data snapshot: [^<]+', f'Data snapshot: {timestamp}', html)
    html = re.sub(r'Day \d+ Final Results', f'Day {day} Final Results', html)
    html = re.sub(r'\d+ of \d+ Medal Events Complete', f'{events_done} of {total_events} Medal Events Complete', html)

    # Update medal table
    html = re.sub(r'<tbody>[\s\S]*?</tbody>(\s*</table>\s*</div>\s*<div class="card">\s*<h2>[^<]*USA)', lambda m: f'<tbody>\n{medal_rows}</tbody>{m.group(1)}', html, count=1)

    # Update headlines
    old_headlines = re.search(r'(Top 10 Olympic Headlines</h2>\s*)(.*?)(\s*</div>\s*</div>\s*<div class="section-divider">)', html, re.DOTALL)
    if old_headlines:
        html = html[:old_headlines.start(2)] + headline_rows + html[old_headlines.end(2):]

    with open('index.html', 'w') as f:
        f.write(html)
    print(f'Dashboard updated at {timestamp}')

def main():
    if not API_KEY:
        print('Error: PERPLEXITY_API_KEY not set')
        return
    try:
        medals = get_medal_data()
        print('Got medal data')
    except Exception as e:
        print(f'Medal data error: {e}')
        medals = {'medals': [], 'day': '?', 'events_complete': '?'}
    try:
        schedule = get_schedule_data()
        print('Got schedule data')
    except Exception as e:
        print(f'Schedule error: {e}')
        schedule = {'today': [], 'upcoming': []}
    try:
        headlines = get_headlines()
        print('Got headlines')
    except Exception as e:
        print(f'Headlines error: {e}')
        headlines = {'headlines': []}
    build_html(medals, schedule, headlines)

if __name__ == '__main__':
    main()
