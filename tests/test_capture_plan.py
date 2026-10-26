from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from capture_plan import freeze, in_capture_window, write_immutable


class PlanTests(unittest.TestCase):
    def test_frozen_snapshot_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'plan.json'
            write_immutable(path, {'first': True})
            with self.assertRaises(FileExistsError):
                write_immutable(path, {'second': True})
            self.assertEqual(path.read_text().strip(), '{\n  "first": true\n}')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
    def test_moscow_window_and_midnight_rejection(self):
        self.assertTrue(in_capture_window(datetime.fromisoformat('2026-10-26T20:59:10+00:00'), '2026-10-27'))
        self.assertFalse(in_capture_window(datetime.fromisoformat('2026-10-26T21:00:00+00:00'), '2026-10-27'))
        data = {'scope_config': {}, 'shops': [{'shop_id': 5818, 'slots': []}]}
        with self.assertRaises(ValueError):
            freeze(data, datetime.fromisoformat('2026-10-26T20:59:10+00:00'),
                   datetime.fromisoformat('2026-10-26T21:00:01+00:00'), '2026-10-27')

    def test_freeze_contains_ids_not_personal_details(self):
        data = {'scope_config': {}, 'shops': [{'shop_id': 5818, 'slots': [{
            'date': '2026-10-27', 'slot_id': 1, 'slot_type': 'limited',
            'time_from': '07:00', 'time_to': '19:00',
            'couriers': [{'courier_id': '11', 'name': 'private', 'phone': 'private'}]}]}]}
        result = freeze(data, datetime.fromisoformat('2026-10-26T20:59:00+00:00'),
                        datetime.fromisoformat('2026-10-26T20:59:10+00:00'), '2026-10-27')
        self.assertEqual(result['shops'][0]['slots'][0]['couriers'], [{'courier_id': '11'}])
