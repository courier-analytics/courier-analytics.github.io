import base64
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from private_proxy_input import parse_nodes, uri_node, read_nodes, ImportProblem
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

    def test_wrapped_base64_and_multiple_json_nodes(self):
        encoded = base64.b64encode(LINK.encode()).decode()
        wrapped = '\n'.join(encoded[i:i+40] for i in range(0, len(encoded), 40))
        self.assertEqual(len(parse_nodes(wrapped)), 1)
        self.assertEqual(len(parse_nodes(json.dumps([{'outbounds': [uri_node(LINK), uri_node(LINK)]}]))), 2)

    def test_safe_diagnostics_do_not_expose_private_input(self):
        for value, code in [('happ://crypt4/private-secret', 'encrypted_happ_link'),
                            ('<html>private-secret</html>', 'subscription_returned_html'),
                            ('not-a-private-secret', 'not_vless_json')]:
            with self.assertRaises(ImportProblem) as caught:
                read_nodes(value)
            self.assertIn(code, str(caught.exception))
            self.assertNotIn('private-secret', str(caught.exception))
