from pathlib import Path
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from superset_access import api, NoRedirect, login_diagnostic, check_protected_endpoints, dataset_structure


class SupersetAccessTests(unittest.TestCase):
    def test_login_payload_not_in_url_and_https_kept(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"access_token":"private"}'
        code, data = api(opener, '/api/v1/security/login', {'password': 'secret'})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://superset.svc.vkusvill.ru/api/v1/security/login')
        self.assertNotIn('secret', request.full_url)
        self.assertEqual(code, 200)
        self.assertEqual(data['access_token'], 'private')

    def test_http_error_body_not_exposed(self):
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError('url', 401, 'hidden', {}, None)
        self.assertEqual(api(opener, '/api/v1/me/'), (401, None))

    def test_redirect_does_not_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'http://other.example'))


class LoginDiagnosticTests(unittest.TestCase):
    def test_provider_validation_without_echoing_secrets(self):
        diagnostic = login_diagnostic({'message': {'provider': ['must be db; private-password'],
                                                  'username': ['private-login']}})
        self.assertEqual(diagnostic['validation_fields'], ['provider', 'username'])
        self.assertNotIn('private', json.dumps(diagnostic))

    def test_csrf_category_without_raw_message(self):
        self.assertTrue(login_diagnostic({'message': 'CSRF private cookie'})['csrf_related'])
        self.assertEqual(login_diagnostic(None)['validation_fields'], [])


class ProtectedEndpointTests(unittest.TestCase):
    @patch('superset_access.api')
    def test_identity_failure_does_not_skip_dataset(self, call):
        call.side_effect = [(401, {'message': 'private'}), (200, {'result': 'private-csrf'}),
                            (200, {'result': {'id': 6856}})]
        opener = MagicMock(); opener.addheaders = []
        with patch('builtins.print') as output:
            self.assertTrue(check_protected_endpoints(opener, 'private-token'))
        self.assertEqual(call.call_count, 3)
        self.assertNotIn('private', str(output.call_args_list))

    @patch('superset_access.api', return_value=(401, {'message': 'unauthorized'}))
    def test_all_protected_failures_not_authenticated(self, call):
        with patch('builtins.print'):
            self.assertFalse(check_protected_endpoints(MagicMock(), 'private-token'))


class DatasetSchemaTests(unittest.TestCase):
    def test_schema_excludes_sql_rows_and_owner_identity(self):
        source = {'table_name': 'schedule', 'sql': 'private-sql', 'owners': ['private-owner'],
                  'data': ['private-row'], 'columns': [{'column_name': 'shift_end', 'type': 'DATETIME',
                  'is_dttm': True, 'expression': 'private-expression'}],
                  'metrics': [{'metric_name': 'count', 'expression': 'private-sql'}]}
        result = dataset_structure(6856, source)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(result['columns'][0]['name'], 'shift_end')
        self.assertEqual(result['metrics'], ['count'])
