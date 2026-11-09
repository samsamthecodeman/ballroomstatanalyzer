"""Unified cached dancer/event browsing and venue-based wins leaderboards."""
import json
import re
import threading
import time
import bce_analyze as core

_lock = threading.Lock()
_snapshot = {}
_catalog_cache = {}


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


US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
# Exact event-year venue references; unknown O2CM venues remain excluded.
O2_VENUES = {
    'aac18': {'city':'Dallas','state':'TX','source':'https://ballroom.rice.edu/events-competitions.html'},
    'mit26': {'city':'Cambridge','state':'MA','source':'https://calendar.mit.edu/event/mit-open-ballroom-dance-competition-7990'},
}


def checked_source(source):
    if source not in ('bce','o2cm','all'): raise ValueError('Choose Unified data, BCE, or O2CM.')
    return source


def flat_catalog(store, source='all'):
    checked_source(source)
    cache_key=(str(store.path),source)
    cached=_catalog_cache.get(cache_key)
    if cached and time.time()-cached[0]<60:return cached[1]
    comps=[]
    if source in ('bce','all'):
        for cid,info in store.competition_metadata().items():
            venue=store.get_external('bce','venue',str(cid))
            comps.append({'cid':cid,**info,'provider':'bce',**(venue['data'] if venue else {})})
    if source in ('o2cm','all'):
        for code in store.external_keys('o2cm','competition'):
            saved=store.get_external('o2cm','competition',code)
            data=saved['data']
            if not data.get('events'): continue
            venue=store.get_external('o2cm','venue',code)
            comps.append({'cid':'o2cm:'+code,'name':data['meta']['name'],'date':data['meta'].get('date'),
                          'provider':'o2cm',**(venue['data'] if venue else O2_VENUES.get(code,{}))})
    for comp in comps:
        comp.setdefault('state','');comp.setdefault('city','')
    _catalog_cache[cache_key]=(time.time(),comps)
    return comps


def catalog(store, source='all'):
    comps=flat_catalog(store,source)
    grouped={}
    for comp in comps:
        key=(comp.get('date'),core.norm(comp['name']))
        grouped.setdefault(key,[]).append(comp)
    out=[]
    for (day,_),group in grouped.items():
        # Merge only a unique cross-provider pair with the same title and date.
        venue_states={c['state'].upper() for c in group if c['state']}
        groups=[group] if day and len(group)==2 and len({c['provider'] for c in group})==2 and len(venue_states)<=1 else [[c] for c in group]
        for members in groups:
            out.append({**members[0],'members':[c['cid'] for c in members],
                        'source_label':'Unified' if len(members)>1 else 'BCE' if members[0]['provider']=='bce' else 'O2CM'})
    return sorted(out,key=lambda c:(c.get('date') or '',str(c['cid'])),reverse=True)


def event_rows(store,cid):
    import bce_o2cm as o2
    if str(cid).startswith('o2cm:'):
        code=str(cid)[5:]
        if not o2.CODE.fullmatch(code): raise ValueError('Invalid O2CM competition code.')
        saved=store.get_external('o2cm','competition',code)
        if not saved: raise ValueError('That O2CM competition is not cached yet.')
        for heat,event in saved['data']['events'].items():
            title=event['title']; category=core.event_category(title)
            if category==core.CAT_COUPLE and re.search(r'mixed|proficiency',title,re.I): category='Unclassified'
            yield {'eid':'o2cm:'+heat,'title':title,'category':category,'classified_title':o2.expanded_title(title),
                   'entries':len(event['entries']),'rounds':event['rounds'],'source':'o2cm',
                   'url':o2.BASE+'scoresheet3.asp?event='+code+'&heatid='+heat,
                   'rows':[{'entry':r['entry'],'people':r['people'],'place':r['place'],'made_final':r['made_final'],
                            'rounds':max(1,event['rounds']-r['group'])} for r in event['entries']]}
    else:
        try: cid=int(str(cid).removeprefix('bce:'))
        except ValueError: raise ValueError('Invalid competition ID.')
        saved=store.competition(cid)
        if not saved or not saved['data'].get('events'): raise ValueError('That competition has no cached results yet.')
        events=saved['data']['events']; indexed=store.get_events((cid,e['eid']) for e in events)
        for event in events:
            data=indexed.get((cid,event['eid']))
            if not data: continue
            results,n,title,info=data;title=title or event['title']
            yield {'eid':event['eid'],'title':title,'classified_title':title,'entries':n,'rounds':info.get('n_rounds'),
                   'category':core.event_category(title,info.get('judged'),info.get('solo_share',0)),'source':'bce',
                   'url':core.RESULTS_URL+f'?cid={cid}&eid='+str(event['eid']),
                   'rows':[{'entry':entry,'people':core.split_people(entry),**result} for entry,result in results.items()]}


