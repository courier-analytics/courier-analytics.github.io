from datetime import datetime
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from calculate_metrics import current_slot_completion
from build_dashboard_feed import validate_metrics

NOW = datetime.fromisoformat('2026-10-26T14:00:00+03:00')


def slot(end='2026-10-25T15:00:00+03:00', identity='1', state='Вышел раньше на час'):
    return {'date': '2026-10-25', 'time_from': '06:00', 'time_to': '16:00',
            'couriers': [{'courier_id': identity, 'shift_status': state, 'shift_end': end}]}


class CompletionTests(unittest.TestCase):
    def test_user_card_one_hour_early_is_not_completed(self):
        result = current_slot_completion([slot()], NOW)
        self.assertEqual((result['numerator'], result['denominator'], result['value']), (0, 1, 0))
        validate_metrics({'planned_completion': result})

    def test_tolerance_and_all_slots_per_unique_courier(self):
        done = slot('2026-10-25T15:50:00+03:00')
        self.assertEqual(current_slot_completion([done, done], NOW)['value'], 100)
        self.assertEqual(current_slot_completion([done, slot()], NOW)['value'], 0)

    def test_night_shift_uses_next_day_and_waits_until_finished(self):
        night = slot('2026-10-26T07:55:00+03:00')
        night.update(time_from='20:00', time_to='08:00')
        self.assertEqual(current_slot_completion([night], NOW)['value'], 100)
        self.assertIsNone(current_slot_completion([night], datetime.fromisoformat('2026-10-26T07:00:00+03:00'))['value'])

    def test_missing_end_never_implies_failed_or_finished(self):
        for end in (None, 'invalid', '2026-10-25T16:00:00'):
            result = current_slot_completion([slot(end)], NOW)
            self.assertIsNone(result['value'])
            self.assertEqual(result['reason'], 'shift_end_or_final_status_missing')
        self.assertEqual(current_slot_completion([slot(None, state='Не вышел')], NOW)['value'], 0)

    def test_empty_population_has_no_percentage(self):
        self.assertEqual(current_slot_completion([], NOW)['reason'], 'zero_denominator')
