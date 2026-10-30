import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audit_corporate_vpn import network_metadata


class NetworkMetadataTests(unittest.TestCase):
    def test_extracts_networks_without_session_secrets(self):
        text = "PUSH: Received control message: 'PUSH_REPLY,dhcp-option DNS 10.0.0.53,route 10.20.0.0 255.255.0.0,auth-token PRIVATE-TOKEN,ifconfig 10.253.1.2 255.255.0.0'\nInitialization Sequence Completed"
        result = network_metadata(text)
        self.assertEqual(result['vpn_dns_ipv4'], ['10.0.0.53'])
        self.assertEqual(result['pushed_ipv4_networks'], ['10.20.0.0/16'])
        self.assertTrue(result['connected_in_log'])
        for secret in ('PRIVATE-TOKEN', 'auth-token', '10.253.1.2'):
            self.assertNotIn(secret, json.dumps(result))

    def test_rejects_bad_addresses_and_deduplicates(self):
        text = ',dhcp-option DNS 999.0.0.1,dhcp-option DNS 10.0.0.53,dhcp-option DNS 10.0.0.53,route 10.0.0.0 255.0.255.0,'
        result = network_metadata(text)
        self.assertEqual(result['vpn_dns_ipv4'], ['10.0.0.53'])
        self.assertEqual(result['pushed_ipv4_networks'], [])
        self.assertFalse(result['connected_in_log'])
