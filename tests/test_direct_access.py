from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_direct_access import probe


class DirectAccessTests(unittest.TestCase):
    def test_probe_bypasses_proxy_and_preserves_certificate_verification(self):
        completed = subprocess.CompletedProcess([], 0,
            '{"http_code":401,"time_connect":0.1,"time_appconnect":0.2,"url_effective":"hidden"}', '')
        with patch('check_direct_access.subprocess.run', return_value=completed) as run:
            result = probe('193.238.178.52', True)
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('--proxy')+1], '')
        self.assertEqual(command[command.index('--noproxy')+1], '*')
        self.assertNotIn('--insecure', command)
        self.assertNotIn('-k', command)
        self.assertIn('--tls-max', command)
        self.assertEqual(result['http_code'], 401)
        self.assertNotIn('url_effective', result)
