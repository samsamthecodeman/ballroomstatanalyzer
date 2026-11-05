#!/usr/bin/env python3
"""
bce_analyze.py - Historical performance analysis for a dancer on ballroomcompexpress.com

Crawls the public results pages (results.php?cid=<comp> and results.php?cid=<comp>&eid=<event>),
finds every event the named dancer appeared in, and reports:
  * overall record (wins, podiums, finals made, average placement, percentile vs. the field)
  * breakdowns by style, level, category and partner
  * a comp-by-comp timeline with a trend line
  * head-to-head records against every other dancer they've shared a floor with

Every fetched page is cached on disk (./bce_cache by default), so the first run is slow and
later runs are fast. Use --refresh to re-download.

Usage:
    pip install requests beautifulsoup4          # matplotlib optional, for --plot
    python bce_analyze.py                     # asks you for a name or dancer ID
    python bce_analyze.py --aid 10062         # fastest: by dancer ID (aid= in the site's address bar)
    python bce_analyze.py "Jane Smith"        # by name: reads every event on the site (slow first time)
    python bce_analyze.py "Jane Smith" --fuzzy --out jane_report --plot
    python bce_analyze.py "Jane Smith" --cids 150-250 --partner "John Doe"

Finding a dancer ID: open any comp they danced at under Results, type their name in the "Dancer"
box and pick them. The address bar then ends in aid=<number>; that number is the ID.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import threading
import tempfile
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from statistics import mean, median
from urllib.parse import urljoin, urlparse, parse_qs
from urllib.parse import urlencode
from datetime import date

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependencies. Run:  pip install requests beautifulsoup4")

BASE = "https://ballroomcompexpress.com/"
RESULTS_URL = urljoin(BASE, "results.php")
USER_AGENT = "Mozilla/5.0 (compatible; BallroomStatsAnalyzer/1.0; +https://bsa.sam-moran.com)"
LIST_MAX_AGE = 7 * 86400   # lists of comps and a dancer's comps: re-check weekly
COMP_MAX_AGE = 7 * 86400   # recent/undated event lists: re-check weekly
# Event results don't change once posted, so event pages are kept indefinitely.


# ----------------------------------------------------------------------------------------------
# Fetching with a polite rate limit and an on-disk cache
# ----------------------------------------------------------------------------------------------
class Fetcher:
    def __init__(self, cache_dir: str, delay: float, refresh: bool, timeout: int = 30):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.refresh = refresh
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "text/html,application/json;q=0.9,*/*;q=0.8"
        self._lock = threading.Lock()
        self._last = 0.0
        self.network_hits = 0
        from bce_store import ResultsStore
        self.store = ResultsStore(self.cache_dir)

    def _path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url: str, use_cache: bool = True, max_age: float | None = None,
            post_data: dict | None = None, cache_misses: bool = True, validate=None) -> str | None:
        """Fetch a page, using the saved copy unless it's older than max_age seconds (None = keep forever)."""
        path = self._path(url if post_data is None else url + "?__post=" + urlencode(sorted(post_data.items())))
        miss = path.with_suffix(".miss")

        def fresh(f: Path) -> bool:
            return f.exists() and (max_age is None or time.time() - f.stat().st_mtime < max_age)

        if use_cache and not self.refresh:
            if fresh(path):
                body = path.read_text(encoding="utf-8", errors="replace")
                if validate is None or validate(body):
                    return body
            if cache_misses and fresh(miss):
                return None
        for attempt in range(3):
            with self._lock:  # global rate limit shared by all worker threads
                wait = self._last + self.delay - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                resp = (self.session.post(url, data=post_data, timeout=self.timeout) if post_data is not None
                        else self.session.get(url, timeout=self.timeout))
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            self.network_hits += 1
            if resp.status_code == 200:
                if validate is not None and not validate(resp.text):
                    return None
                # Readers always see a complete page, even during a background refresh.
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as f:
                    f.write(resp.text)
                    temporary = Path(f.name)
                try:
                    temporary.replace(path)
                    miss.unlink(missing_ok=True)
                finally:
                    temporary.unlink(missing_ok=True)
                return resp.text
            if resp.status_code in (400, 401, 403, 404, 410):
                if cache_misses:
                    miss.write_text(str(resp.status_code))
                return None
            time.sleep(2 * (attempt + 1))  # 429 / 5xx: back off and retry
        return None


# ----------------------------------------------------------------------------------------------
# Text helpers
# ----------------------------------------------------------------------------------------------
def norm(s: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return " ".join(s.split())


def clean(s: str) -> str:
    return " ".join((s or "").split())


def split_people(entry: str) -> list[str]:
    parts = re.split(r"\s*&\s*|\s+and\s+|\s*/\s*|\s*\+\s*", entry)
    return [clean(p) for p in parts if clean(p)]


MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
DATE_RE = re.compile(
    r"\b(" + "|".join(m.capitalize() for m in MONTHS) + r")\s+(\d{1,2})"
    r"(?:\s*[-–]\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2}))?,\s*(\d{4})", re.I
)


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    month = MONTHS.index(m.group(1).lower()) + 1
    end_month = MONTHS.index(m.group(3).lower()) + 1 if m.group(3) and m.group(3).lower() in MONTHS else month
    year = int(m.group(5)) - (1 if end_month < month else 0)
    try:
        return date(year, month, int(m.group(2))).isoformat()
    except ValueError:
        return None


def parse_end_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    month_name = m.group(3) or m.group(1)
    if month_name.lower() not in MONTHS:
        return None
    try:
        return date(int(m.group(5)), MONTHS.index(month_name.lower()) + 1, int(m.group(4) or m.group(2))).isoformat()
    except ValueError:
        return None


def parse_place(text: str) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


# ----------------------------------------------------------------------------------------------
# Data embedded in the site's pages as  var results = JSON.parse('...');
# ----------------------------------------------------------------------------------------------
JSVAR_RE = re.compile(r"var\s+(\w+)\s*=\s*JSON\.parse\(\s*'((?:[^'\\]|\\.)*)'\s*\)", re.S)
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
def js_unescape(s):
    out, i, L = [], 0, len(s)
    while i < L:
        c = s[i]
        if c == "\\" and i + 1 < L:
            n = s[i + 1]
            if n == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6] or ""):
                out.append(chr(int(s[i + 2:i + 6], 16))); i += 6; continue
            if n == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", s[i + 2:i + 4] or ""):
                out.append(chr(int(s[i + 2:i + 4], 16))); i += 4; continue
            out.append(_SIMPLE.get(n, n)); i += 2; continue
        out.append(c); i += 1
    return "".join(out)
