import json
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from roster_client import normalize, RosterError, one_c_token, request, own_session_name
from calculate_metrics import calculate


class RosterTests(unittest.TestCase):
    def test_name_from_own_token_matches_site(self):
        segment = base64.urlsafe_b64encode(json.dumps({'full_name': 'Own Name'}).encode()).decode().rstrip('=')
        self.assertEqual(own_session_name('eyJheader.'+segment+'.signature'), 'Own Name')
        self.assertIsNone(own_session_name('invalid'))
        self.assertIsNone(own_session_name('header.e30.signature'))

    def test_auth_error_identifies_stage_without_response_body(self):
        with patch('roster_client.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'private response\n401'
            for path, stage in [('/delivery/v1/courier/courier', 'own_profile'),
                                ('/auth/api/v1/couriers/auth/1c', 'one_c_login'),
                                ('/delivery/v1/couriers?shopno=5818', 'assigned_couriers')]:
                with self.assertRaisesRegex(RosterError, '^'+stage+'_http_401$'):
                    request(path, {}, '')

    def test_unique_ids_and_scope(self):
        result = normalize({'items': [{'id': '12', 'shopno': 5818}, {'id': '12'}]}, 5818)
        self.assertEqual(result['courier_ids'], ['12'])
        self.assertEqual(result['duplicate_rows'], 1)
        with self.assertRaises(RosterError):
            normalize([{'id': '12', 'shopno': 7745}], 5818)
        with self.assertRaises(RosterError):
            normalize({'items': [{'id': '12'}], 'total': 2}, 5818)

    def test_only_assigned_people_count_in_numerator(self):
        slots = [{'date': '2026-10-26', 'slot_type': 'limited', 'capacity': 3, 'couriers': [
            {'courier_id': '11'}, {'courier_id': '99'}]}]
        result = calculate(slots, '2026-10-26', roster={
            'verified': True, 'courier_ids': ['11', '12']})
        self.assertEqual(result['shift_marked']['value'], 50)

    def test_auth_uses_own_profile_and_private_cache(self):
        calls = []
        token = 'eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjk5OTk5OTk5OTl9.signature'
        def fake(path, headers, proxy, form_file=None):
            calls.append(path)
            if path.endswith('/courier/courier'):
                return {'name_courier': 'Own Profile'}
            self.assertEqual(form_file.read_text(), 'Own Profile')
            self.assertEqual(form_file.stat().st_mode & 0o777, 0o600)
            return {'token': token}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'source.js'
            source.write_text('function Oq(){return`public-client-key`}')
            cache = root/'session.json'
            with patch('roster_client.request', side_effect=fake):
                self.assertEqual(one_c_token('primary', '', cache, source), token)
                self.assertEqual(one_c_token('primary', '', cache, source), token)
                self.assertEqual(len(calls), 2)
                one_c_token('different-primary', '', cache, source)
                self.assertEqual(len(calls), 4)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('Own Profile', cache.read_text())

    def test_headers_stdin_and_tls_enabled(self):
        with patch('roster_client.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '[]\n200'
            request('/delivery/v1/couriers?shopno=5818', {'Authorization': 'Bearer secret'}, '')
            args, kwargs = run.call_args
            self.assertNotIn('secret', ' '.join(args[0]))
            self.assertIn('Bearer secret', kwargs['input'])
            self.assertNotIn('--insecure', args[0])
            self.assertNotIn('--location', args[0])
