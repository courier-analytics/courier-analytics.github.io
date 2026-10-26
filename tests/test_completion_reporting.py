from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from completion_reporting import choose, collect, BASIS
from build_dashboard_feed import validate_metrics

NOW = datetime.fromisoformat('2026-10-27T18:00:00+03:00')


def night(end=None):
    return {'date': '2026-10-25', 'time_from': '20:00', 'time_to': '08:00',
            'slot_type': 'limited', 'slot_id': 1, 'scope_kind': 'shopno', 'scope_id': 5818,
            'couriers': [{'courier_id': '1', 'shift_start': '2026-10-25T20:47:00+03:00',
                          'shift_end': end, 'shift_status': 'Опоздал'}]}


class CompletionReportingTests(unittest.TestCase):
    def test_open_night_not_assigned_to_start_day_and_long_night_uses_actual_day(self):
        self.assertEqual(choose([night()], '2026-10-25'), [])
        completed = night('2026-10-27T08:00:00+03:00')
        self.assertEqual(choose([completed], '2026-10-26'), [])
        self.assertEqual(len(choose([completed], '2026-10-27')), 1)

    def test_next_day_duplicate_does_not_double_count_or_replace_original_plan(self):
        original = night('2026-10-26T07:00:00+03:00')
        continuation = {**deepcopy(original), 'date': '2026-10-26', 'slot_id': 2,
                        'time_from': '00:00', 'time_to': '07:00'}
        self.assertEqual(choose([continuation, original], '2026-10-26'), [original])

    def test_collect_bootstraps_previous_day_and_keeps_polling_open_shift(self):
        def response(scope, token, proxy):
            raw = deepcopy(night('2026-10-27T08:00:00+03:00'))
            raw['date'] = scope[0]
            raw['shopno_cluster_id'] = 5818
            for person in raw['couriers']:
                person['id'] = person.pop('courier_id')
            return {'items': [raw]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict('completion_reporting.FIRST_DAYS', {5818: '2026-10-26'}):
                # 25th: still working, tracked privately but not counted yet.
                first, _ = collect('2026-10-25', 5818, {'cluster_ids': []}, [night()], '', '', root, NOW)
                self.assertEqual(first['reason'], 'zero_denominator')
                # 27th: refresh older pending origin, not just the immediately previous day.
                with patch('completion_reporting.fetch', side_effect=response) as request:
                    result, _ = collect('2026-10-27', 5818, {'cluster_ids': []}, [], '', '', root, NOW)
                self.assertIn(('2026-10-25', 'shopno', 5818, 'limited'), [c.args[0] for c in request.call_args_list])
                self.assertEqual(result['value'], 100)
                self.assertEqual(result['denominator'], 1)
                self.assertEqual(result['basis'], BASIS)
                validate_metrics({'planned_completion': result})
