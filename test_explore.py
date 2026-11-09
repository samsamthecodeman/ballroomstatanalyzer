import tempfile
import unittest
import bce_explore as explore
import bce_analyze as core
from bce_store import ResultsStore


class ExploreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ResultsStore(self.temp.name)
        explore._snapshot.clear()
        for cid,state in [(1,'TX'),(2,'CA'),(3,'')]:
            self.store.put_competition({'cid':cid,'name':'Cup','date':'2026-11-07','events':[{'eid':1,'title':'Bronze Waltz'},{'eid':2,'title':'Mixed Follows Bronze Waltz'}]},complete=True)
            if state:self.store.put_external('bce','venue',str(cid),{'state':state,'city':'City'})
            results={'Alex Example & Sam Example':{'place':1,'made_final':True,'rounds':2},'Other One & Other Two':{'place':2,'made_final':True,'rounds':2}}
            self.store.put_event(cid,1,[results,2,'Amateur Bronze International Standard Waltz',{'n_rounds':2}])
            self.store.put_event(cid,2,[results,2,'Mixed Follows Bronze International Standard Waltz',{'n_rounds':2}])

    def test_texas_wins_credit_judged_dancer_and_ignore_unknown_venues(self):
        data=explore.texas_leaderboard(self.store,{})
        rows={r['name']:r for r in data['rows']}
        self.assertEqual(rows['Sam Example']['wins'],2)
        self.assertEqual(rows['Alex Example']['wins'],1)
        self.assertEqual(data['verified_texas'],1)
        self.assertEqual(data['unknown_venues'],1)
        self.assertEqual(len(data['competitions']),1)

    def test_filters_ties_search_and_orphan_rows(self):
        results={'Alex Example & Sam Example':{'place':1,'made_final':True,'rounds':1}}
        self.store.put_event(1,1,[results,1,'Amateur Bronze International Standard Waltz',{}])
        self.store.put_event(1,99,[results,1,'Orphan Waltz',{}])
        data=explore.texas_leaderboard(self.store,{'category':core.CAT_COUPLE})
        self.assertEqual([r['rank'] for r in data['rows']],[1,1])
        self.assertEqual([r['wins'] for r in data['rows']],[1,1])
        self.assertEqual(explore.texas_leaderboard(self.store,{'category':core.CAT_COUPLE,'excludeUncontested':'true'})['rows'],[])
        self.assertEqual(explore.texas_leaderboard(self.store,{'year':'2025'})['rows'],[])
        self.assertEqual(len(explore.texas_leaderboard(self.store,{'q':'Sam'})['rows']),1)

    def test_competition_and_event_belonging(self):
        self.assertEqual(len(explore.competition(self.store,1)['events']),2)
        event=explore.competition(self.store,1,1)
        self.assertEqual(event['rows'][0]['place'],1)
        self.assertIn('cid=1&eid=1',event['url'])
        for cid,eid in [(999,None),(1,99)]:
            with self.assertRaises(ValueError): explore.competition(self.store,cid,eid)

    def test_legacy_cache_title_falls_back_to_event_listing(self):
        data=self.store.get_events([(1,1)])[(1,1)]
        data[2]=None
        self.store.put_event(1,1,data)
        self.assertEqual(explore.competition(self.store,1,1)['title'],'Bronze Waltz')
        self.assertTrue(explore.texas_leaderboard(self.store,{})['rows'])


if __name__=='__main__':unittest.main()
