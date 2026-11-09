"""Cached competition browsing and a venue-based Texas wins leaderboard."""
import json
import re
import threading
import time
from collections import Counter
import bce_analyze as core
from bce_store import PARSER_VERSION

_lock = threading.Lock()
_snapshot = {}


def refresh_locations(fetcher, progress=lambda: None):
    """Verify venues from BCE's public competition search, paced by the caller."""
    for cid, comp in fetcher.store.competition_metadata().items():
        saved = fetcher.store.get_external('bce', 'venue', str(cid))
        if saved and time.time() - saved['updated'] < 7 * 86400:
            continue
        progress()
        body = fetcher.get(core.BASE + 'php/searchCompsAndDancers.php', post_data={'query':comp['name']}, max_age=7*86400, cache_misses=False)
        try:
            matches = json.loads(body or 'null')
        except ValueError:
            continue
        if not isinstance(matches, list):
            continue
        match = next((m for m in matches if m.get('type') == 'comp' and str(m.get('compid')) == str(cid)), None)
        if match and match.get('venuestate'):
            fetcher.store.put_external('bce', 'venue', str(cid), {'state':match['venuestate'], 'city':match.get('venuecity',''),
                'source':core.BASE+'competition.php?cid='+str(cid)})


def catalog(store):
    venues = {key:store.get_external('bce','venue',key)['data'] for key in store.external_keys('bce','venue')}
    return sorted([{'cid':cid, **info, 'city':venues.get(str(cid),{}).get('city',''),
                    'state':venues.get(str(cid),{}).get('state','')} for cid,info in store.competition_metadata().items()],
                  key=lambda c:(c.get('date') or '',c['cid']), reverse=True)


def competition(store, cid, eid=None):
    saved = store.competition(cid)
    if not saved or not saved['data'].get('events'):
        raise ValueError('That competition has no cached results yet.')
    comp = saved['data']
    if eid is None:
        return {'cid':cid,'name':comp['name'],'date':comp.get('date'),'updated':saved['refreshed'],
                'events':[{'eid':e['eid'],'title':e['title']} for e in comp['events']]}
    if eid not in {e['eid'] for e in comp['events']}:
        raise ValueError('That event does not belong to this competition.')
    data = store.get_events([(cid,eid)]).get((cid,eid))
    if not data:
        raise ValueError('This event is awaiting a cache refresh. Check the official results.')
    results,n,title,info = data
    return {'title':title,'entries':n,'rounds':info.get('n_rounds'), 'url':core.RESULTS_URL+f'?cid={cid}&eid={eid}',
            'category':core.event_category(title,info.get('judged'),info.get('solo_share',0)),
            'rows':sorted([{'entry':entry,**result} for entry,result in results.items()],
                          key=lambda r:(r['place'] is None,r['place'] or 0,r['entry']))}


def texas_leaderboard(store, filters):
    # All visitors share a short-lived snapshot; no upstream requests on browsing.
    key = str(store.path)
    with _lock:
        cached = _snapshot.get(key)
        if not cached or time.time()-cached[0] > 60:
            comps = catalog(store)
            tx = {c['cid']:c for c in comps if str(c.get('state','')).upper() in ('TX','TEXAS')}
            rows = []
            with store.connect() as db:
                for cid in tx:
                    current_ids = {e['eid'] for e in store.competition(cid)['data']['events']}
                    for eid,payload in db.execute('SELECT eid,payload FROM events WHERE cid=? AND version=?',(cid,PARSER_VERSION)):
                        # Exclude stale orphan event rows left after an event-list correction.
                        if eid in current_ids:
                            rows.append((cid,eid,json.loads(payload)))
            cached = (time.time(),comps,tx,rows)
            _snapshot[key] = cached
    _,comps,tx,events = cached
    names = {}
    included = set()
    for cid,eid,(results,n,title,info) in events:
        if filters.get('year') and not (tx[cid].get('date') or '').startswith(filters['year']): continue
        category = core.event_category(title,info.get('judged'),info.get('solo_share',0))
        style = core.classify(title,core.STYLE_PATTERNS)
        level = core.classify(title,core.LEVEL_PATTERNS)
        if any(filters.get(k) and filters[k] != v for k,v in [('category',category),('style',style),('level',level)]): continue
        if filters.get('excludeUncontested') == 'true' and n == 1: continue
        if re.search(r'\b(team|formation)\b',title,re.I): continue
        included.add(cid)
        seen = set()
        for entry,result in results.items():
            people = core.split_people(entry)
            if any(re.search(r'\(#|^Entrant\s+\d',p) for p in people): continue
            if category == core.CAT_LEAD: people = people[:1] if len(people)==2 else []
            elif category == core.CAT_FOLLOW: people = people[1:] if len(people)==2 else []
            elif category == core.CAT_COUPLE and len(people) != 2: continue
            elif category == core.CAT_SOLO and len(people) != 1: continue
            for person in people:
                identity = core.norm(person)
                if identity in seen: continue
                seen.add(identity)
                row = names.setdefault(identity,{'name':person,'wins':0,'events':0,'comps':set()})
                row['events'] += 1; row['comps'].add(cid)
                if result.get('made_final') and result.get('place') == 1: row['wins'] += 1
    ordered = sorted(names.values(),key=lambda r:(-r['wins'],core.norm(r['name'])))
    previous,rank = None,0
    for i,row in enumerate(ordered,1):
        if row['wins'] != previous: rank=i; previous=row['wins']
        row['rank']=rank; row['competitions']=len(row.pop('comps'))
    search = core.norm(filters.get('q',''))
    matches = [r for r in ordered if not search or search in core.norm(r['name'])]
    return {'rows':matches[:500], 'matching_names':len(matches),'total_names':len(ordered),'updated':cached[0],
            'competitions':[tx[cid] for cid in sorted(included)],'verified_texas':len(tx),
            'unknown_venues':sum(not c['state'] for c in comps), 'years':sorted({(c.get('date') or '')[:4] for c in tx.values()}-{''},reverse=True)}
