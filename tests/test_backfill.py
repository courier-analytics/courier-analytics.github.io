from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from backfill_dashboard import manual_history, needed, select_rows, BASE
from calculate_metrics import metric


class BackfillTests(unittest.TestCase):
    def test_real_manual_history_has_correct_shop_start_and_preserves_entered_values(self):
        manual = manual_history(Path(__file__).resolve().parents[1])
        work = needed({'records': []}, manual, '2026-10-26')
        self.assertEqual(work[5818, '2026-10-08'], {'planned_completion'})
        self.assertNotIn((7745, '2026-10-17'), work)
        self.assertEqual(work[7745, '2026-10-18'], {'slot_fill'})
        self.assertEqual(work[4747, '2026-10-21'], {'slot_fill', 'planned_completion'})
        for shop in (5818, 7745, 4747):
            self.assertEqual(work[shop, '2026-10-23'], {'slot_fill', 'shift_marked', 'planned_attendance', 'planned_late', 'planned_completion'})
        self.assertNotIn((8092, '2026-10-25'), work)
        self.assertEqual(work[8092, '2026-10-26'], {'slot_fill', 'shift_marked', 'planned_attendance', 'planned_late', 'planned_completion'})

    def test_zero_denominator_is_a_complete_answer_not_a_missing_day(self):
        row = {'shop_id': 5818, 'date': '2026-10-26', 'metrics': {
            'slot_fill': metric(0, 0, basis='limited_slot_places'),
            'shift_marked': metric(0, 0, basis=BASE)}}
        row['metrics'].update(planned_attendance=metric(0, 0, basis='current_limited_bookings_unique_couriers'),
                              planned_late=metric(0, 0, basis='current_limited_bookings_unique_couriers'))
        row['metrics']['planned_completion'] = metric(0, 0, basis='slot_completion_by_actual_night_end_date')
        work = needed({'records': [row]}, {(5818, '2026-10-26'): set(),
            (7745, '2026-10-26'): set(), (4747, '2026-10-26'): set()}, '2026-10-26')
        self.assertNotIn((5818, '2026-10-26'), work)

    def test_select_preserves_manual_plan_and_prior_slot_fill(self):
        old = {'shop_id': 5818, 'date': '2026-10-25', 'booked_places': 5,
               'capacity': 10, 'fill_percent': 50,
               'metrics': {'planned_late': metric(1, 2, basis='frozen_plan_unique_couriers')}}
        row = {**old, 'booked_places': 8, 'fill_percent': 80, 'metrics': {
            'slot_fill': metric(8, 10, basis='limited_slot_places'),
            'shift_marked': metric(4, 10, basis=BASE),
            'planned_attendance': metric(reason='frozen_plan_missing'),
            'planned_late': metric(reason='frozen_plan_missing')}}
        out = select_rows({'records': [row]}, {'records': [old]},
                          {(5818, '2026-10-25'): {'planned_attendance'}},
                          {(5818, '2026-10-25'): {'shift_marked'}}, '2026-10-25')['records'][0]
        self.assertNotIn('planned_attendance', out['metrics'])
        self.assertEqual(out['metrics']['planned_late']['value'], 50)
        self.assertEqual(out['fill_percent'], 50)
        self.assertNotIn('slot_fill', out['metrics'])

    def test_partial_required_source_stops_publication(self):
        with self.assertRaises(ValueError):
            select_rows({'records': []}, {'records': []}, {},
                        {(5818, '2026-10-25'): {'slot_fill'}}, '2026-10-25')
