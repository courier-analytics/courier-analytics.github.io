import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from enrich_slots import atomic_json
from refresh_all_shops import refresh


class AllShopTests(unittest.TestCase):
    def test_all_four_shops_real_zero_and_missing_plan_not_confused(self):
        def audit(day, token, proxy, directory, extra_details=False):
            shops = []
            for identity in (5818, 7745, 4747, 8092):
                slots = [] if identity == 7745 else [{
                    'date': day, 'slot_id': identity, 'slot_type': 'limited',
                    'scope_kind': 'shopno', 'scope_id': identity,
                    'time_from': '07:00', 'time_to': '19:00', 'capacity': 2,
                    'couriers': [{'courier_id': str(identity), 'shift_status': 'Вышел',
                                  'shift_start': '2026-10-26T07:00:00+03:00', 'shift_end': None,
                                  'booked_at': '2026-10-25T16:00:00+03:00'}]}]
                shops.append({'shop_id': identity, 'slots': slots})
            directory.mkdir(parents=True, exist_ok=True)
            atomic_json(directory/'all-shops-observations.json', {'shops': shops})
            return {'shops': [{'shop_id': s['shop_id']} for s in shops]}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with patch('refresh_all_shops.audit', side_effect=audit):
                refresh('2026-10-26', 'secret', '', folder/'private', folder/'public.json')
            public = json.loads((folder/'public.json').read_text())
            self.assertEqual([r['shop_id'] for r in public['records']], [4747, 5818, 7745, 8092])
            self.assertEqual(public['records'][0]['fill_percent'], 50)
            self.assertIsNone(public['records'][2]['fill_percent'])
            self.assertEqual(public['records'][0]['metrics']['planned_attendance']['value'], 100)
            self.assertEqual(public['records'][0]['metrics']['unplanned_work']['reason'], 'frozen_plan_missing')
            self.assertNotIn('courier_id', (folder/'public.json').read_text())
            self.assertTrue((folder/'private/all-shops-2026-10-26.xlsx').is_file())