def js_vars(html):
    found = {}
    for m in JSVAR_RE.finditer(html):
        try:
            found[m.group(1)] = json.loads(js_unescape(m.group(2)))
        except ValueError:
            pass
    return found


# ----------------------------------------------------------------------------------------------
# Event classification (style / level / category / age) from the event title
# ----------------------------------------------------------------------------------------------
STYLE_PATTERNS = [
    ("International Standard", r"international (standard|ballroom)|\bstandard\b"),
    ("International Latin", r"international latin|\blatin\b"),
    ("American Smooth", r"american smooth|\bsmooth\b|american (waltz|tango|foxtrot|viennese)"),
    ("American Rhythm", r"american rhythm|\brhythm\b|american (cha|rumba|swing|bolero|mambo)"),
    ("Nightclub / Social", r"west coast|hustle|salsa|bachata|argentine|nightclub|two-step|merengue|country"),
    ("Cabaret / Show", r"cabaret|show ?dance|theatre|theater"),
]
LEVEL_PATTERNS = [
    ("Pre-Champ", r"pre[- ]?champ"),
    ("Championship", r"\bchamp(ionship)?\b|\bs class\b"),
    ("Novice", r"\bnovice\b"),
    ("Pre-Bronze", r"pre[- ]?bronze"),
    ("Bronze", r"bronze"),
    ("Silver", r"silver"),
    ("Gold", r"gold"),
    ("Newcomer / Beginner", r"newcomer|\bbeginn(er|ing)\b"),
    ("Open", r"\bopen\b"),
    ("Syllabus / Mixed", r"syllabus|mixed level"),
]
DIVISION_PATTERNS = [
    ("Proficiency", r"proficiency"),
    ("Pro/Am", r"pro/?am|teacher/student"),
    ("Solo", r"\bsolo\b"),
    ("Mixed Am", r"mixed am"),
    ("Switch-Role", r"switch"),
    ("WDSF", r"\bwdsf\b"),
    ("Amateur", r"amateur"),
]
AGE_PATTERNS = [
    ("Teddy Bear", r"teddy bear"), ("Pre-Teen", r"pre-?teen"), ("Junior High", r"junior high"),
    ("Junior", r"junior"), ("Youth", r"youth"), ("Under 21", r"under 21"),
    ("Collegiate", r"collegiate"), ("High School", r"high school"), ("Elementary", r"elementary"),
    ("Senior", r"senior"), ("Adult", r"adult"),
]


CAT_COUPLE = "Couple-judged"
CAT_LEAD = "Mixed proficiency – leader judged"
CAT_FOLLOW = "Mixed proficiency – follower judged"
CAT_SOLO = "Solo"
CATEGORIES = [CAT_COUPLE, CAT_LEAD, CAT_FOLLOW, CAT_SOLO]
LEAD_WORD_RE = re.compile(r"\blead(?:er)?s?\b'?")
FOLLOW_WORD_RE = re.compile(r"\bfollow(?:er)?s?\b'?")


def event_category(title: str, judged: str | None = None, solo_share: float = 0.0) -> str:
    """
    Sort an event into one of four categories.
    1. The site's own data: each entrant is tagged with what is judged ("entrant" for a couple;
       a leader/follower tag for mixed proficiency).
    2. The event name: "Mixed Leads/Follows", "Leaders'/Followers' ... Proficiency",
       "Follower-judged", etc.
       These count as mixed proficiency even when the name also says "Solo".
    3. Solo: named "Solo", tagged as an individual, or nearly every entry is a single dancer.
    4. Everything else, including Pro/Am, is couple-judged.
    """
    t = (title or "").lower()
    j = (judged or "").lower()
    if "lead" in j:
        return CAT_LEAD
    if "follow" in j:
        return CAT_FOLLOW
    lead, follow = bool(LEAD_WORD_RE.search(t)), bool(FOLLOW_WORD_RE.search(t))
    role_event = ("proficiency" in t or "judged" in t or "mixed prof" in t
                  or re.search(r"\bmixed[\s-]+(?:lead(?:er)?s?|follow(?:er)?s?)\b", t)
                  or re.match(r"\s*(leaders?|followers?)\b", t))
    if role_event and lead != follow:
        return CAT_LEAD if lead else CAT_FOLLOW
    if re.search(r"\bsolo\b", t) or j in ("solo", "dancer", "individual", "single") or solo_share >= 0.8:
        return CAT_SOLO
    return CAT_COUPLE


# Dances, in the order they're usually listed
DANCE_NAMES = [
    ("Waltz", r"(?<!viennese )\bwaltz\b"), ("Tango", r"(?<!argentine )\btango\b"),
    ("Viennese Waltz", r"\bviennese\b"), ("Foxtrot", r"\bfox ?trot\b"), ("Quickstep", r"\bquick ?step\b"),
    ("Samba", r"\bsamba\b"), ("Cha Cha", r"\bcha[- ]?cha\b"), ("Rumba", r"\brumba\b"),
    ("Paso Doble", r"\bpaso\b"), ("Jive", r"\bjive\b"),
    ("Swing", r"(?<!west coast )(?<!east coast )\bswing\b|\beast coast swing\b"), ("Bolero", r"\bbolero\b"),
    ("Mambo", r"\bmambo\b"), ("West Coast Swing", r"\bwest coast\b"), ("Hustle", r"\bhustle\b"),
    ("Salsa", r"\bsalsa\b"), ("Bachata", r"\bbachata\b"), ("Merengue", r"\bmerengue\b"),
    ("Argentine Tango", r"\bargentine\b"), ("Nightclub Two-Step", r"\btwo[- ]?step\b"),
    ("Polka", r"\bpolka\b"), ("Peabody", r"\bpeabody\b"),
]
DANCE_ORDER = [d for d, _ in DANCE_NAMES]
LETTER_CODES = {
    "International Standard": {"W": "Waltz", "T": "Tango", "V": "Viennese Waltz", "F": "Foxtrot", "Q": "Quickstep"},
    "American Smooth": {"W": "Waltz", "T": "Tango", "F": "Foxtrot", "V": "Viennese Waltz"},
    "International Latin": {"S": "Samba", "C": "Cha Cha", "R": "Rumba", "P": "Paso Doble", "J": "Jive"},
    "American Rhythm": {"C": "Cha Cha", "R": "Rumba", "S": "Swing", "B": "Bolero", "M": "Mambo"},
}
CODE_RE = re.compile(r"(?<![A-Za-z/])([A-Z](?:/[A-Z])+)(?![A-Za-z/])")