def competition(store,cid,eid=None,source='all',dancer=''):
    matches=[c for c in catalog(store,source) if str(c['cid'])==str(cid) or str(cid) in map(str,c['members'])]
    if len(matches)!=1: raise ValueError('Choose a cached competition from the selected data source.')
    comp=matches[0]
    events=[{**event,'competition':comp['name'],'date':comp.get('date','')} for member in comp['members'] for event in event_rows(store,member)]
    if dancer:
        target=core.norm(dancer)
        rows=[];seen={};duplicates=0
        for event in events:
            for result in event['rows']:
                if target not in {core.norm(p) for p in result['people']}:continue
                key=(core.norm(event['title']),core.norm(result['entry']),result['place'],event['entries'],result['made_final'])
                if key in seen and seen[key]!=event['source']:duplicates+=1;continue
                seen[key]=event['source']
                rows.append({**result,'event':event['title'],'category':event['category'],'entries':event['entries'],
                             'source':event['source'],'url':event['url'],
                             'partner':' & '.join(p for p in result['people'] if core.norm(p)!=target)})
        return {'name':comp['name'],'dancer':dancer,'rows':rows,'deduplicated':duplicates,
                'ambiguous':len(rows)!=len({(r['source'],r['url']) for r in rows})}
    if eid is not None:
        selected=[event for event in events if str(event['eid'])==str(eid)]
        if len(selected)!=1: raise ValueError('That event does not belong to this competition or is not cached yet.')
        event=selected[0]
        return {**event,'rows':sorted(event['rows'],key=lambda r:(r['place'] is None,r['place'] or 0,r['entry']))}
    stamps=[store.get_external('o2cm','competition',str(member)[5:])['updated'] if str(member).startswith('o2cm:')
            else store.competition(int(member))['refreshed'] for member in comp['members']]
    return {'cid':comp['cid'],'name':comp['name'],'date':comp.get('date'),'updated':min(stamps) if stamps else None,
            'events':[{'eid':e['eid'],'title':e['title'],'source':e['source']} for e in events],
            'dancers':sorted({p for e in events for r in e['rows'] for p in r['people']},key=core.norm)}


def texas_leaderboard(store,filters):
    source=checked_source(filters.get('source','all'));region=filters.get('region','texas')
    if region not in ('texas','national'):raise ValueError('Choose Texas or U.S. national.')
    key=(str(store.path),source)
    with _lock:
        cached=_snapshot.get(key)
        if not cached or time.time()-cached[0]>60:
            comps=flat_catalog(store,source)
            verified=[c for c in comps if c['state'].upper() in US_STATES or c['state'].upper()=='TEXAS']
            events=[(comp,event) for comp in verified for event in event_rows(store,comp['cid'])]
            cached=(time.time(),comps,verified,events);_snapshot[key]=cached
    _,comps,verified,events=cached
    names={};included={};seen_results={};duplicates=0;skipped=0
    eligible=[c for c in verified if region=='national' or c['state'].upper() in ('TX','TEXAS')]
    eligible_ids={str(c['cid']) for c in eligible}
    for comp,event in events:
        if str(comp['cid']) not in eligible_ids:continue
        if filters.get('year') and not (comp.get('date') or '').startswith(filters['year']):continue
        title=event['classified_title'];category=event['category']
        if any(filters.get(k) and filters[k]!=v for k,v in [('category',category),('style',core.classify(title,core.STYLE_PATTERNS)),('level',core.classify(title,core.LEVEL_PATTERNS))]):continue
        if filters.get('excludeUncontested')=='true' and event['entries']==1:continue
        if category=='Unclassified' or re.search(r'\b(team|formation)\b',title,re.I):skipped+=1;continue
        included[str(comp['cid'])]=comp
        seen_names=set()
        for result in event['rows']:
            people=result['people']
            if any(re.search(r'\(#|^Entrant\s+\d',p) for p in people):continue
            if category==core.CAT_LEAD:people=people[:1] if len(people)==2 and event['source']=='bce' else []
            elif category==core.CAT_FOLLOW:people=people[1:] if len(people)==2 and event['source']=='bce' else []
            elif category==core.CAT_COUPLE and len(people)!=2:continue
            elif category==core.CAT_SOLO and len(people)!=1:continue
            mirror=(comp.get('date'),core.norm(comp['name']),core.norm(event['title']),core.norm(result['entry']),result['place'],event['entries'],result['made_final'])
            if comp.get('date') and mirror in seen_results and seen_results[mirror]!=event['source']:duplicates+=1;continue
            seen_results[mirror]=event['source']
            for person in people:
                identity=core.norm(person)
                if identity in seen_names:continue
                seen_names.add(identity)
                row=names.setdefault(identity,{'name':person,'wins':0,'events':0,'comps':set(),'sources':set()})
                row['events']+=1;row['comps'].add((comp.get('date'),core.norm(comp['name'])));row['sources'].add(event['source'])
                if result.get('made_final') and result.get('place')==1:row['wins']+=1
    ordered=sorted(names.values(),key=lambda r:(-r['wins'],core.norm(r['name'])))
    previous,rank=None,0
    for i,row in enumerate(ordered,1):
        if row['wins']!=previous:rank=i;previous=row['wins']
        row.update(rank=rank,competitions=len(row.pop('comps')),sources=sorted(row['sources']))
    search=core.norm(filters.get('q',''));matches=[r for r in ordered if not search or search in core.norm(r['name'])]
    return {'rows':matches[:500],'matching_names':len(matches),'total_names':len(ordered),'updated':cached[0],
            'competitions':list(included.values()),'verified_texas':sum(c['state'].upper() in ('TX','TEXAS') for c in verified),
            'unknown_venues':sum(not c['state'] for c in comps),'years':sorted({(c.get('date') or '')[:4] for c in eligible}-{''},reverse=True),
            'deduplicated':duplicates,'unclassified_events':skipped,'source':source,'region':region}
