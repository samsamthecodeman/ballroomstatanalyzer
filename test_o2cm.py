"""Regression fixtures follow published MIT 2026 O2CM markup and placements."""
import tempfile
import unittest
import json
from unittest.mock import patch
from unittest.mock import Mock
from pathlib import Path

import bce_o2cm as o2
from bce_store import ResultsStore

HISTORY = '''<table><tr><td>Jonny Lu</td></tr>
<tr><td><b>04-25-26 - MIT Open 2026</b></td></tr>
<tr><td><a href="http://Results.o2cm.com/scoresheet3.asp?event=mit26&amp;heatid=40328510">3) Amateur Collegiate Championship Standard</a></td></tr>
<tr><td><b>04-26-25 - MIT Open 2025</b></td></tr>
<tr><td><a href="scoresheet3.asp?event=mit25&amp;heatid=40328510">8) Amateur Collegiate Championship Standard</a></td></tr></table>'''


def competition():
    # Official structure: scoresheet header, t2b final rows, ---- round separators.
    people = [
        (1, 135, 'Andrii Balkovyi & Diana Kuznetsova'),
        (2, 461, 'Kevin Song & Anna Soong'), (3, 305, 'Jonny Lu & Dorothy Xiao'),
        (4, 351, 'Patrick Lin & Ying Chen'), (5, 464, 'Steven Huang & Vikie Luo'),
        (6, 208, 'Justin Chiou & Hannah Chiou'),
    ] + [(i, 500 + i, f'Leader {i} & Follower {i}') for i in range(7, 23)]
    people[13] = (14, 514, 'Leader 14 & Follower 14')
    people[14] = (14, 515, 'Leader 15 & Follower 15')
    rows = ['<table><tr><td colspan="2" class="h5b"><a href="scoresheet3.asp?event=mit26&amp;heatid=40328510&amp;bclr=#FFFFFF">Amateur Collegiate Championship Standard (WTVFQ)</a></td></tr>']
    for index, (place, bib, name) in enumerate(people):
        if index in (6, 12):
            rows.append('<tr><td></td><td>----</td></tr>')
        css = 't2b' if index < 6 else 't2n'
        rows.append(f'<tr><td></td><td class="{css}">{place}) {bib} {name} - NJ</td></tr>')
    return ''.join(rows) + '</table>'


class Fetcher:
    def __init__(self, directory):
        self.store = ResultsStore(directory)
        self.calls = []
        self.history = HISTORY
        self.page = competition()

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.history if url.endswith('individual.asp') else self.page


