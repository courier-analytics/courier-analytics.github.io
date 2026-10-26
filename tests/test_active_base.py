from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_active_base import summarize


class ActiveBaseTests(unittest.TestCase):
    def snapshots(self):
        return [{'date': (date(2026, 10, 26)-timedelta(days=n)).isoformat(), 'shops': [
            {'shop_id': 5818, 'slots': [{'couriers': [
                {'courier_id': '1', 'shift_status': 'Не вышел'},
                {'courier_id': str(2+n), 'shift_status': 'Вышел'}]}]}]} for n in range(5)]

    def test_deduplicate_and_distinguish_schedule_from_attendance(self):
        report = summarize(self.snapshots(), '2026-10-26')
        row = report['shops'][0]
        self.assertEqual(report['date_from'], '2026-10-22')
        self.assertEqual(row['scheduled_unique_5d'], 6)
        self.assertEqual(row['attendance_observed_unique_5d'], 5)
        self.assertEqual(row['with_slot_on_selected_day'], 2)
        self.assertFalse(report['shops'][1]['available'])

    def test_missing_or_repeated_day_is_rejected(self):
        observations = self.snapshots()
        with self.assertRaises(ValueError):
            summarize(observations[:4], '2026-10-26')
        observations[-1] = observations[0]
        with self.assertRaises(ValueError):
            summarize(observations, '2026-10-26')
