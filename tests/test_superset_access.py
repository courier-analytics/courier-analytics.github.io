from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import urllib.error
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from superset_access import api, NoRedirect


class SupersetAccessTests(unittest.TestCase):
    def test_login_payload_not_in_url_and_https_kept(self):
        opener = Mock()
        opener.open.return_value.__enter__.return_value.status = 200
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"access_token":"private"}'
        code, data = api(opener, '/api/v1/security/login', {'password': 'secret'})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://superset.svc.vkusvill.ru/api/v1/security/login')
        self.assertNotIn('secret', request.full_url)
        self.assertEqual(code, 200)
        self.assertEqual(data['access_token'], 'private')

    def test_http_error_body_not_exposed(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError('url', 401, 'hidden', {}, None)
        self.assertEqual(api(opener, '/api/v1/me/'), (401, None))

    def test_redirect_does_not_forward_credentials(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'http://other.example'))
