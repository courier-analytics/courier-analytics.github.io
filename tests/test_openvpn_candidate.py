import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from prepare_openvpn import candidate, private_write

PROFILE = '''client
dev tun
proto udp
remote vpn.example 1194
auth-user-pass
redirect-gateway def1
route 10.0.0.0 255.0.0.0
dhcp-option DNS 10.0.0.1
<ca>
PRIVATE EXAMPLE CERTIFICATE
</ca>
'''

class CandidateTests(unittest.TestCase):
    def test_limits_routes_and_preserves_certificate(self):
        result, auth = candidate(PROFILE, ['193.238.178.52'], Path('/root/test.auth'))
        self.assertTrue(auth)
        self.assertIn('PRIVATE EXAMPLE CERTIFICATE', result)
        self.assertNotIn('redirect-gateway', result)
        self.assertNotIn('route 10.', result)
        self.assertNotIn('dhcp-option', result)
        self.assertIn('route-nopull', result)
        self.assertIn('route 193.238.178.52 255.255.255.255 vpn_gateway', result)
        self.assertIn('auth-user-pass /root/test.auth', result)

    def test_rejects_executable_options_and_external_keys(self):
        for option in ['up /tmp/script', 'plugin /tmp/plugin.so', 'management 0.0.0.0 1234', 'config /tmp/config', 'key /tmp/key']:
            with self.subTest(option=option), self.assertRaises(ValueError):
                candidate(PROFILE + option + '\n', ['193.238.178.52'], Path('/root/test.auth'))

    def test_private_atomic_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'candidate.conf'
            private_write(path, 'first')
            path.chmod(0o644)
            private_write(path, 'second')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), 'second')

    def test_rejects_incomplete_profile(self):
        with self.assertRaises(ValueError):
            candidate(PROFILE.replace('</ca>', ''), ['193.238.178.52'], Path('/root/test.auth'))