def event_dances(title: str, style: str) -> list[str]:
    """Which dances an event includes, from its name: "Foxtrot", "W/T/F/V", "S/C/R/P/J", etc."""
    t = title or ""
    found = {d for d, pat in DANCE_NAMES if re.search(pat, t, re.I)}
    for m in CODE_RE.finditer(t):
        letters = m.group(1).split("/")
        codes = LETTER_CODES.get(style)
        if codes is None:  # style unknown: guess from letters that only appear in one family
            if set(letters) <= set("WTFVQ"):
                codes = LETTER_CODES["International Standard"]
            elif set(letters) & set("PJ"):
                codes = LETTER_CODES["International Latin"]
            elif set(letters) & set("BM"):
                codes = LETTER_CODES["American Rhythm"]
            else:
                codes = {"C": "Cha Cha", "R": "Rumba"}  # "S" is ambiguous (Samba or Swing)
        found.update(codes[x] for x in letters if x in codes)
    return sorted(found, key=DANCE_ORDER.index)


def classify(title: str, patterns, default="Other") -> str:
    t = title.lower()
    for label, pat in patterns:
        if re.search(pat, t):
            return label
    return default


# ----------------------------------------------------------------------------------------------
# Page parsing
# ----------------------------------------------------------------------------------------------
CID_RE = re.compile(r"[?&]cid=(\d+)")


COMP_DIV_ID_RE = re.compile(r"^[A-Za-z_-]{2,6}(\d+)$")


