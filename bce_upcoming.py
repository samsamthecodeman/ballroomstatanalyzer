"""Public BCE heat sheets, joined to a completed dancer's existing history."""
import re
from collections import Counter
from datetime import date, datetime, timezone
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
import bce_analyze as core

TTL = 15 * 60


def valid_page(parser, body):
    try:
        parser(body)
        return True
    except ValueError:
        return False


def competition_id(value):
    value = str(value).strip()
    if value.isdigit():
        cid = int(value)
    else:
        url = urlparse(value)
        if (url.scheme not in ('http', 'https') or url.hostname not in ('ballroomcompexpress.com', 'www.ballroomcompexpress.com')
                or url.username or url.password or url.port or url.path not in ('/heatsheets.php', '/viewschedule.php')):
            raise ValueError('Paste a public Ballroom Comp Express heat-sheet or schedule link, or its competition ID.')
        ids = parse_qs(url.query).get('cid', [])
        if len(ids) != 1 or not ids[0].isdigit():
            raise ValueError('The BCE link must contain one numeric cid.')
        cid = int(ids[0])
    if not 1 <= cid <= 999999:
        raise ValueError('Invalid BCE competition ID.')
    return cid


def event_heading(text):
    match = re.search(r'Event\s+(\d+):\s*(.+)', text, re.I)
    if not match:
        return None
    title = re.sub(r'\s*\(\d+\s+(?:couples?|entries|dancers?)\)\s*$', '', match[2], flags=re.I)
    round_match = re.search(r'\s+(Final|Semi[- ]?final|Quarter[- ]?final|(?:1/\d+|\d+th)\s*final|Round\s+\d+)\s*$', title, re.I)
    return {'number': int(match[1]), 'title': title[:round_match.start()].strip() if round_match else title,
            'round': round_match[1] if round_match else 'Round not specified'}


def published_time(node):
    changed = node.select_one('.changedtime')
    if changed:
        return core.clean(changed.get_text(' ', strip=True))
    match = re.search(r'\[([^]]+)\]', node.get_text(' ', strip=True))
    return core.clean(match[1]) if match else 'Time not published'


def parse_personal(body):
    soup = BeautifulSoup(body, 'html.parser')
    if not soup.select_one('.page h2'):
        raise ValueError('BCE has not published a personal heat sheet for this dancer.')
    rows = []
    for node in soup.select('.page > div'):
        if 'callback-round' in node.get('class', []):
            continue
        text = core.clean(node.get_text(' ', strip=True))
        event = event_heading(text)
        if not event:
            continue
        partner = re.search(r'\((Leading|Following)\s+(.+?)\)\s*Event', text, re.I)
        session = node.find_previous('h3')
        rows.append({**event, 'time': published_time(node), 'session': core.clean(session.get_text(' ', strip=True)) if session else '',
                     'role': partner[1] if partner else 'Unspecified', 'partner': partner[2] if partner else ''})
    if not rows:
        raise ValueError('No entered rounds were published in this personal heat sheet. Try again after the organizer publishes it.')
    return rows


def parse_schedule(body):
    soup = BeautifulSoup(body, 'html.parser')
    heading = soup.find('h1')
    if not heading or 'schedule for' not in core.norm(heading.get_text()):
        raise ValueError('BCE did not return a public competition schedule.')
    rounds = []
    for node in soup.select('.round-entry'):
        trigger = node.select_one('.trigger')
        event = event_heading(trigger.get_text(' ', strip=True)) if trigger else None
        if not event:
            continue
        entries = []
        for entry in node.select('.inner > div'):
            copy = BeautifulSoup(str(entry), 'html.parser')
            for org in copy.select('i'):
                org.decompose()
            text = re.sub(r'\(\s*\)', '', copy.get_text(' ', strip=True))
            match = re.match(r'\s*(\d+)\s*[-–]\s*(.+)', text)
            if match:
                label = core.clean(match[2])
                entries.append({'bib': match[1], 'entry': label, 'people': core.split_people(label)})
        rounds.append({**event, 'time': published_time(trigger), 'entries': entries})
    if not rounds:
        raise ValueError('BCE has not published event entrants yet. Try again after heat lists are published.')
    sessions = [core.clean(h.get_text(' ', strip=True)) for h in soup.find_all('h3') if re.match(r'Session\s+\d+', h.get_text(), re.I)]
    return {'competition': re.sub(r'^Schedule for\s+', '', heading.get_text(' ', strip=True), flags=re.I), 'sessions': sessions, 'rounds': rounds}


def history_stats(history, names, *, couple=False):
    targets = {core.norm(name) for name in names}
    counts = dict(meetings=0, wins=0, losses=0, ties=0, unplaced=0, together=0, ambiguous_events=0)
    matches = []
    for event in history:
        own = {core.norm(p) for p in core.split_people(event['entry'])}
        if (own == targets if couple else bool(own & targets)):
            counts['together'] += 1
        opponents = []
        for other in event.get('field', []):
            people = {core.norm(p) for p in other.get('people', core.split_people(other['entry']))}
            if other['entry'] == event['entry'] or not (people == targets if couple else bool(people & targets)):
                continue
            opponents.append(other)
        if len(opponents) > 1 or (not couple and own & targets and opponents):
            counts['ambiguous_events'] += 1
            continue
        for other in opponents:
            a, b = event.get('place'), other.get('place')
            outcome = 'unplaced' if a is None or b is None else 'wins' if a < b else 'losses' if a > b else 'ties'
            counts['meetings'] += 1
            counts[outcome] += 1
            matches.append({'date': event.get('date', ''), 'competition': event['comp'], 'event': event['event'],
                            'style': event.get('style', ''), 'dances': event.get('dances', []), 'level': event.get('level', ''),
                            'category': event.get('category', ''), 'your_partner': event.get('partner', ''), 'opposing_entry': other['entry'],
                            'your_place': a, 'their_place': b, 'outcome': outcome, 'url': event['url']})
    matches.sort(key=lambda row: row['date'] or '', reverse=True)
    return {**counts, 'last_met': matches[0]['date'] if matches else None, 'matches': matches[:10]}


