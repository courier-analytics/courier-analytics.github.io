from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from discover_scopes import discover, name_shop_numbers
from audit_sources import audit, sanitize_slot
from enrich_slots import ApiError, api_get


class ScopeTests(unittest.TestCase):
    def test_application_error_is_not_a_successful_empty_roster(self):
        completed = subprocess.CompletedProcess([], 0, '{"code":16,"message":"private"}\n200', '')
        with patch('enrich_slots.subprocess.run', return_value=completed):
            with self.assertRaisesRegex(RuntimeError, 'API application error 16'):
                api_get('/v1/shops', 'private-token', 'socks5h://127.0.0.1:18080')

    def test_exact_site_number_rules(self):
        self.assertEqual(name_shop_numbers('5818 Олимпийка, 7745; 3'), [5818, 7745])
        self.assertEqual(name_shop_numbers('Кластер 58; 4747'), [4747])

    def test_three_shops_without_cross_contamination(self):
        config = discover({'items': [{'id': 5818, 'cluster_id': 7000}, {'id': 7745}, {'id': 4747}]},
                          [{'id': 7332, 'name': '5818 Олимпийка'},
                           {'id': 8000, 'name': '7745 Точка'}, {'id': 8001, 'name': '4747 Точка'},
                           {'id': 9999, 'name': '15818 Другой ДС'}])
        self.assertEqual([s['cluster_ids'] for s in config['shops']], [[7000, 7332], [8000], [8001]])

    def test_missing_shop_is_not_silently_zero(self):
        config = discover([{'id': 5818}], [])
        self.assertFalse(config['shops'][1]['scope_verified'])

    def test_private_slot_discards_names_and_phones(self):
        slot = sanitize_slot({'slot_id': 1, 'slot_type': 'manual', 'shopno_cluster_id': 5818,
            'couriers': [{'id': '11', 'name': 'private', 'phone': 'private',
                          'shift_status': 'Вышел'}]}, '2026-10-26', 'shopno', 5818)
        self.assertNotIn('name', slot['couriers'][0])
        self.assertNotIn('phone', slot['couriers'][0])

    def test_null_aliases_do_not_hide_real_fields(self):
        slot = sanitize_slot({'slot_id': None, 'id': 1, 'type': None, 'slot_type': 'manual',
            'shopno_cluster_id': None, 'shopno': 5818, 'capacity': None, 'courier_limits': 0,
            'occupied': None, 'booked': 0, 'couriers': []}, '2026-10-26', 'shopno', 5818)
        self.assertEqual(slot['slot_id'], 1)
        self.assertEqual(slot['slot_type'], 'manual')
        self.assertEqual(slot['capacity'], 0)

    def test_forbidden_ds_does_not_become_zero_or_block_other_ds(self):
        def catalogue(path, token, proxy):
            return [{'id': n} for n in (5818, 7745, 4747)] if path == '/v1/shops' else []
        def slots(scope, token, proxy):
            if scope[2] == 7745:
                raise ApiError(403)
            return {'items': []}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch('audit_sources.api_get', side_effect=catalogue), patch('audit_sources.fetch', side_effect=slots):
                result = audit('2026-10-26', 'private-token', '', folder, extra_details=False)
            denied = result['shops'][1]
            self.assertFalse(denied['scope_verified'])
            self.assertEqual(denied['reason'], 'slots_http_403')
            self.assertNotIn('fill_percent', denied)
            stored = json.loads((folder/'all-shops-observations.json').read_text())
            self.assertEqual([s['shop_id'] for s in stored['shops']], [5818, 4747])
