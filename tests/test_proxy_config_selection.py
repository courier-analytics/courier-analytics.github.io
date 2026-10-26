import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from proxy_config import configured_proxy


class ProxySelectionTests(unittest.TestCase):
    def test_manual_tools_use_same_route_as_services(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder)/'proxy.env'
            self.assertEqual(configured_proxy(path), 'socks5h://127.0.0.1:18080')
            path.write_text('COURIER_PROXY_URL=socks5h://127.0.0.1:18081\n')
            self.assertEqual(configured_proxy(path), 'socks5h://127.0.0.1:18081')
            with patch.dict(os.environ, {'COURIER_PROXY_URL': 'socks5h://127.0.0.1:19000'}):
                self.assertEqual(configured_proxy(path), 'socks5h://127.0.0.1:19000')

    def test_config_is_not_executed_and_embedded_credentials_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder)/'proxy.env'
            path.write_text('COURIER_PROXY_URL=$(echo secret)')
            with self.assertRaises(ValueError):
                configured_proxy(path)
            path.write_text('COURIER_PROXY_URL=http://user:password@example.com')
            with self.assertRaises(ValueError):
                configured_proxy(path)
