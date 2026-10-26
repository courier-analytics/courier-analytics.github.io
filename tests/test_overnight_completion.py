from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from overnight_completion import match_end, resolve

NOW = datetime.fromisoformat('2026-10-26T14:00:00+03:00')


class OvernightTests(unittest.TestCase):
    def test_only_same_person_and_same_shift_start_can_supply_end(self):
        original = {'courier_id': '1', 'shift_start': '2026-10-25T20:47:00+03:00'}
        valid = {**original, 'shift_end': '2026-10-26T08:00:00+03:00', 'shift_status': 'Опоздал'}
        self.assertEqual(match_end(original, [valid], NOW)[0], valid['shift_end'])
        other_shift = {**valid, 'shift_start': '2026-10-26T06:00:00+03:00'}
        self.assertIsNone(match_end(original, [other_shift], NOW)[0])
        self.assertIsNone(match_end(original, [{**valid, 'courier_id': '2'}], NOW)[0])
        conflicting = {**valid, 'shift_end': '2026-10-26T07:00:00+03:00'}
        self.assertIsNone(match_end(original, [valid, conflicting], NOW)[0])

    def test_fetch_next_day_same_scope_and_preserve_original(self):
        slot = {'date': '2026-10-25', 'time_from': '20:00', 'time_to': '08:00',
                'slot_id': 29158, 'slot_type': 'limited', 'scope_kind': 'shopno', 'scope_id': 5818,
                'couriers': [{'courier_id': '1', 'shift_status': 'Опоздал',
                              'shift_start': '2026-10-25T20:47:00+03:00', 'shift_end': None}]}
        response = {'items': [{'date': '2026-10-26', 'slot_id': 30000, 'slot_type': 'manual',
                              'shopno_cluster_id': 5818, 'couriers': [{'id': '1',
                              'shift_status': 'Вышел', 'shift_start': '2026-10-25T20:47:00+03:00',
                              'shift_end': '2026-10-26T08:00:00+03:00'}]}]}
        with patch('overnight_completion.fetch', return_value=response) as request:
            result, report = resolve([slot], 'private', '', NOW)
        request.assert_called_once_with(('2026-10-26', 'shopno', 5818, 'all'), 'private', '')
        self.assertEqual(report['recovered_records'], 1)
        self.assertIsNone(slot['couriers'][0]['shift_end'])
        self.assertEqual(result[0]['couriers'][0]['shift_end_source_date'], '2026-10-26')
        with patch('overnight_completion.fetch') as request:
            resolve([slot], '', '', datetime.fromisoformat('2026-10-26T06:00:00+03:00'))
            request.assert_not_called()
