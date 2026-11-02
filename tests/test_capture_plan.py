from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from capture_plan import freeze, in_capture_window, write_immutable


class PlanTests(unittest.TestCase):
    def test_frozen_snapshot_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'plan.json'
            write_immutable(path, {'first': True})
            with self.assertRaises(FileExistsError):
                write_immutable(path, {'second': True})
            self.assertEqual(path.read_text().strip(), '{\n  "first": true\n}')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
    def test_moscow_window_and_midnight_rejection(self):
        self.assertTrue(in_capture_window(datetime.fromisoformat('2026-10-26T20:59:10+00:00'), '2026-10-27'))
        self.assertFalse(in_capture_window(datetime.fromisoformat('2026-10-26T21:00:00+00:00'), '2026-10-27'))
        data = {'scope_config': {}, 'shops': [{'shop_id': 5818, 'slots': []}]}
        with self.assertRaises(ValueError):
            freeze(data, datetime.fromisoformat('2026-10-26T20:59:10+00:00'),
                   datetime.fromisoformat('2026-10-26T21:00:01+00:00'), '2026-10-27')

    def test_audit_rejects_falsely_dated_or_out_of_window_plan(self):
        import json
        from check_plan_capture import load_plan
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'plan.json'
            self.assertIsNone(load_plan(path, '2026-11-01'))
            data = {'date': '2026-11-01', 'verified': True, 'shops': [],
                    'started_at': '2026-10-31T20:59:00+00:00',
                    'completed_at': '2026-10-31T20:59:45+00:00'}
            path.write_text(json.dumps(data))
            self.assertTrue(load_plan(path, '2026-11-01')['verified'])
            data['completed_at'] = '2026-10-31T21:00:01+00:00'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_plan(path, '2026-11-01')

    def test_transient_connection_retry_stays_inside_capture_window(self):
        import json
        from unittest.mock import patch
        from capture_plan import collect
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            now = lambda: datetime.fromisoformat('2026-10-31T20:59:20+00:00')
            data = {'scope_config': {}, 'shops': [{'shop_id': 5818, 'slots': []},
                                                     {'shop_id': 7745, 'slots': []}]}
            def success(*args, **kwargs):
                (folder/'all-shops-observations.json').write_text(json.dumps(data))
            calls = []
            def flaky(*args, **kwargs):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError('API connection failed (curl 35)')
                success()
            with patch('capture_plan.audit', side_effect=flaky) as audit:
                result = collect('2026-11-01', 'hidden', 'socks5h://127.0.0.1:18081', folder,
                                 now=now, pause=lambda seconds: None)
                self.assertTrue(result['verified'])
                self.assertEqual(audit.call_count, 2)
            with patch('capture_plan.audit') as audit:
                with self.assertRaises(ValueError):
                    collect('2026-11-01', 'hidden', '', folder,
                            now=lambda: datetime.fromisoformat('2026-10-31T21:00:00+00:00'))
                audit.assert_not_called()

    def test_freeze_contains_ids_not_personal_details(self):
        data = {'scope_config': {}, 'shops': [{'shop_id': 5818, 'slots': [{
            'date': '2026-10-27', 'slot_id': 1, 'slot_type': 'limited',
            'time_from': '07:00', 'time_to': '19:00',
            'couriers': [{'courier_id': '11', 'name': 'private', 'phone': 'private'}]}]}]}
        result = freeze(data, datetime.fromisoformat('2026-10-26T20:59:00+00:00'),
                        datetime.fromisoformat('2026-10-26T20:59:10+00:00'), '2026-10-27')
        self.assertEqual(result['shops'][0]['slots'][0]['couriers'], [{'courier_id': '11'}])
