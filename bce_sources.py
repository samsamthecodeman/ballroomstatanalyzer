"""Resolve the unified search and combine explicitly selected result providers."""
import bce_analyze as core
import bce_o2cm as o2


def split_name(value):
    value = core.clean(value)
    if ',' in value:
        last, first = (core.clean(part) for part in value.split(',', 1))
    else:
        parts = value.rsplit(' ', 1)
        if len(parts) != 2:
            raise ValueError('Enter a full name, or a Ballroom Comp Express dancer ID. For compound surnames, use Last name, First name.')
        first, last = parts
    if not first or not last:
        raise ValueError('Enter both a first and last name.')
    return first, last


def collect(params, fetcher, progress=None):
    source = params.get('source', 'bce')
    name = params.get('name') or ''
    aid = params.get('aid')
    progress = progress or (lambda *args: None)
    partner = params.get('partner') or None
    warnings = []
    bce = None
    o2cm = None
    allowed_partners = None
    candidates = []
    candidate_check = False
    o2_name = None
    if params.get('first') and params.get('last'):
        first, last = params['first'], params['last']
        o2_name = first, last
        name = f'{first} {last}'
    elif source in ('all', 'o2cm') and name:
        first, last = split_name(name)
        o2_name = first, last
        name = f'{first} {last}'
    if source == 'all' and name:
        try:
            candidates = core.search_dancers(name, fetcher)
            exact = [candidate for candidate in candidates if core.norm(candidate['name']) == core.norm(name)]
            candidates = exact
            candidate_check = True
            if len(exact) > 1 and not aid:
                first, last = o2_name or split_name(name)
                partners = o2.partner_names(first, last, fetcher, progress)
                linked = []
                for i, candidate in enumerate(exact):
                    progress('discover', i, len(exact), 'Comparing shared partnerships to resolve matching names...')
                    result = core.collect(name, fetcher, aid=candidate['id'], partner=partner, workers=4, progress=progress)
                    if result['status'] not in ('ok', 'no_events', 'no_aid_comps'):
                        raise ValueError('Partnership checks could not inspect every matching profile. Select a suggestion or enter a dancer ID.')
                    own_partners = {core.norm(p) for record in result['records'] for p in core.split_people(record.partner)}
                    if own_partners & partners:
                        linked.append((candidate['id'], result, own_partners))
                if len(linked) != 1:
                    raise ValueError('Partnership checks could not identify one unique matching dancer. Select a Ballroom Comp Express suggestion or enter a dancer ID.')
                aid, bce, allowed_partners = linked[0]
                warnings.append('Multiple profiles matched this name. The identity was linked using shared partnerships; O2CM events without a verified shared partner were excluded.')
            elif exact and not aid:
                aid = exact[0]['id']
            elif not exact and not aid:
                warnings.append('No exact Ballroom Comp Express identity matched this name; only O2CM matches can be included.')
        except core.Cancelled:
            raise
        except ValueError as exc:
            if 'Partnership checks' in str(exc):
                raise
            if len(candidates) > 1 and not aid:
                raise ValueError('Multiple matching profiles could not be checked reliably. Select a suggestion or enter a Ballroom Comp Express dancer ID.') from exc
            warnings.append(f'Ballroom Comp Express name lookup unavailable: {exc}')
    if bce is None and ((source in ('bce', 'all') and (aid or source == 'bce')) or (source == 'o2cm' and aid)):
        try:
            cids = core.parse_cids(params['cids']) if source == 'bce' and params.get('cids') else None
            # A numeric search resolves the authoritative name before querying O2CM.
            bce = core.collect(name, fetcher, aid=aid, cids=cids, partner=partner,
                               fuzzy=.88 if params.get('fuzzy') else None, workers=4, progress=progress)
            if bce.get('name'):
                name = bce['name']
            if source == 'bce':
                return {**bce, 'aid': aid}
        except core.Cancelled:
            raise
        except Exception as exc:
            if source != 'all':
                raise
            warnings.append(f'Ballroom Comp Express results unavailable: {exc}')
    if source in ('all', 'o2cm'):
        if not name:
            raise ValueError('Could not resolve that Ballroom Comp Express ID to a name. Enter the full O2CM name instead.')
        first, last = o2_name if o2_name and core.norm(' '.join(o2_name)) == core.norm(name) else split_name(name)
        if source == 'all' and not candidate_check and bce:
            try:
                candidates = [candidate for candidate in core.search_dancers(name, fetcher)
                              if core.norm(candidate['name']) == core.norm(name)]
            except ValueError:
                allowed_partners = {core.norm(p) for record in bce['records'] for p in core.split_people(record.partner)}
                warnings.append('Name ambiguity could not be checked; only O2CM partnerships shared with this Ballroom Comp Express ID were included.')
        if source == 'all' and len(candidates) > 1 and bce:
            allowed_partners = {core.norm(p) for record in bce['records'] for p in core.split_people(record.partner)}
            warnings.append('Matching names were checked against shared partnerships. Unverified O2CM partnerships were excluded.')
        try:
            try:
                o2cm = o2.collect(first, last, fetcher, partner=partner,
                                  competitions=params.get('o2_comps'), progress=progress, allowed_partners=allowed_partners)
            except o2.AmbiguousName:
                if source != 'all' or not bce:
                    raise
                allowed_partners = {core.norm(p) for record in bce['records'] for p in core.split_people(record.partner)}
                o2cm = o2.collect(first, last, fetcher, partner=partner, progress=progress, allowed_partners=allowed_partners)
                warnings.append('Repeated O2CM names were resolved using verified Ballroom Comp Express partnerships only.')
            if source == 'o2cm':
                return {**o2cm, 'aid': aid}
        except core.Cancelled:
            raise
        except Exception as exc:
            if source != 'all':
                raise
            warnings.append(f'O2CM results unavailable: {exc}')
    results = [result for result in (bce, o2cm) if result]
    raw = []
    seen = {}
    duplicates = 0
    for result in results:
        warnings.extend(result.get('warnings', []))
        for record, field in result['raw_events']:
            # Suppress only exact cross-provider duplicate records, never fuzzy guesses.
            key = (record.date, core.norm(record.comp), core.norm(record.event), core.norm(record.entry),
                   record.place, record.entries, record.made_final)
            if key in seen and seen[key] != record.source:
                duplicates += 1
                continue
            seen[key] = record.source
            raw.append((record, field))
    if bce and not bce['records']:
        warnings.append('No Ballroom Comp Express events matched this search.')
    if o2cm and not o2cm['records']:
        warnings.append('No O2CM events matched this exact name.')
    if duplicates:
        warnings.append(f'{duplicates} identical cross-source event record(s) were counted once.')
    warnings.insert(0, 'Unified data combines exact-name matches across Ballroom Comp Express and O2CM. Multiple matching profiles are checked using shared partnerships. Review differently titled duplicate events; O2CM roles remain unverified and do not contribute YCN points.')
    raw.sort(key=lambda pair: (pair[0].date, str(pair[0].cid), str(pair[0].eid)))
    return {'status': 'ok' if raw else 'no_all_results', 'name': name, 'aid': aid,
            'raw_events': raw, 'records': [record for record, _ in raw],
            'spellings': set().union(*(result['spellings'] for result in results)),
            'warnings': list(dict.fromkeys(warnings)), 'alternatives': [], 'suggestions': [],
            'comps_scanned': len({(record.source, str(record.cid)) for record, _ in raw}),
            'events_scanned': sum(result['events_scanned'] for result in results)}
