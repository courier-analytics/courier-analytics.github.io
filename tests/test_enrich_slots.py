import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from enrich_slots import enrich, report, scopes, atomic_json, source_status, booking_before_day
from import_slots import parse_rows
from test_import_slots import HEADERS, row


class EnrichmentTests(unittest.TestCase):
    def test_site_status_prefixes(self):
        self.assertEqual(source_status('Вышел раньше на 1 час'), 'early')
        self.assertEqual(source_status('Опоздал на 15 минут'), 'late')
        self.assertEqual(source_status('Не вышел'), 'no_show')
        self.assertEqual(source_status(None), 'unknown')

    def test_booking_cutoff_moscow_and_unknown_timezone(self):
        self.assertTrue(booking_before_day('2026-10-24T20:59:59Z', '2026-10-25'))
        self.assertFalse(booking_before_day('2026-10-24T21:00:00Z', '2026-10-25'))
        self.assertIsNone(booking_before_day('2026-10-24T20:59:59', '2026-10-25'))
        self.assertIsNone(booking_before_day(None, '2026-10-25'))

    def slots(self):
        return parse_rows(HEADERS, [row(), row(2, '7332', '1 из 2', '11')])

    def response(self, identity=1, people=None, capacity=3):
        return {'items': [{'slot_id': identity, 'slot_type': 'limited',
            'capacity': capacity, 'time_from': '07:00', 'time_to': '19:00',
            'couriers': people if people is not None else [
                {'id': '11', 'shift_status': 'Вышел', 'shift_start': '07:00'},
                {'id': '12', 'shift_status': 'Опоздал', 'shift_start': '07:15'}]}]}

    def test_scope_includes_cluster_and_direct_shop(self):
        self.assertEqual(scopes(self.slots()), [
            ('2026-10-25', 'cluster_id', 7332, 'limited'),
            ('2026-10-25', 'shopno', 5818, 'limited')])

    def test_individual_details_and_unknown_end(self):
        output, issues = enrich(self.slots()[:1], [
            ('2026-10-25', 'shopno', 5818, 'limited', self.response())])
        self.assertFalse(issues)
        people = output[0]['couriers']
        self.assertEqual([p['shift_status'] for p in people], ['Вышел', 'Опоздал'])
        self.assertTrue(all(p['shift_end'] is None for p in people))
        public = json.dumps(report(output, issues), ensure_ascii=False)
        self.assertNotIn('courier_id', public)
        self.assertNotIn('shift_start', public)

    def test_changed_membership_does_not_merge(self):
        output, issues = enrich(self.slots()[:1], [
            ('2026-10-25', 'shopno', 5818, 'limited',
             self.response(people=[{'id': '11'}, {'id': '99'}]))])
        self.assertEqual(issues[0]['code'], 'booking_membership_changed')
        self.assertEqual(output[0]['couriers'][0]['details_source'], 'api_required')

    def test_slot_time_and_capacity_changes_detected(self):
        raw = self.response(capacity=4)
        _, issues = enrich(self.slots()[:1], [
            ('2026-10-25', 'shopno', 5818, 'limited', raw)])
        self.assertEqual(issues[0]['code'], 'capacity_changed')
        raw = self.response()
        raw['items'][0]['time_to'] = '20:00'
        _, issues = enrich(self.slots()[:1], [
            ('2026-10-25', 'shopno', 5818, 'limited', raw)])
        self.assertEqual(issues[0]['code'], 'slot_times_changed')

    def test_wrong_scope_cannot_satisfy_missing_slot(self):
        _, issues = enrich(self.slots()[:1], [
            ('2026-10-25', 'cluster_id', 7332, 'limited', self.response())])
        self.assertEqual(issues[0]['code'], 'slot_missing_from_api')

    def test_atomic_output_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'report.json'
            atomic_json(p, {'ok': True})
            self.assertEqual(json.loads(p.read_text()), {'ok': True})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
