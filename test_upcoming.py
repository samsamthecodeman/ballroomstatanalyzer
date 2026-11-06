import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import bce_upcoming as upcoming

ROSTER = '<select id="dancer"><option value="1">Sam Example</option><option value="2">Bob Smith</option><option value="3">Cindy Jones</option></select>'
PERSONAL = '''<div class="page"><h2>Sam Example</h2><h3>Session 1: Morning</h3>
<div>[9:00 AM <span class="changedtime">10:00 AM</span>] (Leading Alex Partner) Event 12: Amateur Collegiate Bronze International Standard Waltz Semifinal</div>
<div class="callback-round hidden">*[10:30 AM] (Leading Alex Partner) Event 12: Amateur Collegiate Bronze International Standard Waltz Final</div></div>'''
SCHEDULE = '''<h1>Schedule for Fixture Comp</h1><h3>Session 1: Morning (01/01/2000 9:00 AM)</h3>
<div class="round-entry"><span class="trigger">[9:00 AM <span class="changedtime">10:00 AM</span>] Event 12: Amateur Collegiate Bronze International Standard Waltz Semifinal (2 couples)</span>
<div class="inner"><div class="eid1">101 - Sam Example &amp; Alex Partner (<i>Austin, TX</i>)</div><div class="eid2">102 - Bob Smith (<i>Club One</i>) &amp; Cindy Jones (<i>Club Two</i>)</div></div></div>'''


def historical(**changes):
    return dict(source='bce', cid=10, eid=5, date='2025-01-01', comp='Past Comp', event='Bronze Waltz',
                entry='Sam Example & Alex Partner', partner='Alex Partner', place=1, category='Couple-judged',
                field=[dict(entry='Sam Example & Alex Partner', people=['Sam Example', 'Alex Partner'], place=1),
                       dict(entry='Bob Smith & Cindy Jones', people=['Bob Smith', 'Cindy Jones'], place=2)],
                url='https://ballroomcompexpress.com/results.php?cid=10&eid=5', **changes)


class Fetcher:
    def __init__(self):
        self.calls = []
        self.roster = ROSTER

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if 'heatsheet_dancer' in url:
            return PERSONAL
        if 'viewschedule' in url:
            return SCHEDULE
        return self.roster


