from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from report_tomorrow import totals, reports


class ReportTests(unittest.TestCase):
    def test_manual_and_duplicates_do_not_inflate_unique_or_capacity(self):
        slots = [{'slot_type': 'limited', 'capacity': 3, 'occupied': 1, 'couriers': [{'courier_id': '1'}]},
                 {'slot_type': 'manual', 'capacity': 0, 'occupied': 0, 'couriers': [{'courier_id': '1'}, {'courier_id': '2'}]}]
        t = totals(slots)
        self.assertEqual((t['capacity'], t['booked_places'], t['unique_couriers'], t['manual_records']), (3, 1, 2, 2))
        self.assertEqual(t['vacancies'], 2)

    def test_missing_shop_not_zero(self):
        a, b = reports('2026-10-31', 'now', [{'shop_id': 8889, 'available': False, 'reason': 'shop_missing_from_catalogue'}])
        self.assertIn('данные недоступны', a)
        self.assertIn('не нулевой план', b)

    def test_overbooked_is_not_negative_vacancy(self):
        t = totals([{'slot_type': 'limited', 'capacity': 1, 'occupied': 2, 'couriers': [{'courier_id': '1'}, {'courier_id': '2'}]}])
        self.assertEqual((t['vacancies'], t['overbooked_places']), (0, 1))

    def test_inconsistent_source_fails(self):
        with self.assertRaises(ValueError):
            totals([{'slot_type': 'limited', 'capacity': 2, 'occupied': 2, 'couriers': []}])
