"""Exercise couple scope at the web job boundary, independent of provider filtering."""
import unittest
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from dataclasses import replace
from unittest.mock import patch

import bce_web as web
import bce_sources
from test_sources import result


class CoupleAnalysisTests(unittest.TestCase):
    def run_analysis(self, records, mode="couple", partner="Partner A"):
        data = result()
        data["raw_events"] = [(r, {r.entry: {"place": r.place, "made_final": True}}) for r in records]
        job = {"cancel": False}
        with patch.object(bce_sources, "collect", return_value=data), patch.dict(web.CONFIG, public=False):
            web.run_job("test-couple", job, dict(name="Sam Example", partner=partner,
                                                 analysis_mode=mode, source="all"))
        return job

    def test_exact_pair_only_across_both_providers(self):
        rec = result()["records"][0]
        records = [rec, replace(rec, source="o2cm", eid=2),
                   replace(rec, partner="Partner B", entry="Sam Example & Partner B"),
                   replace(rec, entry="Sam Example"),
                   replace(rec, entry="Sam Example & Partner A & Team Member")]
        job = self.run_analysis(records)
        self.assertEqual(job["state"], "done")
        data = job["result"]
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual({e["source"] for e in data["events"]}, {"bce", "o2cm"})
        self.assertEqual(data["display_name"], "Sam Example & Partner A")
        self.assertEqual(data["name"], "Sam Example")
        self.assertTrue(data["scope_limited"])

    def test_individual_preserves_other_partners_and_solo_results(self):
        rec = result()["records"][0]
        job = self.run_analysis([rec, replace(rec, partner="", entry="Sam Example")], mode="individual", partner="")
        self.assertEqual(len(job["result"]["events"]), 2)
        self.assertFalse(job["result"]["scope_limited"])
        self.assertEqual(job["result"]["display_name"], "Sam Example")

    def test_no_shared_results(self):
        job = self.run_analysis(result()["records"], partner="Someone Else")
        self.assertEqual(job["result"]["status"], "no_couple_results")
        self.assertEqual(job["result"]["events"], [])

    def test_resolved_id_cannot_be_its_own_partner(self):
        job = self.run_analysis([], partner="Sam Example")
        self.assertEqual(job["state"], "error")
        self.assertIn("two different dancers", job["error"])

    def test_normalized_exact_names(self):
        job = self.run_analysis(result()["records"], partner=" Pártner A ")
        self.assertEqual(len(job["result"]["events"]), 1)

    def test_start_validation_and_exact_matching(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        created = []
        def request(**changes):
            payload = dict(name="Sam Example", partner="Partner A", analysis_mode="couple", fuzzy=True)
            payload.update(changes)
            return urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/start",
                                   json.dumps(payload).encode(), {"Content-Type": "application/json"}), timeout=5)
        try:
            ready = threading.Event()
            with patch.dict(web.CONFIG, public=False), patch.object(web, "run_job", side_effect=lambda *args: ready.set()) as worker:
                for changes in ({"partner": ""}, {"partner": "123"}, {"partner": "Sám Example"}, {"analysis_mode": "unknown"}):
                    with self.subTest(changes=changes), self.assertRaises(HTTPError) as error:
                        request(**changes)
                    self.assertEqual(error.exception.code, 400)
                with request() as response:
                    created.append(json.load(response)["id"])
                self.assertTrue(ready.wait(2))
                params = worker.call_args.args[2]
                self.assertFalse(params["fuzzy"])
                self.assertEqual(params["source"], "all")
                self.assertEqual(params["analysis_mode"], "couple")
        finally:
            server.shutdown()
            server.server_close()
            for jid in created:
                web.JOBS.pop(jid, None)


if __name__ == "__main__":
    unittest.main()
