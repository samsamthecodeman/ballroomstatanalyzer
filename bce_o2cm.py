"""O2CM public results importer. Provider IDs never overlap Comp Express IDs."""
import json
import re
import time
from datetime import datetime, date
from urllib.parse import parse_qs, urlparse, urlencode

from bs4 import BeautifulSoup

import bce_analyze as core
from bce_store import WEEK

BASE = "https://results.o2cm.com/"
VERSION = 1
class AmbiguousName(ValueError):
    pass
CODE = re.compile(r"^[A-Za-z0-9_-]{2,30}$")
HEAT = re.compile(r"^[0-9A-Fa-f]{1,16}$")
WARNING = ("O2CM histories match exact names, not Comp Express IDs. People with the same name may appear; "
           "verify competitions and partners. Leader/follower roles are unverified, so O2CM events do not contribute YCN points.")


def valid_response(parser, body, *args):
    try:
        parser(body, *args)
        return True
    except ValueError:
        return False


def parse_history(html):
    soup = BeautifulSoup(html, "html.parser")
    current = None
    comps = {}
    for row in soup.select("tr"):
        if row.find("table"):
            continue
        text = core.clean(row.get_text(" "))
        match = re.match(r"^(\d{2}-\d{2}-\d{2,4})\s*-\s*(.+)", text)
        if match:
            fmt = "%m-%d-%Y" if len(match[1]) == 10 else "%m-%d-%y"
            try:
                current = {"date": datetime.strptime(match[1], fmt).date().isoformat(), "name": match[2]}
            except ValueError:
                current = None
        for link in row.select("a[href]"):
            query = parse_qs(urlparse(link["href"]).query)
            code = query.get("event", [""])[0]
            heat = query.get("heatid", [""])[0].upper()
            if current and CODE.fullmatch(code) and HEAT.fullmatch(heat):
                comp = comps.setdefault(code.lower(), {**current, "code": code, "heats": []})
                if heat not in comp["heats"]:
                    comp["heats"].append(heat)
    if not comps and "no results on file" not in soup.get_text(" ").lower():
        raise ValueError("O2CM returned an unrecognized dancer-history page; no existing cached results were replaced.")
    return list(comps.values())


def parse_competition(html, code):
    """Parse published overall placements, bold final rows, ties and round separators."""
    soup = BeautifulSoup(html, "html.parser")
    events = {}
    current = None
    group = 0
    for row in soup.select("tr"):
        if row.find("table"):
            continue
        for link in row.select("a[href]"):
            query = parse_qs(urlparse(link["href"]).query)
            heat = query.get("heatid", [""])[0].upper()
            event = query.get("event", [""])[0]
            if HEAT.fullmatch(heat) and event.lower() == code.lower():
                current = events.setdefault(heat, {"title": core.clean(link.get_text(" ")), "entries": [], "rounds": 1})
                group = 0
                break
        if not current:
            continue
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        cell = cells[-1]
        text = core.clean(cell.get_text(" "))
        if re.fullmatch(r"-{3,}", text):
            group += 1
            current["rounds"] = max(current["rounds"], group + 1)
            continue
        match = re.match(r"^(\d+(?:\.\d+)?)\)\s+(\d+)\s+(.+)$", text)
        if not match:
            continue
        # The source appends affiliation/location after a spaced hyphen.
        names = re.split(r"\s+-\s*", match[3], maxsplit=1)[0].strip()
        people = [core.clean(p) for p in names.split(" & ") if core.clean(p)]
        if not people:
            continue
        place = float(match[1])
        current["entries"].append({"bib": match[2], "entry": " & ".join(people), "people": people,
                                   "place": int(place) if place.is_integer() else place,
                                   "made_final": "t2b" in cell.get("class", []), "group": group})
    events = {heat: event for heat, event in events.items() if event["entries"]}
    if not events:
        raise ValueError("O2CM returned an unrecognized competition results page; no cached results were replaced.")
    return events


