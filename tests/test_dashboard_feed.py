from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_dashboard_feed import build


class FeedTests(unittest.TestCase):
    def report(self):
        return {'schema_version': 1, 'snapshot_consistent': True, 'issues': [],
                'generated_at': '2026-10-26T07:12:12.215078+00:00',
                'summaries': [{'date': '2026-10-25', 'shop_id': 5818,
                               'slot_type': 'limited', 'booked_places': 57,
                               'capacity': 102, 'fill_percent': 55.88,
                               'courier_id': 'private', 'name': 'private'}]}

    def test_only_public_allowlisted_fields(self):
        feed = build([self.report()])
        self.assertEqual(feed['records'][0]['fill_percent'], 55.88)
        self.assertNotIn('name', feed['records'][0])
        self.assertNotIn('courier_id', feed['records'][0])

    def test_invalid_or_inconsistent_reports_rejected(self):
        for field, value in [('fill_percent', 45), ('capacity', -1), ('booked_places', True)]:
            report = self.report()
            report['summaries'][0][field] = value
            with self.assertRaises(ValueError):
                build([report])
        report = self.report()
        report['snapshot_consistent'] = False
        with self.assertRaises(ValueError):
            build([report])

    def test_zero_capacity_remains_missing(self):
        report = self.report()
        report['summaries'][0].update(capacity=0, booked_places=0, fill_percent=None)
        self.assertIsNone(build([report])['records'][0]['fill_percent'])

    def test_duplicate_snapshot_is_not_silently_overwritten(self):
        with self.assertRaises(ValueError):
            build([self.report(), deepcopy(self.report())])
