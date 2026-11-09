import json
import tempfile
import time
import unittest
import threading
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import bce_analyze as core
from bce_cache import CacheMaintainer, historical, weekly_slot
from bce_store import ResultsStore


def event_html(place=1, eid=12):
    values = {
        "eventinfo": {"eventid": eid, "displayname": "Mixed Follows Collegiate Newcomer International Standard Quickstep"},
        "dancers": {"1": {"leaderfname": "Alex", "leaderlname": "Example", "followerfname": "Sam", "followerlname": "Example", "judgedEntity": "follower"}},
        "results": {"roundorder": ["1"], "1": {"final": 1, "partnershiporder": ["1"], "1": {"place": place}}},
    }
    return "".join(f"var {name} = JSON.parse('{json.dumps(value)}');" for name, value in values.items())


def comp_html(eids=(12,), date_text="October 1, 2026"):
    return f"<h1>Results for Example Cup</h1><p>{date_text}</p>" + "".join(
        f'<div class="event-link" id="evt{eid}">Newcomer Quickstep</div>' for eid in eids)


INDEX = '<div class="comp-list"><div id="cmp1">Example Cup<br>October 1, 2026</div></div>'


class MemoryFetcher(core.Fetcher):
    def __init__(self, directory, pages):
        super().__init__(directory, delay=0, refresh=False)
        self.pages = pages
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        body = self.pages.get(url)
        if body is not None:
            self._path(url).write_text(body, encoding="utf-8")
        else:
            self._path(url).with_suffix(".miss").write_text("404", encoding="ascii")
        return body


class ResultsCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_warm_search_matches_original_and_requires_no_html_or_network(self):
        pages = {core.RESULTS_URL: INDEX, core.BASE + "index.php": INDEX,
                 core.RESULTS_URL + "?aid=123": "<h2>Sam Example</h2>" + INDEX,
                 core.RESULTS_URL + "?aid=123&cid=1": comp_html(),
                 core.RESULTS_URL + "?cid=1&eid=12": event_html()}
        fetcher = MemoryFetcher(self.directory.name, pages)
        first = core.collect("", fetcher, aid=123)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["name"], "Sam Example")
        self.assertTrue(fetcher.calls)
        fetcher.get = Mock(side_effect=AssertionError("Warm search must read the index, not fetch HTML"))
        warm = core.collect("", fetcher, aid=123)
        self.assertEqual(first, warm)
        self.assertEqual(fetcher.store.find_person_events("sam example"), [(1, 12)])
        # A background correction becomes visible without reparsing HTML or changing the profile.
        corrected = core.parsed_event(event_html(place=2))
        fetcher.store.put_event(1, 12, corrected, ["sam example"])
        self.assertEqual(core.collect("", fetcher, aid=123)["records"][0].place, 2)
        import bce_web
        job = {"state": "running", "cancel": False}
        with patch.object(bce_web, "FETCHER", fetcher), patch.dict(bce_web.CONFIG, {"public": True}):
            bce_web.run_job("cache-test", job, {"aid": 123})
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"]["events"][0]["place"], 2)
        # Weekly membership updates bypass a still-fresh profile and overview cache.
        fetcher.get = lambda url, **kwargs: pages.get(url)
        with patch.object(fetcher, "get", wraps=fetcher.get) as get:
            core.collect("", fetcher, aid=123, refresh_profile=True)
            overview_calls = [call for call in get.call_args_list if call.args[0].endswith("?aid=123")]
            self.assertEqual(overview_calls[0].kwargs["max_age"], 0)

    def test_persistence_and_parser_version_invalidation(self):
        store = ResultsStore(self.directory.name)
        store.put_event(1, 12, core.parsed_event(event_html()), ["sam example"])
        self.assertIn((1, 12), ResultsStore(self.directory.name).get_events([(1, 12)]))
        with store.connect() as db:
            db.execute("UPDATE events SET version=0")
        self.assertEqual(store.get_events([(1, 12)]), {})

    def membership_fixture(self):
        pages = {core.RESULTS_URL: INDEX, core.BASE + "index.php": INDEX,
                 core.RESULTS_URL + "?aid=123": '<h2>Sam Example</h2>' + INDEX,
                 core.RESULTS_URL + "?aid=123&cid=1": comp_html(),
                 core.RESULTS_URL + "?cid=1&eid=12": event_html(),
                 core.RESULTS_URL + "?aid=123&cid=2": comp_html((13,), 'November 7, 2026'),
                 core.RESULTS_URL + "?cid=2&eid=13": event_html(eid=13)}
        fetcher = MemoryFetcher(self.directory.name, pages)
        core.collect('', fetcher, aid=123)
        comp = core.parse_comp_page(comp_html((13,), 'November 7, 2026'), 2)
        comp.update(date='2026-11-07', end_date='2026-11-01')
        fetcher.store.put_competition(comp, complete=True)
        return fetcher

    def test_refresh_discovers_recent_results_missing_from_dancer_overview(self):
        fetcher = self.membership_fixture()
        worker = CacheMaintainer(fetcher, delay=0)
        self.assertEqual(worker.refresh_profiles(time.time(), date(2026, 11, 8)), 0)
        self.assertEqual({c['cid'] for c in fetcher.store.get_profile(123)['comps']}, {1, 2})
        self.assertTrue(any(url.endswith('?aid=123&cid=2') and options['max_age'] == 0 for url, options in fetcher.calls))
        # Repeating a profile refresh without the recent-set hint cannot erase verified results.
        data = core.collect('', fetcher, aid=123, refresh_profile=True)
        self.assertEqual({e.cid for e in data['records']}, {1, 2})
        fetcher.get = Mock(side_effect=AssertionError('Warm visitor searches must stay offline'))
        self.assertEqual(len(core.collect('', fetcher, aid=123)['records']), 2)

    def test_failed_recent_listing_preserves_history_and_is_not_checkpointed(self):
        fetcher = self.membership_fixture()
        core.collect('', fetcher, aid=123, refresh_profile=True, recent_competitions=fetcher.store.competition_metadata())
        fetcher.pages.pop(core.RESULTS_URL + '?aid=123&cid=2')
        worker = CacheMaintainer(fetcher, delay=0)
        self.assertEqual(worker.refresh_profiles(time.time(), date(2026, 11, 8)), 1)
        self.assertEqual({c['cid'] for c in fetcher.store.get_profile(123)['comps']}, {1, 2})
        self.assertIsNone(fetcher.store.get_meta('profile_membership_refresh_123'))

    def test_recent_probes_are_bounded_and_manual_refresh_ignores_weekly_checkpoint(self):
        fetcher = self.membership_fixture()
        for cid, day in [(3, '2026-11-09'), (4, '2025-01-01')]:
            comp = core.parse_comp_page(comp_html(), cid)
            comp.update(date=day, end_date=day)
            fetcher.store.put_competition(comp, complete=True)
        worker = CacheMaintainer(fetcher, delay=0)
        start = time.time()
        with patch.object(core, 'collect', return_value={'status':'ok'}) as collect:
            self.assertEqual(worker.refresh_profiles(start, date(2026,11,8)), 0)
            self.assertEqual(set(collect.call_args.kwargs['recent_competitions']), {2})
            self.assertEqual(worker.refresh_profiles(start, date(2026,11,8)), 0)
            self.assertEqual(collect.call_count, 1)
            worker.refresh_profiles(start, date(2026,11,8), cids={4}, checkpointed=False)
            self.assertEqual(set(collect.call_args.kwargs['recent_competitions']), {4})
            self.assertEqual(collect.call_count, 2)

    def test_old_competition_freezes_but_manual_refresh_can_correct_it(self):
        url = core.RESULTS_URL + "?cid=1&eid=12"
        fetcher = MemoryFetcher(self.directory.name, {core.RESULTS_URL + "?cid=1": comp_html(), url: event_html()})
        worker = CacheMaintainer(fetcher, delay=0)
        self.assertTrue(worker.refresh_competition(1, {}, time.time(), date(2026, 11, 5)))
        self.assertTrue(fetcher.store.competition(1)["frozen"])
        count = len(fetcher.calls)
        worker.refresh_competition(1, {}, time.time() + 8 * 86400, date(2026, 11, 13))
        self.assertEqual(len(fetcher.calls), count)
        fetcher.pages[url] = event_html(place=2)
        worker.refresh_competition(1, {}, time.time(), date(2026, 11, 5), force=True)
        self.assertEqual(fetcher.store.get_events([(1, 12)])[1, 12][0]["Alex Example & Sam Example"]["place"], 2)

    def test_recent_competition_gets_a_final_refresh_after_thirty_days(self):
        fetcher = MemoryFetcher(self.directory.name, {core.RESULTS_URL + "?cid=1": comp_html(),
                                core.RESULTS_URL + "?cid=1&eid=12": event_html()})
        worker = CacheMaintainer(fetcher, delay=0)
        worker.refresh_competition(1, {}, time.time(), date(2026, 10, 20))
        self.assertFalse(fetcher.store.competition(1)["frozen"])
        worker.refresh_competition(1, {}, time.time() + 1, date(2026, 11, 1))
        self.assertTrue(fetcher.store.competition(1)["frozen"])
        self.assertTrue(fetcher.calls[-1][1]["use_cache"] is False)

    def test_partial_competition_resumes_without_refetching_successful_events(self):
        first_url = core.RESULTS_URL + "?cid=1&eid=12"
        second_url = core.RESULTS_URL + "?cid=1&eid=13"
        fetcher = MemoryFetcher(self.directory.name, {core.RESULTS_URL + "?cid=1": comp_html((12, 13)), first_url: event_html()})
        worker = CacheMaintainer(fetcher, delay=0)
        started = time.time()
        self.assertFalse(worker.refresh_competition(1, {}, started, date(2026, 11, 5)))
        self.assertEqual(fetcher.store.competition(1)["refreshed"], 0)
        fetcher.pages[second_url] = event_html(eid=13)
        self.assertTrue(worker.refresh_competition(1, {}, started, date(2026, 11, 5)))
        self.assertEqual(sum(url == first_url for url, _ in fetcher.calls), 1)

    def test_failed_refresh_preserves_previous_results_and_remains_due(self):
        event_url = core.RESULTS_URL + "?cid=1&eid=12"
        fetcher = MemoryFetcher(self.directory.name, {core.RESULTS_URL + "?cid=1": comp_html(), event_url: event_html()})
        worker = CacheMaintainer(fetcher, delay=0)
        worker.refresh_competition(1, {}, time.time(), date(2026, 10, 20))
        previous = fetcher.store.competition(1)["refreshed"]
        del fetcher.pages[event_url]
        self.assertFalse(worker.refresh_competition(1, {}, time.time() + 1, date(2026, 11, 5)))
        self.assertFalse(fetcher.store.competition(1)["frozen"])
        self.assertEqual(fetcher.store.competition(1)["refreshed"], previous)
        self.assertIn((1, 12), fetcher.store.get_events([(1, 12)]))

    def test_end_dates_and_refresh_boundaries(self):
        cases = [("October 31 - November 1, 2026", "2026-10-31", "2026-11-01"),
                 ("October 23-25, 2026", "2026-10-23", "2026-10-25"),
                 ("December 31 - January 1, 2027", "2026-12-31", "2027-01-01"),
                 ("October 1, 2026", "2026-10-01", "2026-10-01")]
        for text, start, end in cases:
            self.assertEqual(core.parse_date(text), start)
            self.assertEqual(core.parse_end_date(text), end)
        self.assertFalse(historical({"date": "2026-10-01", "end_date": "2026-10-03"}, date(2026, 11, 1)))
        self.assertTrue(historical({"end_date": "2026-10-03"}, date(2026, 11, 2)))
        self.assertFalse(historical({}, date(2026, 11, 2)))
        self.assertFalse(historical({"date": "invalid"}, date(2026, 11, 2)))
        zone = ZoneInfo("America/Chicago")
        self.assertEqual(weekly_slot(datetime(2026, 11, 7, 23, 58, tzinfo=zone)).date(), date(2026, 10, 31))
        self.assertEqual(weekly_slot(datetime(2026, 11, 7, 23, 59, tzinfo=zone)).date(), date(2026, 11, 7))
        self.assertEqual(weekly_slot(datetime(2026, 11, 8, 12, tzinfo=zone)).date(), date(2026, 11, 7))

    def test_name_lookup_filters_competitions_and_preserves_distinct_ids(self):
        fetcher = Mock()
        fetcher.get.return_value = json.dumps([
            {"type": "comp", "name": "Example Cup"},
            {"type": "dancer", "acctid": "123", "fname": "Sam", "lname": "Example", "city": "Austin", "stateabbrev": "TX"},
            {"type": "dancer", "acctid": "124", "fname": "Sam", "lname": "Example", "city": "Dallas", "stateabbrev": "TX"},
            {"type": "dancer", "acctid": "invalid", "fname": "Unknown"},
        ])
        self.assertEqual([d["id"] for d in core.search_dancers("Sam", fetcher)], [123, 124])
        self.assertEqual(core.search_dancers("Sa", fetcher), [])
        fetcher.get.return_value = "Unexpected HTML"
        with self.assertRaises(ValueError):
            core.search_dancers("Sam", fetcher)

    def test_get_and_post_cache_keys_are_distinct_and_post_lookups_are_reused(self):
        fetcher = core.Fetcher(self.directory.name, delay=0, refresh=False)
        fetcher.session = Mock()
        fetcher.session.get.return_value = Mock(status_code=200, text="<html>Results</html>")
        fetcher.session.post.return_value = Mock(status_code=200, text='[{"type":"dancer","acctid":"123","fname":"Sam","lname":"Example"}]')
        url = core.BASE + "php/searchCompsAndDancers.php"
        self.assertEqual(core.search_dancers("Sam", fetcher)[0]["id"], 123)
        self.assertEqual(core.search_dancers("Sam", fetcher)[0]["id"], 123)
        self.assertEqual(fetcher.session.post.call_count, 1)
        self.assertEqual(fetcher.get(url), "<html>Results</html>")
        self.assertEqual(fetcher.session.get.call_count, 1)

    def test_background_stops_on_transient_upstream_failure(self):
        fetcher = MemoryFetcher(self.directory.name, {})
        fetcher.get = lambda *args, **kwargs: None
        worker = CacheMaintainer(fetcher, delay=0)
        with self.assertRaisesRegex(ValueError, "retry in an hour"):
            worker._get(core.RESULTS_URL)

    def test_cancelled_worker_does_not_fetch(self):
        fetcher = MemoryFetcher(self.directory.name, {})
        worker = CacheMaintainer(fetcher, delay=0)
        worker.stop.set()
        with self.assertRaises(core.Cancelled):
            worker._get(core.RESULTS_URL)
        self.assertEqual(fetcher.calls, [])

    def test_archived_dates_resolve_by_exact_competition_id(self):
        search_url = core.BASE + "php/searchCompsAndDancers.php"
        fetcher = MemoryFetcher(self.directory.name, {
            core.RESULTS_URL + "?cid=1": "<h1>Login</h1>" + comp_html(date_text=""),
            core.RESULTS_URL + "?cid=1&eid=12": event_html(),
            search_url: json.dumps([
                {"type": "comp", "compid": 2, "daterange": "November 1, 2026"},
                {"type": "comp", "compid": 1, "daterange": "October 1-2, 2025"},
            ]),
        })
        worker = CacheMaintainer(fetcher, delay=0)
        self.assertTrue(worker.refresh_competition(1, {}, time.time(), date(2026, 11, 5)))
        saved = fetcher.store.competition(1)
        self.assertEqual(saved["data"]["end_date"], "2025-10-02")
        self.assertEqual(saved["data"]["name"], "Example Cup")
        search_calls = [kwargs for url, kwargs in fetcher.calls if url == search_url]
        self.assertEqual(search_calls[0]["post_data"], {"query": "Example Cup"})
        self.assertTrue(saved["frozen"])

    def test_name_lookup_http_errors_do_not_block_future_lookups(self):
        import bce_web
        server = ThreadingHTTPServer(("127.0.0.1", 0), bce_web.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        bce_web.LOOKUP_RECENT.clear()
        def request(query):
            return urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/dancers?q={query}"))
        try:
            with patch.object(core, "search_dancers", side_effect=ValueError("Lookup unavailable")):
                with self.assertRaises(HTTPError) as error:
                    request("Sam")
                self.assertEqual(error.exception.code, 503)
            with patch.object(core, "search_dancers", return_value=[{"id": 123, "name": "Sam Example", "location": "Austin, TX"}]):
                with request("Sam") as response:
                    self.assertEqual(json.load(response)["dancers"][0]["id"], 123)
                with self.assertRaises(HTTPError) as error:
                    request("Sa")
                self.assertEqual(error.exception.code, 400)
                bce_web.LOOKUP_RECENT["127.0.0.1"] = [time.time()] * 20
                with self.assertRaises(HTTPError) as error:
                    request("Sam")
                self.assertEqual(error.exception.code, 429)
        finally:
            server.shutdown()
            server.server_close()
            bce_web.LOOKUP_RECENT.clear()

    def test_full_cycle_checkpoints_survive_worker_restart(self):
        event_url = core.RESULTS_URL + "?cid=1&eid=12"
        pages = {core.RESULTS_URL: INDEX, core.BASE + "index.php": INDEX,
                 core.RESULTS_URL + "?aid=123": "<h2>Sam Example</h2>" + INDEX,
                 core.RESULTS_URL + "?aid=123&cid=1": comp_html(),
                 core.RESULTS_URL + "?cid=1": comp_html(), event_url: event_html()}
        fetcher = MemoryFetcher(self.directory.name, pages)
        core.collect("", fetcher, aid=123)
        worker = CacheMaintainer(fetcher, delay=0, log=lambda message: None)
        self.assertTrue(worker.run_cycle(datetime(2026, 11, 5, 12, tzinfo=ZoneInfo("America/Chicago"))))
        self.assertEqual(fetcher.store.status()["refresh"]["state"], "complete")
        self.assertIsNotNone(fetcher.store.get_meta("profile_membership_refresh_123"))
        event_calls = sum(url == event_url for url, _ in fetcher.calls)
        worker = CacheMaintainer(fetcher, delay=0, log=lambda message: None)
        self.assertTrue(worker.run_cycle(datetime(2026, 11, 5, 13, tzinfo=ZoneInfo("America/Chicago"))))
        self.assertEqual(sum(url == event_url for url, _ in fetcher.calls), event_calls)


if __name__ == "__main__":
    unittest.main()
