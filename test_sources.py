import unittest
from dataclasses import replace, asdict
from unittest.mock import patch
import io
import csv

import bce_analyze as core
import bce_sources as sources
import bce_o2cm as o2
import bce_export
from test_exports import sample_event


def result(provider='bce', partner='Partner A', cid=1):
    fields = sample_event(entry=f'Sam Example & {partner}', partner=partner, rounds_in_event=2,
                          source=provider, cid=cid, comp=f'{provider} Cup')
    record = core.EventRecord(**fields)
    return dict(status='ok', name='Sam Example', records=[record],
                raw_events=[(record, {record.entry: dict(place=record.place, made_final=True, rounds=2)})],
                spellings={'Sam Example'}, suggestions=[], alternatives=[], comps_scanned=1, events_scanned=1)


CANDIDATES = [dict(id=1, name='Sam Example'), dict(id=2, name='Sam Example')]


class SourceTests(unittest.TestCase):
    def test_name_boundaries(self):
        self.assertEqual(sources.split_name('Sam Example'), ('Sam', 'Example'))
        self.assertEqual(sources.split_name('de la Cruz, Ana'), ('Ana', 'de la Cruz'))
        self.assertEqual(sources.split_name('Mary Ann Smith'), ('Mary Ann', 'Smith'))
        with self.assertRaises(ValueError):
            sources.split_name('Sam')

    def test_unique_name_combines_both_sources_without_partner_restriction(self):
        with patch.object(core, 'search_dancers', return_value=CANDIDATES[:1]), \
             patch.object(core, 'collect', return_value=result()), \
             patch.object(o2, 'collect', return_value=result('o2cm', cid='o2cm:abc26')) as collect:
            data = sources.collect(dict(source='all', name='Sam Example'), None)
        self.assertEqual({r.source for r in data['records']}, {'bce', 'o2cm'})
        self.assertEqual(collect.call_args.kwargs['allowed_partners'], None)
        self.assertEqual(data['aid'], 1)

    def test_duplicate_profiles_resolve_only_one_shared_partnership(self):
        def lookup(name, fetcher, **kwargs):
            return result(partner='Partner A' if kwargs['aid'] == 1 else 'Partner B')
        with patch.object(core, 'search_dancers', return_value=CANDIDATES), \
             patch.object(core, 'collect', side_effect=lookup), \
             patch.object(o2, 'partner_names', return_value={'partner b'}), \
             patch.object(o2, 'collect', return_value=result('o2cm', 'Partner B', 'o2cm:abc26')) as collect:
            data = sources.collect(dict(source='all', name='Sam Example'), None)
        self.assertEqual(data['aid'], 2)
        self.assertEqual(collect.call_args.kwargs['allowed_partners'], {'partner b'})
        self.assertIn('shared partnerships', ' '.join(data['warnings']))

    def test_no_unique_partnership_does_not_guess(self):
        for partners in ({'partner a'}, set()):
            with self.subTest(partners=partners), patch.object(core, 'search_dancers', return_value=CANDIDATES), \
                 patch.object(core, 'collect', return_value=result()), patch.object(o2, 'partner_names', return_value=partners):
                with self.assertRaisesRegex(ValueError, 'one unique'):
                    sources.collect(dict(source='all', name='Sam Example'), None)

    def test_numeric_id_resolves_name_and_checks_duplicate_profiles(self):
        with patch.object(core, 'search_dancers', return_value=CANDIDATES), \
             patch.object(core, 'collect', return_value=result(partner='Partner B')), \
             patch.object(o2, 'collect', return_value=result('o2cm', 'Partner B', 'o2cm:abc26')) as collect:
            data = sources.collect(dict(source='all', name='', aid=2), None)
        self.assertEqual(data['name'], 'Sam Example')
        self.assertEqual(collect.call_args.args[:2], ('Sam', 'Example'))
        self.assertEqual(collect.call_args.kwargs['allowed_partners'], {'partner b'})

    def test_o2cm_only_can_resolve_comp_express_id(self):
        with patch.object(core, 'collect', return_value=result()), \
             patch.object(o2, 'collect', return_value=result('o2cm')):
            data = sources.collect(dict(source='o2cm', aid=1), None)
        self.assertEqual([r.source for r in data['records']], ['o2cm'])

    def test_compound_surname_keeps_explicit_boundary(self):
        with patch.object(o2, 'collect', return_value=result('o2cm')) as collect:
            sources.collect(dict(source='o2cm', name='de la Cruz, Ana'), None)
        self.assertEqual(collect.call_args.args[:2], ('Ana', 'de la Cruz'))

    def test_duplicate_compound_surname_keeps_explicit_boundary(self):
        candidates = [dict(id=1, name='Ana de la Cruz'), dict(id=2, name='Ana de la Cruz')]
        with patch.object(core, 'search_dancers', return_value=candidates), \
             patch.object(o2, 'partner_names', return_value=set()) as partners, \
             patch.object(core, 'collect', return_value=result()):
            with self.assertRaisesRegex(ValueError, 'one unique'):
                sources.collect(dict(source='all', name='de la Cruz, Ana'), None)
        self.assertEqual(partners.call_args.args[:2], ('Ana', 'de la Cruz'))

    def test_provider_failure_returns_other_source_with_notice(self):
        with patch.object(core, 'search_dancers', return_value=CANDIDATES[:1]), \
             patch.object(core, 'collect', return_value=result()), \
             patch.object(o2, 'collect', side_effect=ValueError('Service down')):
            data = sources.collect(dict(source='all', name='Sam Example'), None)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(len(data['records']), 1)
        self.assertIn('Service down', ' '.join(data['warnings']))

    def test_exact_mirrors_deduplicate_but_conflicting_placements_remain(self):
        bce = result()
        for place, count in ((1, 1), (2, 2)):
            # The sample event is first place. Mirror all metadata except provider IDs.
            record = replace(bce['records'][0], source='o2cm', cid='o2cm:abc26', place=place)
            other = {**result('o2cm'), 'records':[record], 'raw_events':[(record, bce['raw_events'][0][1])]}
            with patch.object(core, 'search_dancers', return_value=CANDIDATES[:1]), \
                 patch.object(core, 'collect', return_value=bce), patch.object(o2, 'collect', return_value=other):
                data = sources.collect(dict(source='all', name='Sam Example'), None)
            self.assertEqual(len(data['records']), count)

    def test_combined_exports_label_both_providers(self):
        events = [asdict(result()['records'][0]), asdict(result('o2cm', cid='o2cm:abc26')['records'][0])]
        rows = list(csv.DictReader(io.StringIO(bce_export.csv_report(events).decode('utf-8-sig'))))
        self.assertEqual([row['Source'] for row in rows], ['Ballroom Comp Express', 'O2CM'])
        from pypdf import PdfReader
        report = bce_export.pdf_report(dict(name='Sam Example', source='all'), events, {})
        text = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(report)).pages)
        self.assertIn('Sources: Comp Express + O2CM', text)
        self.assertIn('ballroomcompexpress.com + results.o2cm.com', text)


if __name__ == '__main__':
    unittest.main()