def expanded_title(title):
    title = re.sub(r"\(([WTVFQCSRPJBM]{2,})\)", lambda m: "(" + "/".join(m[1]) + ")", title)
    title = re.sub(r"\bIntl\.?\s*", "International ", title, flags=re.I)
    title = re.sub(r"\bAm\.\s*", "American ", title, flags=re.I)
    title = re.sub(r"\bV\.\s*Waltz\b", "Viennese Waltz", title, flags=re.I)
    if re.search(r"International (?:Waltz|Tango|Viennese Waltz|Foxtrot|Quickstep)", title, re.I):
        title = title.replace("International ", "International Standard ")
    elif re.search(r"International (?:Cha|Samba|Rumba|Paso|Jive)", title, re.I):
        title = title.replace("International ", "International Latin ")
    return title


def _profile_key(first, last):
    # Keep first/last boundaries and spelling; O2CM requires an exact match.
    return json.dumps([core.clean(first).casefold(), core.clean(last).casefold()])


def load_history(first, last, fetcher, force=False):
    key = _profile_key(first, last)
    cached = fetcher.store.get_external("o2cm", "profile", key)
    if cached and not force and time.time() - cached["updated"] < WEEK:
        return cached["data"], []
    html = fetcher.get(BASE + "individual.asp", max_age=0 if force else WEEK,
                       post_data={"szFirst": first, "szLast": last, "Search": "Search"},
                       cache_misses=False, validate=lambda body: valid_response(parse_history, body))
    if html is None:
        if cached:
            return cached["data"], ["O2CM is unavailable; showing the last successfully cached history."]
        raise ValueError("O2CM could not be reached from this server. Comp Express searches are still available. Please try O2CM again later.")
    comps = parse_history(html)
    data = {"first": first, "last": last, "comps": comps, "version": VERSION}
    fetcher.store.put_external("o2cm", "profile", key, data)
    return data, []


def load_competition(comp, fetcher, force=False):
    key = comp["code"].lower()
    cached = fetcher.store.get_external("o2cm", "competition", key)
    old = (date.today() - date.fromisoformat(comp["date"])).days >= 30
    if cached and cached["data"].get("version") == VERSION and not force:
        # A final successful refresh is required when a recent comp crosses 30 days.
        if set(comp["heats"]).issubset(cached["data"]["events"]) and (cached["data"].get("frozen") or (not old and time.time() - cached["updated"] < WEEK)):
            return cached["data"], []
    params = {"event": comp["code"], "selDiv": "", "selAge": "", "selSkl": "", "selSty": "", "selEnt": "", "submit": "OK"}
    html = fetcher.get(BASE + "event3.asp", post_data=params, max_age=0 if cached or force else None,
                       cache_misses=False, validate=lambda body: valid_response(parse_competition, body, comp["code"]))
    if html is None:
        if cached:
            return cached["data"], [f"O2CM could not refresh {comp['name']}; using cached results."]
        raise ValueError(f"O2CM results are unavailable for {comp['name']}. No placements were guessed.")
    events = parse_competition(html, comp["code"])
    # Never accept a silently truncated page (large competitions initially show only Open).
    if not set(comp["heats"]).issubset(events):
        raise ValueError(f"O2CM returned incomplete results for {comp['name']}. Try again later; existing cached data was kept.")
    data = {"version": VERSION, "meta": comp, "events": events, "frozen": old}
    fetcher.store.put_external("o2cm", "competition", key, data)
    return data, []


