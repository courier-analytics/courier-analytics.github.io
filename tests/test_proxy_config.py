import base64
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from prepare_proxy_config import canonical_config
from download_xray import verified_binary


def node():
    return {'protocol': 'vless', 'tag': 'from-happ', 'sendThrough': 'utun4',
            'settings': {'vnext': [{'address': 'example.com', 'port': 443,
                'users': [{'id': '11111111-1111-4111-8111-111111111111',
                           'encryption': 'none', 'flow': 'xtls-rprx-vision'}]}]},
            'streamSettings': {'network': 'tcp', 'security': 'reality',
                'sockopt': {'interface': 'utun4'},
                'realitySettings': {'serverName': 'example.com', 'fingerprint': 'chrome',
                    'publicKey': base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
                    'shortId': '12345678'}}}


class ProxyConfigTests(unittest.TestCase):
    def test_loopback_only_and_preserved_identity(self):
        exported = {'inbounds': [{'listen': '0.0.0.0', 'port': 9999}],
                    'routing': {'rules': ['do not copy']}, 'outbounds': [node(), {'protocol': 'freedom'}]}
        config = canonical_config(exported)
        self.assertEqual(config['inbounds'][0]['listen'], '127.0.0.1')
        self.assertEqual(config['inbounds'][0]['port'], 18081)
        self.assertNotIn('routing', config)
        self.assertNotIn('sendThrough', config['outbounds'][0])
        self.assertNotIn('sockopt', config['outbounds'][0]['streamSettings'])
        self.assertEqual(config['outbounds'][0]['settings'], node()['settings'])

    def test_multiple_nodes_and_insecure_tls_rejected(self):
        with self.assertRaises(ValueError):
            canonical_config({'outbounds': [node(), node()]})
        unsafe = node()
        unsafe['streamSettings']['realitySettings']['allowInsecure'] = True
        with self.assertRaises(ValueError):
            canonical_config(unsafe)

    def test_chained_proxy_rejected(self):
        exported = node()
        exported['proxySettings'] = {'tag': 'missing'}
        with self.assertRaises(ValueError):
            canonical_config(exported)

    def test_server_private_key_rejected(self):
        exported = node()
        exported['streamSettings']['realitySettings']['privateKey'] = 'do-not-transfer'
        with self.assertRaises(ValueError):
            canonical_config(exported)

    def test_unverified_artifact_rejected(self):
        with self.assertRaises(ValueError):
            verified_binary(b'not an official verified binary')