class O2CMTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fetcher = Fetcher(self.directory.name)

    def test_history_dates_codes_and_reused_heat_ids(self):
        comps = o2.parse_history(HISTORY)
        self.assertEqual([comp['code'] for comp in comps], ['mit26', 'mit25'])
        self.assertEqual(comps[0]['date'], '2026-04-25')
        self.assertEqual(comps[0]['heats'], comps[1]['heats'])
        self.assertEqual(o2.parse_history(HISTORY.replace('40328510', '40a28510'))[0]['heats'], ['40A28510'])
        self.assertEqual(o2.parse_history('<p>No Results on File</p>'), [])
        with self.assertRaises(ValueError):
            o2.parse_history('<h1>Server Error</h1>')

    def test_placements_ties_field_size_and_finals(self):
        event = o2.parse_competition(competition(), 'mit26')['40328510']
        self.assertEqual(len(event['entries']), 22)
        self.assertEqual(event['rounds'], 3)
        self.assertEqual(sum(e['made_final'] for e in event['entries']), 6)
        self.assertEqual(sum(e['place'] == 14 for e in event['entries']), 2)
        self.assertEqual(event['entries'][2]['entry'], 'Jonny Lu & Dorothy Xiao')
        self.assertEqual(event['entries'][2]['place'], 3)

    def test_collect_source_ids_links_classification_and_warm_cache(self):
        first = o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        record = first['records'][0]
        self.assertEqual(record.cid, 'o2cm:mit26')
        self.assertEqual(record.eid, 'o2cm:40328510')
        self.assertEqual(record.source, 'o2cm')
        self.assertEqual(record.role, 'Unknown')
        self.assertEqual(record.entries, 22)
        self.assertEqual(record.place, 3)
        self.assertEqual(record.partner, 'Dorothy Xiao')
        self.assertEqual(record.style, 'International Standard')
        self.assertEqual(record.dances, ['Waltz', 'Tango', 'Viennese Waltz', 'Foxtrot', 'Quickstep'])
        self.assertEqual(record.category, 'Couple-judged')
        self.assertIn('scoresheet3.asp?event=mit26&heatid=40328510', record.url)
        with patch.object(self.fetcher, 'get', side_effect=AssertionError('Warm O2CM results must be offline')):
            warm = o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        self.assertEqual(first, warm)
        self.assertEqual(self.fetcher.calls[1][1]['post_data']['submit'], 'OK')

    def test_provider_namespace_keeps_comp_express_rows_separate(self):
        self.fetcher.store.put_profile(123, 'BCE overview', [])
        o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        self.assertEqual(self.fetcher.store.get_profile(123)['overview'], 'BCE overview')
        self.assertEqual(len(self.fetcher.store.external_keys('o2cm', 'profile')), 1)

    def test_offline_source_reports_failure_or_returns_last_successful_data(self):
        self.fetcher.history = None
        with self.assertRaisesRegex(ValueError, 'could not be reached'):
            o2.collect('Jonny', 'Lu', self.fetcher)
        self.fetcher.history = HISTORY
        o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        self.fetcher.history = None
        data, notes = o2.load_history('Jonny', 'Lu', self.fetcher, force=True)
        self.assertEqual(len(data['comps']), 2)
        self.assertTrue(notes)

    def test_incomplete_competition_never_replaces_good_cache(self):
        result = o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        comp = o2.parse_history(HISTORY)[0]
        self.fetcher.page = '<table>Login required</table>'
        with self.assertRaises(ValueError):
            o2.load_competition(comp, self.fetcher, force=True)
        cached = self.fetcher.store.get_external('o2cm', 'competition', 'mit26')
        self.assertEqual(len(cached['data']['events']['40328510']['entries']), 22)
        comp['heats'].append('999')
        self.fetcher.page = competition()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            o2.load_competition(comp, self.fetcher)

    def test_partner_filter_and_ambiguous_entries(self):
        self.assertEqual(o2.collect('Jonny', 'Lu', self.fetcher, partner='Someone Else', competitions=['mit26'])['status'], 'no_o2_results')
        self.fetcher.page = competition().replace('</table>', '<tr><td class="t2n">23) 888 Jonny Lu & Another Partner - NJ</td></tr></table>')
        self.fetcher.store.put_external('o2cm', 'competition', 'mit26', {'version':0})
        with self.assertRaisesRegex(ValueError, 'Multiple O2CM entries'):
            o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        result = o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'], partner='Dorothy Xiao')
        self.assertEqual(len(result['records']), 1)

    def test_http_source_validation_and_job_wiring(self):
        import bce_web
        from dataclasses import asdict
        data = o2.collect('Jonny', 'Lu', self.fetcher, competitions=['mit26'])
        with patch.object(o2, 'collect', return_value=data), patch.object(bce_web, 'FETCHER', self.fetcher):
            job = {'cancel':False,'state':'running'}
            bce_web.run_job('o2-test', job, {'source':'o2cm','first':'Jonny','last':'Lu','name':'Jonny Lu','o2_comps':['mit26']})
        self.assertEqual(job['state'], 'done')
        self.assertEqual(job['result']['source'], 'o2cm')
        self.assertEqual(job['result']['events'][0]['source'], 'o2cm')
        self.assertTrue(job['result']['warnings'])

    def test_invalid_or_failed_pages_are_not_cached_for_a_week(self):
        import bce_analyze as core
        fetcher = core.Fetcher(self.directory.name, 0, False)
        fetcher.session = Mock()
        fetcher.session.post.return_value = Mock(status_code=200, text='<h1>Temporary error</h1>')
        url = o2.BASE + 'individual.asp'
        options = dict(post_data={'szFirst':'Jonny','szLast':'Lu'}, cache_misses=False,
                       validate=lambda body: o2.valid_response(o2.parse_history, body))
        self.assertIsNone(fetcher.get(url, **options))
        fetcher.session.post.return_value = Mock(status_code=404, text='Unavailable')
        self.assertIsNone(fetcher.get(url, **options))
        fetcher.session.post.return_value = Mock(status_code=200, text=HISTORY)
        self.assertEqual(fetcher.get(url, **options), HISTORY)
        self.assertEqual(fetcher.session.post.call_count, 3)
        self.assertEqual(fetcher.get(url, **options), HISTORY)
        self.assertEqual(fetcher.session.post.call_count, 3)

    def test_provider_refresh_has_independent_checkpoint_and_backoff(self):
        import bce_analyze as core
        from bce_cache import CacheMaintainer
        fetcher = core.Fetcher(self.directory.name, 0, False)
        worker = CacheMaintainer(fetcher, delay=0, log=lambda message: None)
        fetcher.store.set_meta('last_complete_slot', 'BCE-completed-slot')
        with patch.object(o2, 'refresh_known', side_effect=ValueError('O2CM unavailable')) as refresh:
            worker.refresh_o2cm('current-slot')
            worker.refresh_o2cm('current-slot')
            self.assertEqual(refresh.call_count, 1)
        self.assertEqual(fetcher.store.get_meta('last_complete_slot'), 'BCE-completed-slot')
        self.assertEqual(fetcher.store.get_meta('o2cm_refresh_status')['state'], 'error')
        fetcher.store.set_meta('o2cm_retry_after', 0)
        with patch.object(o2, 'refresh_known') as refresh:
            worker.refresh_o2cm('current-slot')
            worker.refresh_o2cm('current-slot')
            self.assertEqual(refresh.call_count, 1)
        self.assertEqual(fetcher.store.get_meta('o2cm_last_slot'), 'current-slot')


if __name__ == '__main__':
    unittest.main()