def comp_list_entries(html: str) -> dict[int, dict]:
    """The site lists comps as <div class="comp-list"><div id="cmp214">Name / Date / Place</div>..."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[int, dict] = {}
    for wrap in soup.select(".comp-list"):
        for div in wrap.find_all(recursive=False):
            m = COMP_DIV_ID_RE.match(div.get("id") or "")
            if not m:
                continue
            lines = [ln for ln in div.get_text("\n", strip=True).split("\n") if ln.strip()]
            info = {}
            if lines:
                info["name"] = lines[0]
            d = parse_date(" ".join(lines))
            if d:
                info["date"] = d
                info["end_date"] = parse_end_date(" ".join(lines))
            out[int(m.group(1))] = info
    return out


def discover_comps(fetcher: Fetcher) -> dict[int, dict]:
    """Read the home page and results index for comp ids, names and dates."""
    comps: dict[int, dict] = {}
    for url in (RESULTS_URL, urljoin(BASE, "index.php")):
        html = fetcher.get(url, max_age=LIST_MAX_AGE)
        if not html:
            continue
        for cid, info in comp_list_entries(html).items():
            comps.setdefault(cid, {}).update(info)
        soup = BeautifulSoup(html, "html.parser")
        for el in soup.find_all(True):  # older layouts: plain links or onclick handlers
            for val in el.attrs.values():
                for v in (val if isinstance(val, list) else [val]):
                    m = CID_RE.search(str(v))
                    if m and "eid=" not in str(v):
                        info = comps.setdefault(int(m.group(1)), {})
                        text = el.get_text("\n", strip=True)
                        lines = [ln for ln in text.split("\n") if ln.strip()]
                        if lines and "name" not in info and not parse_date(lines[0]):
                            info["name"] = lines[0]
                        if parse_date(text) and "date" not in info:
                            info["date"] = parse_date(text)
    return comps


def attr_text(el, levels: int = 2) -> str:
    """All attribute values (except href) of an element and a few ancestors."""
    out = []
    node = el
    for _ in range(levels + 1):
        if node is None or not hasattr(node, "attrs"):
            break
        for k, v in node.attrs.items():
            if k != "href":
                out.append(" ".join(v) if isinstance(v, list) else str(v))
        node = node.parent
    return " ".join(out)


def parse_comp_page(html: str, cid: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    # The site's hidden login modal precedes the actual competition heading.
    heading = next((h for h in soup.find_all(["h1", "h2", "h3"])
                    if re.match(r"results for\s+", clean(h.get_text(" ")), re.I)), None)
    title = clean(heading.get_text(" ")) if heading else f"Comp {cid}"
    title = re.sub(r"^Results for\s+", "", title, flags=re.I)
    events, seen = [], set()
    for a in soup.find_all("a", href=True):
        q = parse_qs(urlparse(a["href"]).query)
        if "eid" not in q or q.get("cid", [str(cid)])[0] != str(cid):
            continue
        try:
            eid = int(q["eid"][0])
        except ValueError:
            continue
        if eid in seen:
            continue
        seen.add(eid)
        events.append({
            "eid": eid,
            "title": clean(a.get_text(" ")),
            "url": urljoin(RESULTS_URL, a["href"]),
            "attrs": norm(attr_text(a)),
        })
    # Current layout: <div class="event-link" id="evt114">Event name</div>
    for el in soup.select(".event-link"):
        m = re.search(r"(\d+)$", el.get("id") or "")
        if not m or int(m.group(1)) in seen:
            continue
        eid = int(m.group(1))
        seen.add(eid)
        events.append({
            "eid": eid,
            "title": clean(el.get_text(" ")),
            "url": f"{RESULTS_URL}?cid={cid}&eid={eid}",
            "attrs": "",
        })
    return {"cid": cid, "name": title, "date": parse_date(soup.get_text(" ")),
            "end_date": parse_end_date(soup.get_text(" ")), "events": events}


def parsed_event(html):
    data = parse_event_data(html)
    if data:
        return data
    results, n = compute_event_results(parse_event_page(html))
    return results, n, None, {
        "judged": None, "n_rounds": max(1, max((r["rounds"] for r in results.values()), default=1)),
        "solo_share": sum(1 for x in results if len(split_people(x)) == 1) / max(len(results), 1),
    }


def search_dancers(query, fetcher):
    query = clean(query)
    if len(query) < 3 or len(query) > 80:
        return []
    body = fetcher.get(urljoin(BASE, "php/searchCompsAndDancers.php"),
                       post_data={"query": query}, max_age=LIST_MAX_AGE)
    if body is None:
        raise ValueError("Dancer lookup is unavailable. Try again or enter a dancer ID.")
    try:
        rows = json.loads(body)
    except (ValueError, TypeError):
        raise ValueError("Dancer lookup returned an unexpected response. Enter a dancer ID instead.") from None
    if not isinstance(rows, list):
        raise ValueError("Dancer lookup returned an unexpected response. Enter a dancer ID instead.")
    matches = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "dancer" or not str(row.get("acctid", "")).isdigit():
            continue
        name = clean(f"{row.get('fname') or ''} {row.get('lname') or ''}")
        if name:
            matches.append({"id": int(row["acctid"]), "name": name,
                            "location": ", ".join(str(x) for x in (row.get("city"), row.get("stateabbrev") or row.get("countryname")) if x)})
    return matches[:20]


DANCE_RE = re.compile(
    r"\b(waltz|tango|foxtrot|fox trot|quickstep|viennese|cha ?cha|samba|rumba|paso|jive|swing|"
    r"bolero|mambo|hustle|salsa|bachata|merengue|polka|peabody|two[- ]step)\b", re.I)
OVERALL_RE = re.compile(r"overall|summary|total|combined|final (result|placement|standing)s?", re.I)
ROUND_RE = re.compile(r"(final|semi[- ]?final|quarter[- ]?final|round\s*\d+|1/\d+|heat)", re.I)
NAME_HEADERS = {"couple", "couples", "dancer", "dancers", "competitor", "competitors", "team",
                "name", "names", "entry", "entries", "participants"}
LEAD_HEADERS = {"leader", "lead", "gentleman", "man"}
FOLLOW_HEADERS = {"follower", "follow", "lady", "woman"}
PLACE_HEADERS = {"place", "placement", "result", "rank", "final place", "pl", "pos", "position"}


@dataclass
class Table:
    label: str
    entries: list  # [(entry_name, place_or_None)]
    is_dance: bool = False
    is_overall: bool = False


def table_label(t) -> str:
    parts = []
    cap = t.find("caption")
    if cap:
        parts.append(cap.get_text(" ", strip=True))
    prev = t.find_previous(["h2", "h3", "h4", "h5", "h6"])
    if prev:
        parts.append(prev.get_text(" ", strip=True))
    sib = t.find_previous_sibling()
    if sib is not None and sib.name != "table":
        txt = sib.get_text(" ", strip=True)
        if 0 < len(txt) <= 60:
            parts.append(txt)
    node = t.parent
    for _ in range(3):
        if node is None or not hasattr(node, "attrs"):
            break
        for k in ("id", "class", "data-round", "data-name", "title"):
            v = node.attrs.get(k)
            if v:
                parts.append(" ".join(v) if isinstance(v, list) else str(v))
        node = node.parent
    return clean(" | ".join(parts))


def parse_event_page(html: str) -> list[Table]:
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [clean(c.get_text(" ")).lower() for c in rows[0].find_all(["th", "td"])]
        place_idx = next((i for i, h in enumerate(headers) if h in PLACE_HEADERS), None)
        if place_idx is None:
            # A callbacks-only table (no place column) still tells us who danced that round
            if not any(h in NAME_HEADERS for h in headers):
                continue
        name_idx = next((i for i, h in enumerate(headers) if h in NAME_HEADERS), None)
        lead_idx = next((i for i, h in enumerate(headers) if h in LEAD_HEADERS), None)
        follow_idx = next((i for i, h in enumerate(headers) if h in FOLLOW_HEADERS), None)
        if name_idx is None and lead_idx is None:
            name_idx = 0 if place_idx != 0 else 1
        entries = []
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if name_idx is not None:
                if name_idx >= len(cells):
                    continue
                name = clean(cells[name_idx].get_text(" "))
            else:
                lead = clean(cells[lead_idx].get_text(" ")) if lead_idx < len(cells) else ""
                fol = clean(cells[follow_idx].get_text(" ")) if follow_idx is not None and follow_idx < len(cells) else ""
                name = " & ".join(p for p in (lead, fol) if p)
            if not name or re.fullmatch(r"[\d\s.]+", name):
                continue
            place = None
            if place_idx is not None and place_idx < len(cells):
                place = parse_place(cells[place_idx].get_text(" "))
            entries.append((name, place))
        if not entries:
            continue
        label = table_label(t)
        is_overall = bool(OVERALL_RE.search(label))
        is_dance = bool(DANCE_RE.search(label)) and not is_overall
        tables.append(Table(label, entries, is_dance, is_overall))
    return tables


def entrant_name(d) -> str | None:
    if not isinstance(d, dict):
        return None
    lead = clean(f"{d.get('leaderfname') or ''} {d.get('leaderlname') or ''}")
    fol = clean(f"{d.get('followerfname') or ''} {d.get('followerlname') or ''}")
    names = [x for x in (lead, fol) if x]
    if names:
        return " & ".join(names)
    for k in ("teamname", "name", "displayname", "fname"):
        if d.get(k):
            return clean(str(d[k]))
    return None


def parse_event_data(html: str):
    """
    Read the results the site embeds in each event page:
      results = {"roundorder": [r1, r2, final], "<round>": {"final": 0/1, "partnershiporder": [ids],
                 "<entrant>": {"place": n | "recall": 0/1, ...}, "designation": "Semifinal"}, ...}
      dancers = {"<entrant>": {"leaderfname", "leaderlname", "followerfname", "followerlname", ...}}
    Couples knocked out in a round are tied at the place right after everyone who went through.
    Returns (results_by_entry_name, number_of_entries, event_title) or None if the data isn't there.
    """
    v = js_vars(html)
    res = v.get("results")
    if not isinstance(res, dict) or "roundorder" not in res:
        return None
    dancers = v.get("dancers") if isinstance(v.get("dancers"), dict) else {}
    rounds = []
    for rid in res.get("roundorder") or []:
        r = res.get(str(rid))
        if not isinstance(r, dict):
            continue
        ids = r.get("partnershiporder") or [k for k in r if str(k).isdigit()]
        ids = [str(i) for i in ids if str(i) in r]
        if ids:
            rounds.append((r, ids))
    if not rounds:
        return None
    # Earlier rounds first (largest field), final last
    rounds.sort(key=lambda ri: (bool(ri[0].get("final")), -len(ri[1])))
    final = rounds[-1] if rounds[-1][0].get("final") else None

    final_places = {}
    if final:
        r, ids = final
        dances = [str(d) for d in (r.get("dances") or [])]
        means = {}
        for eid in ids:
            p = r[eid].get("place") if isinstance(r[eid], dict) else None
            if isinstance(p, (int, float)):
                final_places[eid] = int(p)
            else:
                ps = [r[eid][d]["place"] for d in dances
                      if isinstance(r[eid].get(d), dict) and isinstance(r[eid][d].get("place"), (int, float))]
                if ps:
                    means[eid] = mean(ps)
        if means:  # overall place not stored: rank by average per-dance place
            ranked = sorted(means.items(), key=lambda kv: kv[1])
            prev, rank = None, 0
            for i, (eid, m) in enumerate(ranked, 1):
                if m != prev:
                    rank, prev = i, m
                final_places.setdefault(eid, rank)

    names, used = {}, set()
    for _, ids in rounds:
        for eid in ids:
            if eid in names:
                continue
            nm = entrant_name(dancers.get(eid)) or f"Entrant {eid}"
            if nm in used:
                nm = f"{nm} (#{(dancers.get(eid) or {}).get('number', eid)})"
            used.add(nm)
            names[eid] = nm

    results = {}
    for eid, nm in names.items():
        seen_in = [i for i, (_, ids) in enumerate(rounds) if eid in ids]
        if final and eid in final[1]:
            place, made = final_places.get(eid), True
        else:
            nxt = max(seen_in) + 1
            place = len(rounds[nxt][1]) + 1 if nxt < len(rounds) else None
            made = False
        results[nm] = {"place": place, "made_final": made, "rounds": len(seen_in)}
    title = (v.get("eventinfo") or {}).get("displayname") if isinstance(v.get("eventinfo"), dict) else None
    tags = [str((dancers.get(eid) or {}).get("judgedEntity") or "") for eid in names]
    tags = [x for x in tags if x]
    info = {
        "n_rounds": len(rounds),
        "judged": max(set(tags), key=tags.count) if tags else None,
        "solo_share": sum(1 for nm in names.values() if len(split_people(nm)) == 1) / max(len(names), 1),
    }
    return results, len(names), title, info


def compute_event_results(tables: list[Table]) -> tuple[dict, int]:
    """
    Work out each entry's overall placement in an event.
    The deepest round an entry reached is the smallest stage table they appear in; their place there
    is their result. If the final is only shown dance-by-dance, a combined final is built from the
    mean per-dance placement.
    Returns ({entry: {"place", "made_final", "rounds"}}, number_of_entries).
    """
    overall = [t for t in tables if t.is_overall]
    dance = [t for t in tables if t.is_dance]
    stage = [t for t in tables if not t.is_dance and not t.is_overall]
    n_round_tables = len(stage)
    if overall:
        stage += overall
    elif dance:
        agg = defaultdict(list)
        for t in dance:
            for n, p in t.entries:
                if p is not None:
                    agg[n].append(p)
        ranked = sorted(agg.items(), key=lambda kv: (mean(kv[1]), kv[0]))
        entries, prev, rank = [], None, 0
        for i, (n, ps) in enumerate(ranked, 1):
            m = mean(ps)
            if m != prev:
                rank, prev = i, m
            entries.append((n, rank))
        if entries:
            stage.append(Table("Final (combined from per-dance placements)", entries))
    if not stage:
        return {}, 0
    stage.sort(key=lambda t: len(t.entries))
    everyone = {n for t in tables for n, _ in t.entries}
    results = {}
    for name in everyone:
        idxs = [i for i, t in enumerate(stage) if any(n == name for n, _ in t.entries)]
        if not idxs:
            continue
        deepest = idxs[0]
        place = next((p for n, p in stage[deepest].entries if n == name), None)
        if place is None:
            numeric = [p for i in idxs for n, p in stage[i].entries if n == name and p is not None]
            if numeric:
                place = min(numeric)
            elif deepest > 0:
                place = len(stage[deepest - 1].entries) + 1  # tied with others eliminated here
        rounds = sum(1 for t in tables if not t.is_dance and not t.is_overall
                     and any(n == name for n, _ in t.entries))
        results[name] = {"place": place, "made_final": deepest == 0,
                         "rounds": max(rounds, 1) if n_round_tables else 1}
    return results, len(everyone)


# ----------------------------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------------------------
@dataclass
class EventRecord:
    cid: int
    comp: str
    date: str
    eid: int
    event: str
    category: str
    division: str
    age: str
    style: str
    dances: list
    level: str
    entry: str
    partner: str
    role: str
    rounds_in_event: int
    place: int | None
    entries: int
    made_final: bool
    percentile: float | None
    url: str
    source: str = "bce"


def person_matches(target_n: str, person_n: str, fuzzy: float | None) -> bool:
    if target_n == person_n:
        return True
    return bool(fuzzy) and SequenceMatcher(None, target_n, person_n).ratio() >= fuzzy


def find_target_entry(results: dict, target_n: str, fuzzy):
    """Returns (entry, name as spelled, partner, role). Entries list the leader first."""
    for entry in results:
        people = split_people(entry)
        for i, p in enumerate(people):
            if person_matches(target_n, norm(p), fuzzy):
                partner = " & ".join(x for x in people if x is not p)
                role = "Solo" if len(people) == 1 else ("Leader" if i == 0 else "Follower")
                return entry, p, partner, role
    return None, None, None, None


def percentile(place, n):
    if place is None or n <= 0:
        return None
    if n == 1:
        return 100.0
    return round(100.0 * (n - min(place, n)) / (n - 1), 1)


def summarize(records: list[EventRecord]) -> dict:
    placed = [r for r in records if r.place is not None]
    pcts = [r.percentile for r in records if r.percentile is not None]
    return {
        "events": len(records),
        "wins": sum(1 for r in placed if r.place == 1),
        "podiums": sum(1 for r in placed if r.place <= 3),
        "finals": sum(1 for r in records if r.made_final),
        "avg_place": round(mean(r.place for r in placed), 2) if placed else None,
        "median_place": median(r.place for r in placed) if placed else None,
        "avg_field": round(mean(r.entries for r in records), 1) if records else None,
        "avg_pct": round(mean(pcts), 1) if pcts else None,
    }


def fmt(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


def print_table(headers, rows):
    rows = [[fmt(c) for c in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(w) if i == 0 else c.rjust(w)
                        for i, (c, w) in enumerate(zip(r, widths))))
    print()


def breakdown(records, key_fn, title):
    groups = defaultdict(list)
    for r in records:
        groups[key_fn(r)].append(r)
    rows = []
    for k, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = summarize(rs)
        rows.append([k or "(none)", s["events"], s["wins"], s["podiums"],
                     f"{round(100 * s['finals'] / s['events'])}%", s["avg_place"], s["avg_pct"]])
    print(f"== {title} ==")
    print_table([title.split(" by ")[-1].title(), "Events", "Wins", "Top 3", "Finals", "Avg Pl", "Avg Pct"], rows)


def linear_slope(ys):
    n = len(ys)
    if n < 2:
        return None
    xm, ym = (n - 1) / 2, mean(ys)
    den = sum((x - xm) ** 2 for x in range(n))
    return sum((x - xm) * (y - ym) for x, y in enumerate(ys)) / den if den else None


# ----------------------------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------------------------
class Cancelled(Exception):
    pass


def collect(name, fetcher, fuzzy=None, partner=None, cids=None, max_cid=None, aid=None,
            workers=4, progress=None, refresh_profile=False, **_ignored):
    """
    Scrape everything needed for one dancer.

    With aid (the site's dancer ID, the number after aid= in a results address), only that dancer's
    comps and events are read: fast. With only a name, every event on the site has to be read,
    because the site doesn't list dancer names on comp pages: slow the first time, cached after.

    Returns a dict with status "ok" | "bad_aid" | "no_aid_comps" | "no_comps" | "no_events",
    plus name, records, raw_events, spellings, suggestions, comps_scanned, events_scanned.
    progress(stage, done, total, message) is called as work proceeds; it may raise Cancelled.
    """
    progress = progress or (lambda *a: None)
    name = clean(name or "")
    target_n = norm(name)
    partner_n = norm(partner) if partner else None
    base = {"name": name, "records": [], "raw_events": [], "spellings": set(), "suggestions": [],
            "comps_scanned": 0, "events_scanned": 0}

    def run_pool(items, submit, handle, stage, label):
        ex = ThreadPoolExecutor(workers)
        try:
            futs = {ex.submit(submit, it): it for it in items}
            for i, fut in enumerate(as_completed(futs), 1):
                progress(stage, i, len(items), label(futs[fut], i, len(items)))
                handle(futs[fut], fut.result())
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    store = getattr(fetcher, "store", None)
    profile = store.get_profile(aid) if store and aid and not fetcher.refresh and not refresh_profile else None
    overview = profile["overview"] if profile else None
    using_stale_profile = False
    comps = {}
    if profile:
        progress("comps", 1, 1, "Reading the shared results index...")
        comps = {c["cid"]: c for c in profile["comps"] if not cids or c["cid"] in cids}
    else:
        # 1. Which comps? Dancer-specific pages preserve exact ID-to-event membership.
        progress("discover", 0, 1, "Finding competitions...")
        meta = discover_comps(fetcher)
        if aid:
            overview = fetcher.get(f"{RESULTS_URL}?aid={aid}", max_age=0 if refresh_profile else LIST_MAX_AGE)
            theirs = comp_list_entries(overview) if overview else {}
            if overview is None:
                stale_profile = store.get_profile(aid, max_age=None) if store else None
                if stale_profile:
                    using_stale_profile = True
                    overview = stale_profile["overview"]
                    comps = {c["cid"]: c for c in stale_profile["comps"] if not cids or c["cid"] in cids}
                else:
                    return {**base, "status": "bad_aid"}
            for cid, info in theirs.items():
                meta.setdefault(cid, {}).update({k: v for k, v in info.items() if v})
            comp_ids = sorted(theirs)
            if cids:
                comp_ids = [c for c in comp_ids if c in set(cids)]
            if not comp_ids and not comps:
                return {**base, "status": "no_aid_comps"}
            comp_url = lambda cid: f"{RESULTS_URL}?aid={aid}&cid={cid}"
        else:
            if not cids:
                top = max_cid or ((max(meta) + 5) if meta else 300)
                cids = list(range(1, top + 1))
            comp_ids = list(cids)
            comp_url = lambda cid: f"{RESULTS_URL}?cid={cid}"

        # 2. Comp pages -> event lists. Freeze old dancer-specific listings too.
        def handle_comp(cid, html):
            if not html:
                return
            c = parse_comp_page(html, cid)
            if not c["events"]:
                return
            if cid in meta:
                for key in ("name", "date", "end_date"):
                    c[key] = meta[cid].get(key) or c.get(key)
            comps[cid] = c

        def comp_age(cid):
            end = meta.get(cid, {}).get("end_date") or meta.get(cid, {}).get("date")
            try:
                return None if end and (date.today() - date.fromisoformat(end)).days >= 30 else (0 if refresh_profile else COMP_MAX_AGE)
            except ValueError:
                return COMP_MAX_AGE

        if not comps:
            run_pool(comp_ids, lambda cid: fetcher.get(comp_url(cid), max_age=comp_age(cid)), handle_comp, "comps",
                     lambda cid, i, n: f"Competition pages: {i}/{n}")
        if store and aid and not cids and comps and not using_stale_profile:
            store.put_profile(aid, overview, list(comps.values()))
    base["comps_scanned"] = len(comps)
    if not comps:
        return {**base, "status": "no_comps"}

    # 3. Event pages
    jobs = [(c, e) for c in comps.values() for e in c["events"]]
    parsed = []  # (comp, event, results, n_entries, title, info)
    all_people = set()

    def handle_event(job, html):
        c, e = job
        if not html:
            return
        data = parsed_event(html)
        results, n, title, info = data
        if not results:
            return
        for entry in results:
            all_people.update(split_people(entry))
        parsed.append((c, e, results, n, title, info))
        if store:
            store.put_event(c["cid"], e["eid"], data, (norm(x) for entry in results for x in split_people(entry)))

    indexed = store.get_events((c["cid"], e["eid"]) for c, e in jobs) if store and not fetcher.refresh else {}
    missing = []
    for c, e in jobs:
        data = indexed.get((c["cid"], e["eid"]))
        if data:
            results, n, title, info = data
            parsed.append((c, e, results, n, title, info))
            all_people.update(x for entry in results for x in split_people(entry))
        else:
            missing.append((c, e))
    progress("events", len(parsed), len(jobs), f"Reading saved results: {len(parsed)}/{len(jobs)}")
    run_pool(missing, lambda job: fetcher.get(job[1]["url"]), handle_event, "events",
             lambda job, i, n: f"Event pages: {i}/{n}  ({job[0]['name'][:40]})")
    base["events_scanned"] = len(parsed)

    # 4. Who are we looking for? With a dancer ID, use the name on their results page if it shows one;
    #    otherwise the person who appears in every one of their events (partners can tie, so we report
    #    the others as alternatives).
    base["alternatives"] = []
    if aid:
        counts, display = {}, {}
        for _c, _e, results, _n, _t, _i in parsed:
            for k, shown in {norm(x): x for entry in results for x in split_people(entry)}.items():
                counts[k] = counts.get(k, 0) + 1
                display.setdefault(k, shown)
        named_ok = target_n and any(person_matches(target_n, k, fuzzy) for k in counts)
        if counts and not named_ok:
            most = max(counts.values())
            in_all = sorted(k for k, c in counts.items() if c == most)
            headings = []
            if overview:
                osoup = BeautifulSoup(overview, "html.parser")
                headings = [" " + norm(h.get_text(" ")) + " " for h in osoup.find_all(["h1", "h2", "h3"])]
            pick = next((k for k in in_all if any(f" {k} " in h for h in headings)), None)
            pick = pick or next((k for k in counts if any(f" {k} " in h for h in headings)), None)
            pick = pick or in_all[0]
            target_n, name = pick, display[pick]
            base["name"] = name
            base["alternatives"] = [display[k] for k in in_all if k != pick]

    records, raw_events, spellings = [], [], set()
    for c, e, results, n, title, info in parsed:
        entry, spelled, partner_name, role = find_target_entry(results, target_n, fuzzy)
        if not entry:
            continue
        if partner_n and not any(person_matches(partner_n, norm(p), fuzzy)
                                 for p in split_people(partner_name)):
            continue
        spellings.add(spelled)
        res = results[entry]
        title = title or e["title"]
        rec = EventRecord(
            cid=c["cid"], comp=c["name"], date=c.get("date") or "", eid=e["eid"], event=title,
            category=event_category(title, info.get("judged"), info.get("solo_share", 0)),
            division=classify(title, DIVISION_PATTERNS), age=classify(title, AGE_PATTERNS),
            style=classify(title, STYLE_PATTERNS), level=classify(title, LEVEL_PATTERNS),
            dances=event_dances(title, classify(title, STYLE_PATTERNS)),
            entry=entry, partner=partner_name, role=role, rounds_in_event=info.get("n_rounds", 1),
            place=res["place"], entries=n,
            made_final=res["made_final"], percentile=percentile(res["place"], n),
            url=f"{RESULTS_URL}?cid={c['cid']}&eid={e['eid']}")
        records.append(rec)
        raw_events.append((rec, results))

    if not records:
        return {**base, "status": "no_events",
                "suggestions": get_close_matches(name, sorted(all_people), n=8, cutoff=0.6)}
    records.sort(key=lambda r: (r.cid, r.eid))
    raw_events.sort(key=lambda x: (x[0].cid, x[0].eid))
    return {**base, "status": "ok", "records": records, "raw_events": raw_events, "spellings": spellings}


def parse_cids(spec: str) -> list[int]:
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def progress(msg):
    print(f"\r{msg:<78}", end="", file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Analyze a dancer's history on ballroomcompexpress.com")
    ap.add_argument("name", nargs="?", default=None,
                    help='Dancer name as shown in results, e.g. "Jane Smith", or their dancer ID number '
                         "(you'll be asked if omitted)")
    ap.add_argument("--aid", type=int, default=None,
                    help="Dancer ID (the number after aid= in a results address). Much faster than a name search")
    ap.add_argument("--fuzzy", nargs="?", const=0.88, type=float, default=None,
                    help="Allow approximate name matches (optional similarity threshold, default 0.88)")
    ap.add_argument("--partner", help="Only include events danced with this partner")
    ap.add_argument("--cids", help="Comp ids to scan, e.g. '150-250' or '11,56,169'. Default: all known")
    ap.add_argument("--max-cid", type=int, default=None,
                    help="Highest comp id to scan if auto-discovery fails (default: discovered + 5, or 300)")
    ap.add_argument("--full-scan", action="store_true", help=argparse.SUPPRESS)  # no longer needed
    ap.add_argument("--workers", type=int, default=4, help="Parallel downloads (default 4)")
    ap.add_argument("--delay", type=float, default=0.4, help="Minimum seconds between requests (default 0.4)")
    ap.add_argument("--cache", default="bce_cache", help="Cache directory (default ./bce_cache)")
    ap.add_argument("--refresh", action="store_true", help="Ignore the cache and re-download")
    ap.add_argument("--top", type=int, default=15, help="Rows to show in head-to-head tables")
    ap.add_argument("--min-meetings", type=int, default=3, help="Minimum meetings for best/worst matchup lists")
    ap.add_argument("--h2h-by", choices=["dancer", "couple"], default="dancer",
                    help="Head-to-head per individual dancer (default) or per couple/entry")
    ap.add_argument("--out", help="Directory to write events.csv, head_to_head.csv and summary.json")
    ap.add_argument("--plot", action="store_true", help="Save a percentile-over-time chart (needs matplotlib)")
    args = ap.parse_args()

    while not args.aid and not norm(args.name or ""):
        try:
            args.name = input("Enter the dancer's name or dancer ID number: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nNothing entered; exiting.")
        if not norm(args.name or ""):
            print("Please type a name (e.g. Jane Smith) or a dancer ID (e.g. 10062).")
    if args.name and args.name.strip().isdigit() and not args.aid:
        args.aid, args.name = int(args.name.strip()), None
    if not args.aid:
        print("Searching by name reads every event on the site, which can take a few hours the first time.\n"
              "For a quick search, use the dancer's ID instead (see --help).", file=sys.stderr)
    fetcher = Fetcher(args.cache, args.delay, args.refresh)

    data = collect(args.name, fetcher, fuzzy=args.fuzzy, partner=args.partner, aid=args.aid,
                   cids=parse_cids(args.cids) if args.cids else None, max_cid=args.max_cid,
                   workers=args.workers, progress=lambda stage, i, n, msg: progress(msg))
    print(file=sys.stderr)
    who = args.name or f"dancer {args.aid}"
    if data["status"] == "bad_aid":
        print(f"Couldn't open the results page for dancer ID {args.aid}. Check the number and your connection.")
        return
    if data["status"] == "no_aid_comps":
        print(f"Dancer ID {args.aid} has no competition results listed on the site"
              + (" in the comp ids you gave." if args.cids else "."))
        return
    if data["status"] == "no_comps":
        print("Couldn't load any competition results. Check your internet connection and try again.")
        return
    if data["status"] == "no_events":
        print(f"Read {data['events_scanned']} events but found no results for {who}.")
        if data["suggestions"]:
            print("Similar names in the results: " + ", ".join(data["suggestions"]))
        print("Check the spelling as it appears on the site, or try --fuzzy.")
        return
    args.name = data["name"] or who
    if data.get("alternatives"):
        print(f"Showing {args.name}. Also in every one of these events: {', '.join(data['alternatives'])}.\n"
              f"If you meant one of them, run again with their name too, e.g.  --aid {args.aid} \"{data['alternatives'][0]}\"\n")
    records, raw_events, spellings = data["records"], data["raw_events"], data["spellings"]

    # ---------------- Report ----------------
    s = summarize(records)
    comps_attended = sorted({(r.cid, r.comp, r.date) for r in records})
    dates = [d for _, _, d in comps_attended if d]
    print("=" * 78)
    print(f"  {args.name}: competition history on ballroomcompexpress.com")
    if spellings - {args.name}:
        print(f"  Matched as: {', '.join(sorted(spellings))}")
    if dates:
        print(f"  {min(dates)} to {max(dates)}")
    print("=" * 78)
    print(f"Comps: {len(comps_attended)}   Events: {s['events']}   Wins: {s['wins']}   "
          f"Top 3: {s['podiums']}   Finals: {s['finals']} ({round(100 * s['finals'] / s['events'])}%)")
    print(f"Average place: {fmt(s['avg_place'])}   Median place: {fmt(s['median_place'])}   "
          f"Average field size: {fmt(s['avg_field'])}")
    print(f"Average percentile vs. field: {fmt(s['avg_pct'], '%')}  "
          "(100% = won, 0% = last; share of the field finished ahead of)\n")

    breakdown(records, lambda r: r.style, "Results by style")
    breakdown(records, lambda r: r.level, "Results by level")
    breakdown(records, lambda r: r.category, "Results by category")
    breakdown(records, lambda r: r.division, "Results by division")
    breakdown(records, lambda r: r.partner or "(solo)", "Results by partner")

    # Timeline
    by_comp = defaultdict(list)
    for r in records:
        by_comp[(r.cid, r.comp, r.date)].append(r)
    rows, series = [], []
    for (cid, name, date), rs in sorted(by_comp.items()):
        cs = summarize(rs)
        rows.append([name[:40], date or "?", cs["events"], cs["wins"], cs["finals"], cs["avg_place"], cs["avg_pct"]])
        if cs["avg_pct"] is not None:
            series.append((date or f"cid {cid}", name, cs["avg_pct"]))
    print("== Timeline (ordered by comp id, which tracks when comps were created) ==")
    print_table(["Comp", "Date", "Events", "Wins", "Finals", "Avg Pl", "Avg Pct"], rows)
    slope = linear_slope([p for _, _, p in series])
    if slope is not None:
        trend = "improving" if slope > 1 else "declining" if slope < -1 else "roughly flat"
        print(f"Trend: {slope:+.1f} percentile points per comp ({trend}).\n")

    # Best results
    best = sorted([r for r in records if r.place is not None],
                  key=lambda r: (r.place, -(r.entries or 0)))[:10]
    print("== Best results ==")
    print_table(["Event", "Comp", "Place", "Of"],
                [[r.event[:50], r.comp[:28], r.place, r.entries] for r in best])

    # Head-to-head
    h2h = {}
    for rec, results in raw_events:
        my_place = rec.place
        if my_place is None:
            continue
        own = {norm(p) for p in split_people(rec.entry)}
        for other, res in results.items():
            if other == rec.entry or res["place"] is None:
                continue
            opponents = [other] if args.h2h_by == "couple" else split_people(other)
            for opp in opponents:
                k = norm(opp)
                if not k or k in own:
                    continue
                h = h2h.setdefault(k, {"name": opp, "meetings": 0, "wins": 0, "losses": 0,
                                       "ties": 0, "finals_together": 0})
                h["meetings"] += 1
                if my_place < res["place"]:
                    h["wins"] += 1
                elif my_place > res["place"]:
                    h["losses"] += 1
                else:
                    h["ties"] += 1
                if rec.made_final and res["made_final"]:
                    h["finals_together"] += 1
    for h in h2h.values():
        decided = h["wins"] + h["losses"]
        h["win_pct"] = round(100 * h["wins"] / decided, 1) if decided else None

    def h2h_rows(items):
        return [[h["name"][:38], h["meetings"], f"{h['wins']}-{h['losses']}-{h['ties']}",
                 fmt(h["win_pct"], "%"), h["finals_together"]] for h in items]

    hdr = ["Opponent" if args.h2h_by == "dancer" else "Opponent entry", "Met", "W-L-T", "Win %", "Finals tog."]
    hs = list(h2h.values())
    print(f"== Head-to-head: most frequent opponents ({len(hs)} faced in total) ==")
    print_table(hdr, h2h_rows(sorted(hs, key=lambda h: (-h["meetings"], h["name"]))[:args.top]))
    qualified = [h for h in hs if h["meetings"] >= args.min_meetings and h["win_pct"] is not None]
    if qualified:
        print(f"== Toughest matchups (min {args.min_meetings} meetings) ==")
        print_table(hdr, h2h_rows(sorted(qualified, key=lambda h: (h["win_pct"], -h["meetings"]))[:args.top]))
        print(f"== Most dominant matchups (min {args.min_meetings} meetings) ==")
        print_table(hdr, h2h_rows(sorted(qualified, key=lambda h: (-h["win_pct"], -h["meetings"]))[:args.top]))
    tot_w = sum(h["wins"] for h in hs)
    tot_l = sum(h["losses"] for h in hs)
    if tot_w + tot_l:
        print(f"Overall head-to-head: {tot_w} wins, {tot_l} losses "
              f"({100 * tot_w / (tot_w + tot_l):.1f}% of opponents beaten).\n")

    # ---------------- Outputs ----------------
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "events.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
            w.writeheader()
            for r in records:
                row = asdict(r)
                row["dances"] = ", ".join(row["dances"])
                w.writerow(row)
        with open(out / "head_to_head.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["opponent", "meetings", "wins", "losses", "ties", "win_pct", "finals_together"])
            for h in sorted(hs, key=lambda h: -h["meetings"]):
                w.writerow([h["name"], h["meetings"], h["wins"], h["losses"], h["ties"],
                            h["win_pct"], h["finals_together"]])
        (out / "summary.json").write_text(json.dumps({
            "dancer": args.name, "matched_as": sorted(spellings), "summary": s,
            "comps": [{"cid": c, "name": n, "date": d} for c, n, d in comps_attended],
        }, indent=2), encoding="utf-8")
        print(f"Wrote {out / 'events.csv'}, {out / 'head_to_head.csv'}, {out / 'summary.json'}")

    if args.plot and series:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("--plot needs matplotlib (pip install matplotlib)")
        else:
            fig, ax = plt.subplots(figsize=(max(6, len(series) * 0.6), 4))
            ax.plot(range(len(series)), [p for _, _, p in series], marker="o")
            ax.set_xticks(range(len(series)))
            ax.set_xticklabels([n[:18] for _, n, _ in series], rotation=45, ha="right", fontsize=8)
            ax.set_ylim(0, 105)
            ax.set_ylabel("Avg percentile vs. field")
            ax.set_title(f"{args.name}: performance by comp")
            ax.grid(alpha=0.3)
            fig.tight_layout()
            path = Path(args.out or ".") / "percentile_trend.png"
            fig.savefig(path, dpi=150)
            print(f"Saved chart to {path}")

    print(f"(Pages downloaded this run: {fetcher.network_hits}; cache: {Path(args.cache).resolve()})")


if __name__ == "__main__":
    main()
