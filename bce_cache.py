"""Resumable historical population and weekly refresh, sharing the web fetcher."""
import argparse
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import bce_analyze as core
from bce_store import ResultsStore


def weekly_slot(now):
    """Most recent Saturday at 23:59, expressed in the supplied local timezone."""
    slot = (now - timedelta(days=(now.weekday() - 5) % 7)).replace(hour=23, minute=59, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=7)


def historical(comp, today):
    value = comp.get("end_date") or comp.get("date")
    try:
        return bool(value) and (today - datetime.fromisoformat(value).date()).days >= 30
    except (ValueError, TypeError):
        return False


class CacheMaintainer:
    def __init__(self, fetcher, busy=lambda: False, delay=2.0, zone="America/Chicago", log=print):
        self.fetcher = fetcher
        self.store = fetcher.store
        self.busy = busy
        self.delay = max(0, delay)
        self.zone = ZoneInfo(zone)
        self.stop = threading.Event()
        self.log = log
        self._last_request = 0.0

    def _yield(self):
        while self.busy() and not self.stop.wait(.25):
            pass
        if self.stop.is_set():
            raise core.Cancelled()

    def _get(self, url, refresh=False, max_age=None, post_data=None, **options):
        self._yield()
        # Extra background pacing applies only to actual network work, not disk reads.
        key = url if post_data is None else url + "?__post=" + core.urlencode(sorted(post_data.items()))
        path = self.fetcher._path(key)
        fresh = path.exists() and (max_age is None or time.time() - path.stat().st_mtime < max_age)
        if refresh or not fresh:
            if self.stop.wait(max(0, self._last_request + self.delay - time.monotonic())):
                raise core.Cancelled()
            self._yield()
            self._last_request = time.monotonic()
        kwargs = {"use_cache": not refresh, "max_age": max_age}
        kwargs.update(options)
        if post_data is not None:
            kwargs["post_data"] = post_data
        body = self.fetcher.get(url, **kwargs)
        if body is None:
            miss = path.with_suffix(".miss")
            if not miss.exists() or miss.read_text().strip() not in ("400", "404", "410"):
                raise ValueError("The upstream results source is unavailable or declining requests; background downloads will retry in an hour.")
        return body

    def refresh_competition(self, cid, metadata, cycle_start, today, force=False):
        previous = self.store.competition(cid)
        if previous and not force:
            if previous["frozen"] or previous["refreshed"] >= cycle_start:
                return True
        old = historical(metadata or (previous["data"] if previous else {}), today)
        refresh = force or bool(previous and previous["refreshed"])
        html = self._get(f"{core.RESULTS_URL}?cid={cid}", refresh=refresh,
                         max_age=None if old else core.COMP_MAX_AGE)
        if html is None:
            # Confirmed unavailable competition IDs are checked again next week.
            miss = self.fetcher._path(f"{core.RESULTS_URL}?cid={cid}").with_suffix(".miss")
            if miss.exists() and miss.read_text().strip() in ("400", "404", "410"):
                self.store.put_competition({"cid": cid, "name": f"Comp {cid}", "events": []}, complete=True)
                return True
            return False
        comp = core.parse_comp_page(html, cid)
        for key in ("name", "date", "end_date"):
            comp[key] = metadata.get(key) or comp.get(key) or (previous["data"].get(key) if previous else None)
        if comp["events"] and not comp.get("date"):
            # Older result pages can omit dates. The public competition search supplies
            # archive dates; match the exact competition ID rather than guessing by title.
            body = self._get(core.BASE + "php/searchCompsAndDancers.php", post_data={"query": comp["name"]})
            try:
                matches = json.loads(body) if body else []
            except ValueError:
                matches = []
            if isinstance(matches, list):
                for match in matches:
                    if isinstance(match, dict) and match.get("type") == "comp" and str(match.get("compid")) == str(cid):
                        comp["date"] = core.parse_date(str(match.get("daterange", "")))
                        comp["end_date"] = core.parse_end_date(str(match.get("daterange", "")))
                        break
        self.store.put_competition(comp)
        old = historical(comp, today)
        complete = True
        for event in comp["events"]:
            self._yield()
            updated = self.store.event_updated(cid, event["eid"])
            if not force and updated and (not refresh or updated >= cycle_start):
                continue
            # Old competitions get one final network refresh when crossing the cutoff.
            body = self._get(event["url"], refresh=refresh,
                             max_age=None if old else core.COMP_MAX_AGE)
            if body is None:
                complete = False
                continue
            payload = core.parsed_event(body)
            if not payload[0] and "eventinfo" not in core.js_vars(body):
                complete = False
                continue
            self.store.put_event(cid, event["eid"], payload,
                                 (core.norm(p) for entry in payload[0] for p in core.split_people(entry)))
            self.store.set_meta("refresh_status", {"state": "running", "competition": cid,
                                "event": event["eid"], "updated_at": time.time()})
        if complete:
            self.store.put_competition(comp, complete=True, frozen=old and bool(comp["events"]))
        return complete

    def run_cycle(self, now=None):
        now = now or datetime.now(self.zone)
        slot = weekly_slot(now).isoformat()
        cycle = self.store.get_meta("refresh_cycle")
        if not cycle or cycle.get("slot") != slot:
            cycle = {"slot": slot, "started": time.time()}
            self.store.set_meta("refresh_cycle", cycle)
        maintainer = self

        class IndexFetcher:
            def get(self, url, **kwargs):
                # One index refresh per cycle; keep successful index fetches on resume.
                return maintainer._get(url, max_age=max(1, time.time() - cycle["started"]))

        metadata = core.discover_comps(IndexFetcher())
        if not metadata:
            raise ValueError("Competition discovery returned no IDs; keeping the existing results index.")
        for cid, known in self.store.known_competition_metadata().items():
            metadata.setdefault(cid, known)
        # The public listing is recent-only. Probe the bounded historical ID range once;
        # successful old competitions are frozen and unavailable IDs are checkpointed.
        ids = list(range(max(metadata), 0, -1))
        self.log(f"Results cache: checking up to {len(ids)} competition IDs; visitor searches have priority.")
        failures = 0
        for cid in ids:
            if not self.refresh_competition(cid, metadata.get(cid, {}), cycle["started"], now.date()):
                failures += 1
        # Refresh known dancer membership weekly without reparsing indexed event results.
        class ProfileFetcher:
            store = maintainer.store
            refresh = False

            def get(self, url, **kwargs):
                return maintainer._get(url, refresh=not kwargs.get("use_cache", True),
                                       max_age=kwargs.get("max_age"), post_data=kwargs.get("post_data"),
                                       **{key: kwargs[key] for key in ("cache_misses", "validate") if key in kwargs})

        for aid in self.store.profile_ids():
            self._yield()
            checkpoint = f"profile_refresh_{aid}"
            if self.store.get_meta(checkpoint, 0) >= cycle["started"]:
                continue
            result = core.collect("", ProfileFetcher(), aid=aid, workers=1, refresh_profile=True,
                         progress=lambda *args: self._yield())
            if result["status"] in ("ok", "no_events", "no_aid_comps"):
                self.store.set_meta(checkpoint, time.time())
            else:
                failures += 1
        if failures:
            self.store.set_meta("refresh_status", {"state": "partial", "failed_competitions": failures, "updated_at": time.time()})
            return False
        self.store.set_meta("last_complete_slot", slot)
        self.store.set_meta("refresh_status", {"state": "complete", "updated_at": time.time()})
        self.log("Results cache: historical population / weekly refresh complete.")
        return True

    def refresh_o2cm(self, slot):
        if self.store.get_meta("o2cm_last_slot") == slot or self.store.get_meta("o2cm_retry_after", 0) > time.time():
            return
        worker = self

        class Fetcher:
            store = worker.store

            def get(self, url, **kwargs):
                return worker._get(url, **kwargs)

        try:
            import bce_o2cm
            bce_o2cm.refresh_known(Fetcher(), progress=lambda *args: self._yield())
            self.store.set_meta("o2cm_last_slot", slot)
            self.store.set_meta("o2cm_refresh_status", {"state": "complete", "updated_at": time.time()})
        except core.Cancelled:
            raise
        except Exception as exc:
            self.log(f"O2CM refresh postponed: {exc}")
            self.store.set_meta("o2cm_retry_after", time.time() + 3600)
            self.store.set_meta("o2cm_refresh_status", {"state": "error", "error": str(exc), "updated_at": time.time()})

    def run(self):
        retry_after = 0
        while not self.stop.is_set():
            try:
                request = Path(self.fetcher.cache_dir) / "refresh-request.json"
                if request.exists():
                    ids = json.loads(request.read_text())
                    request.unlink()
                    for cid in ids:
                        self.refresh_competition(int(cid), {}, time.time(), datetime.now(self.zone).date(), force=True)
                slot = weekly_slot(datetime.now(self.zone)).isoformat()
                # Each provider has an independent checkpoint and failure/backoff state.
                self.refresh_o2cm(slot)
                if time.time() >= retry_after and self.store.get_meta("last_complete_slot") != slot:
                    if not self.run_cycle():
                        retry_after = time.time() + 3600
            except core.Cancelled:
                break
            except Exception as exc:
                self.log(f"Results cache refresh paused after error: {exc}")
                self.store.set_meta("refresh_status", {"state": "error", "error": str(exc), "updated_at": time.time()})
                retry_after = time.time() + 3600
            self.stop.wait(30)


def main():
    parser = argparse.ArgumentParser(description="Inspect the shared results cache or request a competition refresh.")
    parser.add_argument("--cache", default="/data/cache")
    parser.add_argument("--refresh", type=int, nargs="+", help="Competition IDs to refresh, including frozen competitions")
    args = parser.parse_args()
    if args.refresh:
        if any(cid <= 0 for cid in args.refresh):
            parser.error("Competition IDs must be positive.")
        target = Path(args.cache) / "refresh-request.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(args.refresh))
        temporary.replace(target)
        print("Refresh requested; the running web app will process it in the background.")
    print(json.dumps(ResultsStore(args.cache).status(), indent=2))


if __name__ == "__main__":
    main()
