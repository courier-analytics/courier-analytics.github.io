from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from prepare_openvpn import candidate
from probe_powerbi_vpn import private_address, response_metadata, probe, REPORT_PATH


class PowerBIAccessTests(unittest.TestCase):
    def test_only_corporate_destination_is_routed(self):
        profile = 'client\ndev tun\nremote vpn.example 443\nproto tcp-client\nauth-user-pass\nredirect-gateway def1\nroute 10.0.0.0 255.0.0.0\ndhcp-option DNS 10.1.0.1\n'
        config, _ = candidate(profile, [private_address('10.20.30.40')], Path('/root/vpn.auth'))
        self.assertIn('route 10.20.30.40 255.255.255.255 vpn_gateway', config)
        self.assertNotIn('redirect-gateway', config)
        self.assertNotIn('route 10.0.0.0', config)
        self.assertNotIn('dhcp-option', config)

    def test_rejects_public_loopback_link_local_and_injected_addresses(self):
        for value in ('147.90.10.158', '127.0.0.1', '169.254.1.1', '100.64.0.1',
                      '10.0.0.1\nroute 0.0.0.0', '::1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                private_address(value)

    def test_credentials_in_challenges_are_never_returned(self):
        raw = 'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: NTLM secret-token\r\nWWW-Authenticate: Negotiate another-secret\r\nSet-Cookie: session=secret\r\n'
        self.assertEqual(response_metadata(raw), ['negotiate', 'ntlm'])
        self.assertEqual(response_metadata('WWW-Authenticate: Negotiate, NTLM\r\n'),
                         ['negotiate', 'ntlm'])

    @patch('probe_powerbi_vpn.subprocess.run')
    def test_probe_preserves_service_identity_and_tls_without_credentials(self, run):
        def response(command, **kwargs):
            Path(command[command.index('--dump-header') + 1]).write_text('WWW-Authenticate: NTLM hidden\n')
            self.assertIn('izb-dwh-ssrs01.izbenka.local:443:10.20.30.40', command)
            self.assertEqual(command[-1], 'https://izb-dwh-ssrs01.izbenka.local/reports/')
            for forbidden in ('-k', '--insecure', '--user', '--location', '--location-trusted'):
                self.assertNotIn(forbidden, command)
            return subprocess.CompletedProcess(command, 0, '401', '')
        run.side_effect = response
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            result = probe('10.20.30.40', 'https', '/reports/', folder)
            self.assertEqual(result['http_status'], 401)
            self.assertEqual(result['auth_schemes'], ['ntlm'])
            self.assertFalse((folder / 'response-headers').exists())

    @patch('probe_powerbi_vpn.subprocess.run', side_effect=subprocess.TimeoutExpired('curl', 16))
    def test_timeout_returns_diagnostic_and_removes_headers(self, run):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            result = probe('10.20.30.40', 'http', REPORT_PATH, folder)
            self.assertEqual(result['curl_exit'], 28)
            self.assertIsNone(result['http_status'])
            self.assertFalse((folder / 'response-headers').exists())

    @patch('probe_powerbi_vpn.subprocess.run')
    def test_unexpected_endpoint_rejected_before_network_request(self, run):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                probe('10.20.30.40', 'http', '/arbitrary-endpoint', Path(directory))
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
