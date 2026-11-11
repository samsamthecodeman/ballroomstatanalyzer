import tempfile
import unittest
import bce_explore as explore
import bce_analyze as core
from bce_store import ResultsStore


class ExploreTests(unittest.TestCase):
    def test_public_api_always_combines_providers(self):
        import json,threading
        from unittest.mock import patch
        from http.server import ThreadingHTTPServer
        from urllib.request import urlopen,Request
        import bce_web
        server=ThreadingHTTPServer(('127.0.0.1',0),bce_web.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with patch.object(bce_web,'FETCHER') as fetcher, patch.object(explore,'catalog',return_value=[]) as catalog:
                json.load(urlopen(url+'/api/catalog?source=bce'))
                self.assertEqual(catalog.call_args.args[1],'all')
            captured=[];ready=threading.Event()
            def run(job_id,job,params):captured.append(params);ready.set()
            with patch.object(bce_web,'run_job',side_effect=run),patch.dict(bce_web.CONFIG,{'public':False}):
                req=Request(url+'/api/start',data=json.dumps({'source':'bce','aid':123}).encode(),headers={'Content-Type':'application/json'})
                result=json.load(urlopen(req))
                self.assertTrue(ready.wait(3))
                self.assertEqual(captured[0]['source'],'all')
                bce_web.JOBS.pop(result['id'],None)
        finally:server.shutdown();server.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ResultsStore(self.temp.name)
        explore._snapshot.clear()
        explore._couples_cache.clear()
        for cid,state in [(1,'TX'),(2,'CA'),(3,'')]:
            self.store.put_competition({'cid':cid,'name':'Cup','date':'2026-11-07','events':[{'eid':1,'title':'Bronze Waltz'},{'eid':2,'title':'Mixed Follows Bronze Waltz'}]},complete=True)
            if state:self.store.put_external('bce','venue',str(cid),{'state':state,'city':'City'})
            results={'Alex Example & Sam Example':{'place':1,'made_final':True,'rounds':2},'Other One & Other Two':{'place':2,'made_final':True,'rounds':2}}
            self.store.put_event(cid,1,[results,2,'Amateur Bronze International Standard Waltz',{'n_rounds':2}])
            self.store.put_event(cid,2,[results,2,'Mixed Follows Bronze International Standard Waltz',{'n_rounds':2}])

    def test_couple_suggestions_use_both_sources_and_merge_reversed_partners(self):
        self.store.put_external('o2cm', 'competition', 'abc26', {'events': {'1': {'entries': [
            {'people': ['Sam Example', 'Alex Example']},
            {'people': ['Sam Example', 'O2 Partner']},
            {'people': ['Solo Example']},
            {'people': ['Team One', 'Team Two', 'Team Three']}]}}})
        pairs = explore.search_couples(self.store, 'sam')
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p['label'] for p in pairs}, {'Alex Example & Sam Example', 'O2 Partner & Sam Example'})
        self.assertEqual(len(explore.search_couples(self.store, 'example sam')), 2)
        self.assertEqual(len(explore.search_couples(self.store, 'example', 'Alex Example')), 1)
        self.assertEqual(explore.search_couples(self.store, 'sa'), [])
        self.assertEqual(explore.search_couples(self.store, 'solo'), [])
        self.assertEqual(explore.search_couples(self.store, 'team'), [])
        self.assertEqual(explore.search_couples(self.store, 'nonexistent'), [])

    def test_texas_wins_credit_judged_dancer_and_ignore_unknown_venues(self):
        data=explore.texas_leaderboard(self.store,{})
        rows={r['name']:r for r in data['rows']}
        self.assertEqual(rows['Sam Example']['wins'],2)
        self.assertEqual(rows['Alex Example']['wins'],1)
        self.assertEqual(data['verified_texas'],1)
        self.assertEqual(data['unknown_venues'],1)
        self.assertEqual(len(data['competitions']),1)

    def test_couple_leaderboard_counts_partnership_once_and_separates_partners(self):
        data = self.store.get_events([(1, 1)])[(1, 1)]
        data[0] = {'Sam Example & Different Partner': {'place':1,'made_final':True,'rounds':2}}
        self.store.put_event(1, 3, data)
        comp = self.store.competition(1)['data']
        comp['events'].append({'eid':3,'title':data[2]})
        self.store.put_competition(comp, complete=True)
        board = explore.texas_leaderboard(self.store, {'mode':'couple','category':core.CAT_FOLLOW})
        rows = {r['name']:r for r in board['rows']}
        self.assertEqual(board['mode'], 'couple')
        self.assertEqual(rows['Alex Example & Sam Example']['wins'], 1)
        self.assertEqual(rows['Alex Example & Sam Example']['events'], 1)
        self.assertEqual(rows['Different Partner & Sam Example']['wins'], 1)
        self.assertEqual(rows['Alex Example & Sam Example']['rank'], rows['Different Partner & Sam Example']['rank'])
        self.assertFalse(any(' & ' not in name for name in rows))
        self.assertEqual(len(explore.texas_leaderboard(self.store, {'mode':'couple','q':'Sam Example Alex'})['rows']), 1)
        self.assertEqual(explore.texas_leaderboard(self.store, {'mode':'couple','year':'2025'})['rows'], [])
        self.assertEqual(explore.texas_leaderboard(self.store, {'mode':'couple','styles':'["International Latin"]'})['rows'], [])
        with self.assertRaises(ValueError):
            explore.texas_leaderboard(self.store, {'mode':'unknown'})

    def test_couple_leaderboard_unifies_reversed_names_across_providers(self):
        self.o2_fixture(name='Cup')
        o2 = self.store.get_external('o2cm','competition','test26')['data']
        o2['events']['ABC']['entries'][0].update(entry='Sam Example & Alex Example', people=['Sam Example','Alex Example'])
        self.store.put_external('o2cm','competition','test26',o2)
        board = explore.texas_leaderboard(self.store, {'mode':'couple'})
        row = next(r for r in board['rows'] if r['name']=='Alex Example & Sam Example')
        self.assertEqual(row['events'], 1)
        self.assertEqual(row['wins'], 1)
        self.assertEqual(row['competitions'], 1)
        self.assertGreater(board['deduplicated'], 0)
        national = explore.texas_leaderboard(self.store, {'mode':'couple','region':'national'})
        row = next(r for r in national['rows'] if r['name']=='Alex Example & Sam Example')
        self.assertEqual(row['wins'], 2)

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

    def o2_fixture(self,name='O2 Cup',state='TX'):
        self.store.put_external('o2cm','competition','test26',{'meta':{'name':name,'date':'2026-11-07'},'events':{
            'ABC':{'title':'Amateur Bronze International Standard Waltz','rounds':2,'entries':[
                {'entry':'Alex Example & Sam Example','people':['Alex Example','Sam Example'],'place':1,'made_final':True,'group':0},
                {'entry':'Other One & Other Two','people':['Other One','Other Two'],'place':2,'made_final':True,'group':0}]},
            'DEF':{'title':'Amateur Bronze International Standard Tango','rounds':1,'entries':[
                {'entry':'Different Partner & Sam Example','people':['Different Partner','Sam Example'],'place':2,'made_final':True,'group':0}]}}})
        self.store.put_external('o2cm','venue','test26',{'state':state,'city':'Verified city'})

    def test_dancer_view_all_events_and_exact_name_suggestions_both_sources(self):
        self.o2_fixture()
        self.assertIn('Sam Example',explore.competition(self.store,'o2cm:test26')['dancers'])
        data=explore.competition(self.store,'o2cm:test26',dancer='sam example')
        self.assertEqual(len(data['rows']),2)
        self.assertEqual({r['source'] for r in data['rows']},{'o2cm'})
        self.assertEqual({r['partner'] for r in data['rows']},{'Alex Example','Different Partner'})
        self.assertEqual(len(explore.competition(self.store,1,dancer='Sam Example')['rows']),2)
        self.assertEqual(explore.competition(self.store,1,dancer='Sam')['rows'],[])
        with self.assertRaises(ValueError):explore.competition(self.store,'o2cm:test26',source='bce')

    def test_national_texas_and_provider_filters(self):
        self.o2_fixture(state='MA')
        tx=explore.texas_leaderboard(self.store,{'region':'texas','source':'all'})
        us=explore.texas_leaderboard(self.store,{'region':'national','source':'all'})
        self.assertGreater(len(us['competitions']),len(tx['competitions']))
        only=explore.texas_leaderboard(self.store,{'region':'national','source':'o2cm'})
        self.assertEqual({s for row in only['rows'] for s in row['sources']},{'o2cm'})
        self.assertEqual(explore.texas_leaderboard(self.store,{'source':'o2cm'})['rows'],[])

    def test_multiple_styles_union_empty_all_and_invalid_selection(self):
        import json
        data=self.store.get_events([(1,2)])[(1,2)]
        data[2]='Amateur Bronze International Latin Rumba'
        self.store.put_event(1,2,data)
        standard=explore.texas_leaderboard(self.store,{'styles':json.dumps(['International Standard'])})
        both=explore.texas_leaderboard(self.store,{'styles':json.dumps(['International Standard','International Latin'])})
        all_styles=explore.texas_leaderboard(self.store,{'styles':'[]'})
        self.assertEqual(next(r for r in standard['rows'] if r['name']=='Sam Example')['wins'],1)
        self.assertEqual(next(r for r in both['rows'] if r['name']=='Sam Example')['wins'],2)
        self.assertEqual(both['rows'],all_styles['rows'])
        for selection in ['invalid','"International Standard"','["unknown"]','[{}]']:
            with self.subTest(selection=selection),self.assertRaises(ValueError):
                explore.texas_leaderboard(self.store,{'styles':selection})

    def test_unique_cross_provider_mirrors_merge_and_count_once(self):
        # Remove unrelated duplicate-name fixtures to establish a unique competition pair.
        with self.store.connect() as db:db.execute('DELETE FROM competitions WHERE cid IN (2,3)')
        self.o2_fixture(name='Cup')
        self.assertEqual(len(explore.catalog(self.store)),1)
        data=explore.competition(self.store,1,dancer='Sam Example')
        self.assertEqual(data['deduplicated'],1)
        self.assertEqual(len(data['rows']),3)
        board=explore.texas_leaderboard(self.store,{})
        self.assertGreater(board['deduplicated'],0)
        sam=next(row for row in board['rows'] if row['name']=='Sam Example')
        self.assertEqual(sam['wins'],2)


if __name__=='__main__':unittest.main()
