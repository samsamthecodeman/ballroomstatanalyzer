import json
import tempfile
import unittest
from pathlib import Path

from bce_partners import PartnerLeaderboard


class PartnerLeaderboardTests(unittest.TestCase):
    def test_distinct_partners_across_events_and_roles(self):
        board = PartnerLeaderboard()
        board.add_entries(["Alex García & Sam Example", "Sam Example & Taylor Doe", "Sam Example & Alex Garcia"])
        board.add_entries(["Sam Example & Taylor Doe", "Solo Dancer", "Sam Example & Sam Example"])
        self.assertEqual(board.snapshot()["names"], ["Sam Example"])
        self.assertEqual(board.snapshot()["partners"], 2)

    def test_ties_and_empty_results(self):
        board = PartnerLeaderboard()
        self.assertEqual(board.snapshot()["names"], [])
        board.add_entries(["Taylor Doe & Sam Example"])
        self.assertEqual(board.snapshot()["names"], ["Sam Example", "Taylor Doe"])
        self.assertEqual(board.snapshot()["tied"], 2)

    def test_bootstrap_from_existing_cache_without_fetching(self):
        board = PartnerLeaderboard()
        results = {"roundorder": ["1"], "1": {"final": 1, "partnershiporder": ["12"], "12": {"place": 1}}}
        dancers = {"12": {"leaderfname": "Sam", "leaderlname": "Example", "followerfname": "Taylor", "followerlname": "Doe"}}
        html = "".join(f"var {name} = JSON.parse('{json.dumps(value)}');" for name, value in (("results", results), ("dancers", dancers)))
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "event.html").write_text(html, encoding="utf-8")
            Path(directory, "partial.html").write_text("<html>Incomplete page", encoding="utf-8")
            board.load_cache(directory)
        self.assertTrue(board.snapshot()["ready"])
        self.assertEqual(board.snapshot()["partners"], 1)
        self.assertEqual(board.snapshot()["names"], ["Sam Example", "Taylor Doe"])


if __name__ == "__main__":
    unittest.main()
