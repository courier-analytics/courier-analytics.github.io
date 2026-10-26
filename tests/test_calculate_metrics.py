from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from calculate_metrics import calculate, period


def slot(identity=1, kind='limited', people=None):
    return {'date': '2026-10-26', 'slot_id': identity, 'slot_type': kind,
            'time_from': '07:00', 'time_to': '19:00', 'capacity': 3,
            'couriers': people if people is not None else [
                {'courier_id': '11', 'shift_status': 'Вышел', 'shift_end': '2026-10-26T19:00:00+03:00'},
                {'courier_id': '12', 'shift_status': 'Опоздал на 15 минут', 'shift_end': None}]}


class MetricTests(unittest.TestCase):
    def test_no_retrospective_plan_guess(self):
        result = calculate([slot()], '2026-10-26')
        self.assertEqual(result['slot_fill']['value'], 66.67)
        self.assertIsNone(result['planned_attendance']['value'])
        self.assertEqual(result['planned_attendance']['reason'], 'frozen_plan_missing')

    def test_roster_counts_people_not_slots(self):
        result = calculate([slot(), slot(2)], '2026-10-26',
                           roster={'verified': True, 'courier_ids': ['11', '12', '13', '14']})
        self.assertEqual(result['shift_marked']['value'], 50)
        self.assertEqual(result['shift_marked']['numerator'], 2)

    def test_arrival_late_and_manual_work_against_frozen_plan(self):
        planned = slot()
        manual = slot(2, 'manual', [{'courier_id': '13', 'shift_status': 'Вышел', 'shift_end': None}])
        result = calculate([planned, manual], '2026-10-26',
                           plan={'date': '2026-10-26', 'verified': True, 'slots': [deepcopy(planned)]})
        self.assertEqual(result['planned_attendance']['value'], 100)
        self.assertEqual(result['planned_late']['value'], 50)
        self.assertEqual(result['unplanned_work']['value'], 33.33)
        self.assertIsNone(result['planned_completion']['value'])

    def test_missing_planned_courier_not_treated_as_no_show(self):
        original = slot()
        current = slot(people=original['couriers'][:1])
        result = calculate([current], '2026-10-26',
                           plan={'date': '2026-10-26', 'verified': True, 'slots': [original]})
        self.assertEqual(result['planned_attendance']['reason'], 'planned_booking_missing_from_current_data')

    def test_overnight_and_source_ten_minute_completion_tolerance(self):
        planned = slot(people=[{'courier_id': '11', 'shift_status': 'Вышел',
                               'shift_end': '2026-10-27T00:51:00+03:00'}])
        planned.update(time_from='19:00', time_to='01:00')
        self.assertEqual(period(planned)[1].date().isoformat(), '2026-10-27')
        result = calculate([planned], '2026-10-26',
                           plan={'date': '2026-10-26', 'verified': True, 'slots': [deepcopy(planned)]})
        self.assertEqual(result['planned_completion']['value'], 100)
