import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from probe_superset_vpn import wait_for_idle_vpn

class VpnWaitTests(unittest.TestCase):
    @patch('probe_superset_vpn.time.sleep')
    @patch('probe_superset_vpn.subprocess.run',return_value=SimpleNamespace(returncode=1))
    def test_free_vpn_starts_without_wait(self,run,sleep):
        wait_for_idle_vpn(600);sleep.assert_not_called()
        run.assert_called_once_with(['pgrep','-x','openvpn'],capture_output=True)

    @patch('probe_superset_vpn.time.sleep')
    @patch('probe_superset_vpn.subprocess.run')
    def test_busy_then_free_only_checks_and_waits(self,run,sleep):
        run.side_effect=[SimpleNamespace(returncode=0),SimpleNamespace(returncode=1)]
        wait_for_idle_vpn(600)
        sleep.assert_called_once()
        self.assertTrue(all(call.args[0]==['pgrep','-x','openvpn'] for call in run.call_args_list))

    @patch('probe_superset_vpn.subprocess.run',return_value=SimpleNamespace(returncode=0))
    def test_default_does_not_overlap(self,run):
        with self.assertRaises(ValueError):wait_for_idle_vpn()

    @patch('probe_superset_vpn.subprocess.run')
    def test_invalid_limits_do_not_check_or_modify_processes(self,run):
        for limit in (-1,601,True,'600'):
            with self.assertRaises(ValueError):wait_for_idle_vpn(limit)
        run.assert_not_called()