class UpcomingTests(unittest.TestCase):
    def setUp(self):
        self.fetcher = Fetcher()
        self.result = dict(aid=1, name='Sam Example', events=[historical()])

    def test_restrict_urls_to_public_bce_pages(self):
        self.assertEqual(upcoming.competition_id('243'), 243)
        self.assertEqual(upcoming.competition_id('https://ballroomcompexpress.com/heatsheets.php?cid=243'), 243)
        for value in ['https://evil.example/heatsheets.php?cid=243', 'https://ballroomcompexpress.com.evil.example/heatsheets.php?cid=243',
                      'http://127.0.0.1/?cid=243', 'https://ballroomcompexpress.com/heatsheets.php?cid=1&cid=2',
                      'https://ballroomcompexpress.com/login.php?cid=243', '0', '1000000', 'https://user:password@ballroomcompexpress.com/heatsheets.php?cid=243']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                upcoming.competition_id(value)

    def test_real_markup_callback_exclusion_updated_time_and_names(self):
        personal = upcoming.parse_personal(PERSONAL)
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0]['time'], '10:00 AM')
        field = upcoming.parse_schedule(SCHEDULE)['rounds'][0]['entries']
        self.assertEqual(field[1]['people'], ['Bob Smith', 'Cindy Jones'])
        self.assertEqual(field[1]['bib'], '102')

    def test_join_and_past_person_and_partnership_records(self):
        report = upcoming.analyze('243', self.result, self.fetcher)
        event = report['events'][0]
        self.assertEqual(event['entries'], 2)
        self.assertEqual(event['time'], '10:00 AM')
        self.assertEqual(event['opponents'][0]['partnership_history']['wins'], 1)
        person = event['opponents'][0]['people_history'][0]
        self.assertEqual(person['history']['meetings'], 1)
        self.assertEqual(person['history']['matches'][0]['your_partner'], 'Alex Partner')
        self.assertTrue(any('past' in warning for warning in report['warnings']))
        self.assertEqual(len(self.fetcher.calls), 3)
        self.assertTrue(all(call[1]['max_age'] == 900 and call[1]['cache_misses'] is False for call in self.fetcher.calls))
        self.assertTrue(all('validate' in call[1] for call in self.fetcher.calls))

    def test_exclude_current_comp_results_and_future_results(self):
        self.result['events'] += [{**historical(), 'cid':243}, {**historical(), 'date':'2999-01-01'}]
        report = upcoming.analyze('243', self.result, self.fetcher)
        self.assertEqual(report['history_events'], 1)

    def test_history_missing_placements_together_and_different_partnerships(self):
        events = [historical(), {**historical(), 'place':3}, {**historical(), 'place':2}, {**historical(), 'place':None},
                  {**historical(), 'entry':'Sam Example & Bob Smith', 'field':[]}]
        result = upcoming.history_stats(events, ['Bob Smith'])
        self.assertEqual([result[k] for k in ['meetings','wins','losses','ties','unplaced','together']], [4,1,1,1,1,1])
        self.assertEqual(upcoming.history_stats(events, ['Bob Smith','Other Partner'], couple=True)['meetings'], 0)
        for event in events:
            event['date'] = '2025-01-01'
        self.assertEqual(len(upcoming.history_stats(events*5, ['Bob Smith'])['matches']), 10)

    def test_ambiguous_registered_and_historical_names_do_not_merge(self):
        self.fetcher.roster += '<select id="dancer"><option value="22">Bob Smith</option></select>'
        report = upcoming.analyze('243', self.result, self.fetcher)
        person = report['events'][0]['opponents'][0]['people_history'][0]
        self.assertTrue(person['ambiguous'])
        self.assertIsNone(person['history'])
        event = historical()
        event['field'].append(dict(entry='Bob Smith & Different Partner', people=['Bob Smith','Different Partner'], place=3))
        result = upcoming.history_stats([event], ['Bob Smith'])
        self.assertEqual(result['meetings'], 0)
        self.assertEqual(result['ambiguous_events'], 1)

    def test_identity_and_unpublished_pages_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, 'unique registered'):
            upcoming.analyze('243', {**self.result, 'aid':999}, self.fetcher)
        for parser in [upcoming.parse_personal, upcoming.parse_schedule]:
            with self.assertRaises(ValueError):
                parser('<h1>Login required</h1>')
            self.assertFalse(upcoming.valid_page(parser, '<h1>Temporary error</h1>'))
        report = upcoming.analyze('243', {**self.result, 'aid':None}, self.fetcher)
        self.assertEqual(report['aid'], 1)

    def test_endpoint_ownership_expiry_and_valid_request(self):
        import bce_web
        job = dict(visitor='owner', state='done', result=self.result)
        bce_web.JOBS['upcoming-test'] = job
        bce_web.UPCOMING_RECENT.clear()
        server = ThreadingHTTPServer(('127.0.0.1', 0), bce_web.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(job_id='upcoming-test'):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/upcoming',
                          data=json.dumps(dict(id=job_id, url='243')).encode(), headers={'Content-Type':'application/json'})
            return urlopen(req).read()
        try:
            with patch.object(bce_web.Handler, 'visitor', return_value='owner'), patch.object(bce_web, 'FETCHER', self.fetcher):
                self.assertEqual(json.loads(request())['competition'], 'Fixture Comp')
                job['visitor'] = 'someone else'
                with self.assertRaises(HTTPError) as error:
                    request()
                self.assertEqual(error.exception.code, 404)
                job['visitor'] = 'owner'; job['state'] = 'running'
                with self.assertRaises(HTTPError) as error:
                    request()
                self.assertEqual(error.exception.code, 409)
        finally:
            server.shutdown(); server.server_close()
            bce_web.JOBS.pop('upcoming-test', None)
            bce_web.UPCOMING_RECENT.clear()


if __name__ == '__main__':
    unittest.main()
