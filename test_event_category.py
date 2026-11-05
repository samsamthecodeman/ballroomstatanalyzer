import unittest

from bce_analyze import CAT_COUPLE, CAT_FOLLOW, CAT_LEAD, CAT_SOLO, event_category


class EventCategoryTests(unittest.TestCase):
    def test_mixed_role_titles(self):
        for role, expected in (
            ("Follow", CAT_FOLLOW), ("Follows", CAT_FOLLOW),
            ("Follower", CAT_FOLLOW), ("Followers", CAT_FOLLOW),
            ("Lead", CAT_LEAD), ("Leads", CAT_LEAD),
            ("Leader", CAT_LEAD), ("Leaders", CAT_LEAD),
        ):
            title = f"Mixed {role} Collegiate Newcomer International Standard Quickstep"
            for judged in (None, "entrant"):
                with self.subTest(title=title, judged=judged):
                    self.assertEqual(event_category(title, judged), expected)

    def test_existing_categories(self):
        cases = (
            ("Collegiate Newcomer International Standard Quickstep", CAT_COUPLE),
            ("Mixed Amateur International Standard Quickstep", CAT_COUPLE),
            ("Mixed Level International Standard Quickstep", CAT_COUPLE),
            ("Pro/Am International Standard Quickstep", CAT_COUPLE),
            ("Followers' Proficiency Quickstep", CAT_FOLLOW),
            ("Leader-judged Quickstep", CAT_LEAD),
            ("Solo Follower Proficiency Quickstep", CAT_FOLLOW),
            ("Solo Quickstep", CAT_SOLO),
            ("Mixed Leads and Follows Quickstep", CAT_COUPLE),
        )
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(event_category(title), expected)

    def test_site_role_metadata_takes_precedence(self):
        self.assertEqual(event_category("Quickstep", "leader"), CAT_LEAD)
        self.assertEqual(event_category("Quickstep", "follower"), CAT_FOLLOW)


if __name__ == "__main__":
    unittest.main()
