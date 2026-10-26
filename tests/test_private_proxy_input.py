import base64
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from private_proxy_input import parse_nodes, uri_node
from prepare_proxy_config import canonical_config

LINK = ('vless://11111111-1111-4111-8111-111111111111@example.com:443'
        '?security=reality&type=tcp&sni=example.com&pbk=public-test-key&sid=1234&flow=xtls-rprx-vision')


class PrivateProxyInputTests(unittest.TestCase):
    def test_uri_and_encoded_subscription_preserve_safe_loopback_config(self):
        node = uri_node(LINK)
        config = canonical_config(node)
        self.assertEqual(config['inbounds'][0]['listen'], '127.0.0.1')
        self.assertEqual(config['inbounds'][0]['port'], 18081)
        encoded = base64.b64encode((LINK+'\n'+LINK).encode()).decode()
        self.assertEqual(len(parse_nodes(encoded)), 2)
        self.assertEqual(node['streamSettings']['realitySettings']['serverName'], 'example.com')

    def test_disabled_tls_verification_and_bad_identity_rejected(self):
        for link in (LINK+'&allowInsecure=1', LINK.replace('reality', 'none'),
                     LINK.replace('11111111-1111-4111-8111-111111111111', 'bad-id')):
            with self.assertRaises(ValueError):
                uri_node(link)
