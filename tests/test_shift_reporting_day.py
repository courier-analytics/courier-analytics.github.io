from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from shift_reporting_day import reporting_day


class ReportingDateTests(unittest.TestCase):
    def test_actual_completion_date_not_start_or_expected_end_date(self):
        slot = {'date': '2026-10-25', 'time_from': '20:00', 'time_to': '08:00'}
        self.assertEqual(reporting_day(slot, {'shift_end': '2026-10-26T08:00:00+03:00'}), '2026-10-26')
        self.assertEqual(reporting_day(slot, {'shift_end': '2026-10-27T08:00:00+03:00'}), '2026-10-27')
        self.assertEqual(reporting_day(slot, {'shift_end': '2026-10-25T23:00:00+03:00'}), '2026-10-25')
        self.assertIsNone(reporting_day(slot, {'shift_end': None}))

    def test_moscow_date_at_utc_midnight_boundary(self):
        slot = {'date': '2026-10-25', 'time_from': '20:00', 'time_to': '08:00'}
        self.assertEqual(reporting_day(slot, {'shift_end': '2026-10-25T22:00:00Z'}), '2026-10-26')
