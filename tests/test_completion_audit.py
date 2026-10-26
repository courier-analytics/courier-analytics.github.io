from pathlib import Path
import sys
import unittest
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_completion import blockers


class CompletionAuditTests(unittest.TestCase):
    def test_identify_missing_timezone_and_absent_end_without_pii(self):
        slot = {'date': '2026-10-25', 'time_from': '06:00', 'time_to': '16:00',
                'slot_type': 'limited', 'slot_id': 1, 'scope_kind': 'shopno', 'scope_id': 5818,
                'couriers': [{'courier_id': '1', 'name': 'Hidden', 'shift_status': 'Вышел', 'shift_end': None},
                             {'courier_id': '2', 'shift_status': 'Опоздал', 'shift_end': '2026-10-25T16:00:00'},
                             {'courier_id': '3', 'shift_status': 'Не вышел', 'shift_end': None}]}
        result = blockers([slot], datetime.fromisoformat('2026-10-26T16:00:00+03:00'))
        self.assertEqual([r['reason'] for r in result], ['shift_end_missing', 'shift_end_timezone_missing'])
        self.assertNotIn('Hidden', str(result))
        self.assertNotIn('name', str(result))
