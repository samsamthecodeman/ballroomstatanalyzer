import csv
import io
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import bce_export
import bce_web


def sample_event(**changes):
    event = dict(date="2026-10-10", cid=101, eid=12, comp="Fall Classic & Collegiate Open",
                 event="Mixed Follows Collegiate Newcomer International Standard Quickstep",
                 category="Mixed proficiency – follower judged", role="Follower", partner="Alex García",
                 place=1, entries=18, made_final=True, percentile=100, style="International Standard",
                 level="Newcomer", division="Mixed Am", age="Collegiate", dances=["Quickstep"],
                 entry="Alex García & Zoë Example", url="https://ballroomcompexpress.com/results.php?cid=101&eid=12")
    return {**event, **changes}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.result = dict(name="Zoë Example", aid=123, events=[sample_event(), sample_event(eid=13, place=None, partner="", style="American Smooth")])

    def test_filters_match_page_and_reject_invalid_filters(self):
        self.assertEqual(len(bce_export.select_events(self.result, {})), 2)
        self.assertEqual(len(bce_export.select_events(self.result, {"style": "International Standard"})), 1)
        self.assertEqual(bce_export.select_events(self.result, {"partner": "(solo)"})[0]["eid"], 13)
        for invalid in ([], {"unknown": "x"}, {"level": []}):
            with self.assertRaises(ValueError):
                bce_export.select_events(self.result, invalid)

    def test_csv_unicode_quotes_newlines_and_formula_safety(self):
        events = [sample_event(comp='Cup, "Final"\nDay 2', partner="=HYPERLINK(1)", place=None)]
        report = bce_export.csv_report(events)
        self.assertTrue(report.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.DictReader(io.StringIO(report.decode("utf-8-sig"))))
        self.assertEqual(rows[0]["Competition"], events[0]["comp"])
        self.assertEqual(rows[0]["Partner"], "'=HYPERLINK(1)")
        self.assertEqual(rows[0]["Entry"], events[0]["entry"])
        self.assertEqual(rows[0]["Place"], "")
        self.assertEqual(rows[0]["Made final"], "Yes")
        self.assertEqual(rows[0]["Dances"], "Quickstep")
        self.assertEqual(len(list(csv.reader(io.StringIO(bce_export.csv_report([]).decode("utf-8-sig"))))), 1)

    def test_exclude_uncontested_preserves_contested_and_unknown_fields(self):
        result = {"events": [sample_event(eid=i, entries=count) for i, count in enumerate((1, 2, 18, None, 0))]}
        selected = bce_export.select_events(result, {"excludeUncontested": True})
        self.assertEqual([e["entries"] for e in selected], [2, 18, None, 0])
        self.assertEqual(len(bce_export.select_events(result, {"excludeUncontested": False})), 5)
        self.assertEqual(len(bce_export.select_events(result, {"excludeUncontested": True, "level": "Newcomer"})), 4)
        self.assertEqual(bce_export.select_events(result, {"excludeUncontested": True, "level": "Bronze"}), [])
        with self.assertRaises(ValueError):
            bce_export.select_events(result, {"excludeUncontested": "true"})

    def test_exclude_three_couple_podiums_matches_exact_field_and_placement(self):
        events = [sample_event(eid=i, entries=3, place=place) for i, place in enumerate((1, 2, 3, None, 4))]
        events += [sample_event(eid=5, entries=4, place=3), sample_event(eid=6, entries=2, place=1),
                   sample_event(eid=7, entries=None, place=1), sample_event(eid=8, entries=1, place=1),
                   sample_event(eid=9, entries=3, place=1, category="Solo"),
                   sample_event(eid=10, entries=3, place=1, role="Solo")]
        result = {"events": events}
        selected = bce_export.select_events(result, {"excludeThreeCouplePodiums": True})
        self.assertEqual([e["eid"] for e in selected], list(range(3, 11)))
        self.assertEqual(len(bce_export.select_events(result, {"excludeThreeCouplePodiums": False})), 11)
        combined = bce_export.select_events(result, {"excludeThreeCouplePodiums": True, "excludeUncontested": True})
        self.assertNotIn(8, [e["eid"] for e in combined])
        with self.assertRaises(ValueError):
            bce_export.select_events(result, {"excludeThreeCouplePodiums": "true"})
        csv_rows = list(csv.DictReader(io.StringIO(bce_export.csv_report(selected).decode("utf-8-sig"))))
        self.assertEqual(len(csv_rows), len(selected))
        from pypdf import PdfReader
        pdf = bce_export.pdf_report(self.result, selected, {"excludeThreeCouplePodiums": True})
        self.assertIn("Top-3 finishes in 3-couple events: excluded", PdfReader(io.BytesIO(pdf)).pages[0].extract_text())

    def test_pdf_pagination_unicode_and_empty_selection(self):
        from pypdf import PdfReader
        events = [sample_event(eid=i, event=f"Event {i:03d}: " + sample_event()["event"]) for i in range(75)]
        report = bce_export.pdf_report(self.result, events, {"style": "International Standard"})
        reader = PdfReader(io.BytesIO(report))
        self.assertGreater(len(reader.pages), 1)
        text = "\n".join(page.extract_text() for page in reader.pages)
        for expected in ("Zoë Example", "Alex García", "Event 000", "Event 074", "75", "Style: International Standard"):
            self.assertIn(expected, text)
        for i, page in enumerate(reader.pages, 1):
            self.assertIn(f"Page {i}", page.extract_text())
            self.assertIn("Date / competition", page.extract_text())
        empty = PdfReader(io.BytesIO(bce_export.pdf_report(self.result, [], {})))
        self.assertIn("No events match", empty.pages[0].extract_text())

    def test_download_endpoint_and_access_checks(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), bce_web.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        bce_web.JOBS["export-test"] = dict(visitor="127.0.0.1", state="done", finished=time.time(), result=self.result)
        bce_web.JOBS["other-test"] = dict(visitor="other-visitor", state="done", finished=time.time(), result=self.result)
        thread.start()
        def request(**changes):
            payload = {"id": "export-test", "format": "csv", "filters": {"style": "International Standard"}, **changes}
            return urlopen(Request(f"http://127.0.0.1:{server.server_port}/api/export", json.dumps(payload).encode(), {"Content-Type": "application/json"}))
        try:
            with request() as response:
                self.assertIn("attachment;", response.headers["Content-Disposition"])
                self.assertEqual(len(list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))), 1)
            with request(format="pdf") as response:
                self.assertEqual(response.headers["Content-Type"], "application/pdf")
                self.assertTrue(response.read().startswith(b"%PDF-"))
            for changes, code in (({"format": "exe"}, 400), ({"id": "missing"}, 404),
                                  ({"id": "other-test"}, 404), ({"filters": []}, 400)):
                with self.subTest(changes=changes), self.assertRaises(HTTPError) as error:
                    request(**changes)
                self.assertEqual(error.exception.code, code)
        finally:
            server.shutdown()
            server.server_close()
            bce_web.JOBS.pop("export-test", None)
            bce_web.JOBS.pop("other-test", None)


if __name__ == "__main__":
    unittest.main()