def collect(first, last, fetcher, partner=None, competitions=None, progress=None, force=False,
            refresh_history=False, refresh_recent=False, allowed_partners=None):
    progress = progress or (lambda *args: None)
    first, last = core.clean(first), core.clean(last)
    if not first or not last:
        raise ValueError("O2CM requires an exact first name and last name.")
    progress("discover", 0, 1, "Finding O2CM dancer history...")
    profile, warnings = load_history(first, last, fetcher, force or refresh_history)
    comps = [c for c in profile["comps"] if not competitions or c["code"].lower() in competitions]
    raw, spellings = [], set()
    target = core.norm(f"{first} {last}")
    for i, comp in enumerate(comps):
        progress("comps", i, len(comps), f"Reading O2CM: {comp['name']}")
        recent = (date.today() - date.fromisoformat(comp["date"])).days < 30
        saved, notes = load_competition(comp, fetcher, force or (refresh_recent and recent))
        warnings.extend(notes)
        for heat in comp["heats"]:
            event = saved["events"].get(heat)
            if not event:
                raise ValueError(f"O2CM's cached results are missing an event in {comp['name']}; try again after refresh.")
            candidates = [entry for entry in event["entries"] if any(core.norm(p) == target for p in entry["people"])]
            if partner:
                candidates = [entry for entry in candidates if any(core.norm(p) == core.norm(partner) for p in entry["people"] if core.norm(p) != target)]
            if allowed_partners is not None:
                candidates = [entry for entry in candidates if any(core.norm(p) in allowed_partners for p in entry["people"] if core.norm(p) != target)]
            if len(candidates) > 1:
                raise AmbiguousName(f"Multiple O2CM entries match this name in {comp['name']}. Specify the exact partner to disambiguate.")
            if not candidates:
                continue
            own = candidates[0]
            title = event["title"]
            normalized = expanded_title(title)
            style = core.classify(normalized, core.STYLE_PATTERNS)
            category = core.event_category(title)
            if category == core.CAT_COUPLE and (len(own["people"]) != 2 or re.search(r"\bmixed\b|proficiency", title, re.I)):
                category = "Unclassified"
            results = {}
            own_key = None
            for entry in event["entries"]:
                key = entry["entry"]
                if key in results:
                    key += f" (#{entry['bib']})"
                results[key] = {"place": entry["place"], "made_final": entry["made_final"], "rounds": max(1, event["rounds"] - entry["group"])}
                if entry is own:
                    own_key = key
            spellings.update(p for p in own["people"] if core.norm(p) == target)
            rec = core.EventRecord(
                cid="o2cm:" + comp["code"].lower(), eid="o2cm:" + heat, comp=comp["name"], date=comp["date"],
                event=title, category=category, division=core.classify(title, core.DIVISION_PATTERNS),
                age=core.classify(title, core.AGE_PATTERNS), style=style, level=core.classify(title, core.LEVEL_PATTERNS),
                dances=core.event_dances(normalized, style), entry=own_key,
                partner=" & ".join(p for p in own["people"] if core.norm(p) != target), role="Unknown",
                rounds_in_event=event["rounds"], place=own["place"], entries=len(event["entries"]),
                made_final=own["made_final"], percentile=core.percentile(own["place"], len(event["entries"])),
                url=BASE + "scoresheet3.asp?" + urlencode({"event": comp["code"], "heatid": heat}), source="o2cm")
            raw.append((rec, results))
    raw.sort(key=lambda pair: (pair[0].date, pair[0].cid, pair[0].eid))
    return {"status": "ok" if raw else "no_o2_results", "name": f"{first} {last}", "records": [r for r, _ in raw],
            "raw_events": raw, "spellings": spellings, "suggestions": [], "alternatives": [], "comps_scanned": len(comps),
            "events_scanned": sum(len(c["heats"]) for c in comps), "warnings": [WARNING, *dict.fromkeys(warnings)]}


def refresh_known(fetcher, progress=None):
    for key in fetcher.store.external_keys("o2cm", "profile"):
        profile = fetcher.store.get_external("o2cm", "profile", key)["data"]
        collect(profile["first"], profile["last"], fetcher, progress=progress,
                refresh_history=True, refresh_recent=True)


def partner_names(first, last, fetcher, progress=None):
    """Inspect all name matches without choosing among same-name entries."""
    progress = progress or (lambda *args: None)
    profile, _ = load_history(first, last, fetcher)
    target = core.norm(f'{first} {last}')
    partners = set()
    for i, comp in enumerate(profile['comps']):
        progress('comps', i, len(profile['comps']), 'Checking O2CM partnerships...')
        saved, _ = load_competition(comp, fetcher)
        for heat in comp['heats']:
            for entry in saved['events'][heat]['entries']:
                if any(core.norm(p) == target for p in entry['people']):
                    partners.update(core.norm(p) for p in entry['people'] if core.norm(p) != target)
    return partners
