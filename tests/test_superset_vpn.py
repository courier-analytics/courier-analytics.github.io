from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from probe_superset_vpn import vpn_config, health_probe


class SupersetVPNTests(unittest.TestCase):
    def test_routes_only_superset_not_original_default(self):
        profile = 'client\ndev tun\nremote vpn.example 443\nproto tcp-client\nauth-user-pass\nredirect-gateway def1\nroute 10.0.0.0 255.0.0.0\n'
        config, auth = vpn_config(profile, ['10.210.254.19'], Path('/root/vpn.auth'))
        self.assertTrue(auth)
        self.assertIn('route 10.210.254.19 255.255.255.255 vpn_gateway', config)
        self.assertIn('route-nopull', config)
        self.assertNotIn('redirect-gateway', config)
        self.assertNotIn('route 10.0.0.0', config)
        self.assertNotIn('193.238.', config)

    @patch('probe_superset_vpn.subprocess.run')
    def test_pins_host_preserves_tls_and_bypasses_proxy(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '200', '')
        result = health_probe('10.210.254.19')
        command = run.call_args.args[0]
        self.assertIn('superset.svc.vkusvill.ru:443:10.210.254.19', command)
        self.assertIn('https://superset.svc.vkusvill.ru/health', command)
        self.assertEqual(command[command.index('--proxy')+1], '')
        self.assertNotIn('-k', command)
        self.assertNotIn('--insecure', command)
        self.assertEqual(result['http_status'], '200')

    @patch('probe_superset_vpn.subprocess.run', side_effect=subprocess.TimeoutExpired('curl', 16))
    def test_timeout_returns_safe_diagnostic(self, run):
        self.assertEqual(health_probe('10.210.254.19')['curl_exit'], 28)
