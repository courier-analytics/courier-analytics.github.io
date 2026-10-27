from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from find_server_proxy import acceptable, choose
from private_proxy_input import ImportProblem


class FindServerProxyTests(unittest.TestCase):
    def test_timeout_and_unauthenticated_401_are_distinguished(self):
        self.assertFalse(acceptable({'curl_exit': 28, 'anonymous_http_status': '000'}))
        self.assertFalse(acceptable({'curl_exit': 0, 'anonymous_http_status': '503'}))
        self.assertTrue(acceptable({'curl_exit': 0, 'anonymous_http_status': '401'}))

    def test_failed_first_node_is_skipped_and_first_usable_node_selected(self):
        first, second = {'private': 'one'}, {'private': 'two'}
        with patch('find_server_proxy.probe_node', side_effect=[
                {'curl_exit': 28, 'anonymous_http_status': '000'},
                {'curl_exit': 0, 'anonymous_http_status': '401'}]), patch('builtins.print'):
            self.assertIs(choose([first, second], Path('xray'), Path('.')), second)

    def test_no_working_node_never_returns_a_candidate(self):
        with patch('find_server_proxy.probe_node', return_value={'curl_exit': 28, 'anonymous_http_status': '000'}), patch('builtins.print'):
            with self.assertRaises(ImportProblem):
                choose([{}], Path('xray'), Path('.'))