def analyze(value, result, fetcher):
    cid = competition_id(value)
    options = dict(max_age=TTL, cache_misses=False)
    roster_body = fetcher.get(core.BASE + f'heatsheets.php?cid={cid}',
                              validate=lambda body: bool(BeautifulSoup(body, 'html.parser').select('#dancer option[value]')), **options)
    roster_soup = BeautifulSoup(roster_body or '', 'html.parser')
    roster = [{'id': int(o['value']), 'name': core.clean(o.get_text())} for o in roster_soup.select('#dancer option[value]') if o['value'].isdigit()]
    if not roster:
        raise ValueError('No public dancer list is available for this competition yet.')
    aid = result.get('aid')
    candidates = [p for p in roster if p['id'] == aid] if aid else [p for p in roster if core.norm(p['name']) == core.norm(result['name'])]
    if len(candidates) != 1:
        raise ValueError('Your analyzed dancer does not match one unique registered dancer. Analyze your BCE dancer ID, then try this heat sheet again.')
    dancer = candidates[0]
    personal_body = fetcher.get(core.BASE + 'heatsheet_dancer.php', post_data={'compid': cid, 'acctid': dancer['id']},
                                validate=lambda body: valid_page(parse_personal, body), **options)
    personal = parse_personal(personal_body or '')
    schedule_body = fetcher.get(core.BASE + f'viewschedule.php?cid={cid}', validate=lambda body: valid_page(parse_schedule, body), **options)
    schedule = parse_schedule(schedule_body or '')
    # Exclude this competition even when it already has provisional results.
    history = [event for event in result['events'] if not ((event.get('source') or 'bce') == 'bce' and str(event['cid']) == str(cid))
               and (not event.get('date') or event['date'] <= date.today().isoformat())]
    name_counts = Counter(core.norm(p['name']) for p in roster)
    events, warnings = [], []
    stats_cache = {}
    def cached_stats(names, couple=False):
        key = (couple, tuple(sorted(core.norm(name) for name in names)))
        if key not in stats_cache:
            stats_cache[key] = history_stats(history, names, couple=couple)
        return stats_cache[key]
    for entry in personal:
        rounds = [r for r in schedule['rounds'] if r['number'] == entry['number'] and core.norm(r['title']) == core.norm(entry['title']) and core.norm(r['round']) == core.norm(entry['round'])]
        if len(rounds) != 1:
            warnings.append(f"Event {entry['number']}: the personal heat sheet could not be matched to one published round.")
            events.append({**entry, 'opponents': [], 'entries': None})
            continue
        field = rounds[0]['entries']
        own = [e for e in field if any(core.norm(p) == core.norm(dancer['name']) for p in e['people'])
               and (not entry['partner'] or any(core.norm(p) == core.norm(entry['partner']) for p in e['people']))]
        if len(own) != 1:
            warnings.append(f"Event {entry['number']}: your partnership could not be identified uniquely in the published entrants.")
            events.append({**entry, 'opponents': [], 'entries': len(field)})
            continue
        opponents = []
        for opponent in field:
            if opponent is own[0]:
                continue
            people = []
            for name in opponent['people']:
                ambiguous = name_counts[core.norm(name)] > 1
                people.append({'name': name, 'ambiguous': ambiguous,
                               'history': None if ambiguous else cached_stats([name])})
            opponents.append({**opponent, 'people_history': people, 'partnership_history': cached_stats(opponent['people'], couple=True)})
        style = core.classify(entry['title'], core.STYLE_PATTERNS)
        events.append({**entry, 'time': rounds[0]['time'], 'entries': len(field), 'opponents': opponents,
                       'category': core.event_category(entry['title']), 'style': style,
                       'level': core.classify(entry['title'], core.LEVEL_PATTERNS),
                       'dances': core.event_dances(entry['title'], style)})
    for session in schedule['sessions']:
        match = re.search(r'\((\d{2}/\d{2}/\d{4})', session)
        if match and datetime.strptime(match[1], '%m/%d/%Y').date() < date.today():
            warnings.append('BCE lists a session date in the past: ' + session + '. Verify the current date and times with the organizer.')
    def order(event):
        session = re.search(r'Session\s+(\d+)', event['session'])
        try:
            time = datetime.strptime(event['time'], '%I:%M %p').time()
            minute = time.hour * 60 + time.minute
        except ValueError:
            minute = 9999
        return (int(session[1]) if session else 999, minute, event['number'])
    events.sort(key=order)
    return {'cid': cid, 'competition': schedule['competition'], 'dancer': dancer['name'], 'aid': dancer['id'],
            'sessions': schedule['sessions'], 'events': events, 'warnings': list(dict.fromkeys(warnings)),
            'checked_at': datetime.now(timezone.utc).isoformat(), 'url': core.BASE + f'heatsheets.php?cid={cid}',
            'schedule_url': core.BASE + f'viewschedule.php?cid={cid}', 'cache_minutes': TTL // 60,
            'history_events': len(history)}
