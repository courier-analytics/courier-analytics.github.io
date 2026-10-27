from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from verify_server_proxy import network_probe, error_code
from enrich_slots import ApiError


class ServerProxyDiagnosticsTests(unittest.TestCase):
    def test_anonymous_401_is_a_reachable_api_not_an_expired_session(self):
        with patch('verify_server_proxy.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '401', '')) as run:
            self.assertEqual(network_probe('socks5h://127.0.0.1:18081'), {'curl_exit': 0, 'anonymous_http_status': '401'})
            self.assertNotIn('--header', run.call_args.args[0])

    def test_error_codes_exclude_private_responses(self):
        self.assertEqual(error_code(ApiError(401)), 'authenticated_api_http_401')
        self.assertEqual(error_code(RuntimeError('API connection failed (curl 97)')), 'authenticated_connection_curl_97')
        self.assertNotIn('secret', error_code(ValueError('secret contents')))
