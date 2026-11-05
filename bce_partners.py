"""A name-based partner leaderboard derived only from locally cached results."""
import threading
from collections import defaultdict
from pathlib import Path

import bce_analyze as core


class PartnerLeaderboard:
    def __init__(self):
        self._partners = defaultdict(set)
        self._names = {}
        self._lock = threading.Lock()
        self._ready = False

    def add_entries(self, entries):
        with self._lock:
            for entry in entries:
                people = core.split_people(entry)
                if len(people) != 2:
                    continue
                first, second = (core.norm(person) for person in people)
                if not first or not second or first == second:
                    continue
                self._names.setdefault(first, people[0])
                self._names.setdefault(second, people[1])
                self._partners[first].add(second)
                self._partners[second].add(first)

    def load_cache(self, directory):
        try:
            for path in Path(directory).glob("*.html"):
                try:
                    html = path.read_text(encoding="utf-8", errors="replace")
                    # Event results have either embedded rounds or legacy result tables.
                    parsed = core.parse_event_data(html)
                    if parsed:
                        self.add_entries(parsed[0])
                    else:
                        results, _ = core.compute_event_results(core.parse_event_page(html))
                        self.add_entries(results)
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    continue  # A partially written or older cached page must not stop startup.
        finally:
            with self._lock:
                self._ready = True

    def snapshot(self):
        with self._lock:
            count = max((len(partners) for partners in self._partners.values()), default=0)
            leaders = sorted((self._names[name] for name, partners in self._partners.items()
                              if len(partners) == count), key=str.casefold)
            return {"names": leaders[:3], "partners": count, "tied": len(leaders),
                    "ready": self._ready, "scope": "cached Comp Express results"}
