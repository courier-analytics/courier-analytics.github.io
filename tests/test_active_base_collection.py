from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from active_base import collect
from build_dashboard_feed import validate_metrics


class ActiveCollectionTests(unittest.TestCase):
    def test_direct_scope_and_unique_people_only(self):
        current = [dict(scope_kind='shopno', scope_id=5818, couriers=[{'courier_id': '1'}]),
                   dict(scope_kind='cluster_id', scope_id=7332, couriers=[{'courier_id': '99'}])]
        def fetch(scope, token, proxy):
            return {'items': [dict(slot_id=1, slot_type='manual', shopno_cluster_id=5818,
                                  date=scope[0], couriers=[{'id': '2'}, {'id': '1'}])]}
        with patch('active_base.fetch', side_effect=fetch) as mocked:
            result = collect('2026-10-26', 5818, current, '', '')
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual(result['numerator'], 1)
        self.assertEqual(result['denominator'], 2)
        self.assertEqual(result['value'], 50)
        validate_metrics({'shift_marked': result})
        current[1]['couriers'].append({'courier_id': '2'})
        with patch('active_base.fetch', side_effect=fetch):
            self.assertEqual(collect('2026-10-26', 5818, current, '', '')['value'], 100)

    def test_incomplete_or_wrong_scope_never_produces_percentage(self):
        with patch('active_base.fetch', return_value={}):
            with self.assertRaises(ValueError):
                collect('2026-10-26', 5818, [], '', '')
