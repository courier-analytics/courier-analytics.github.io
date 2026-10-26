"""Convert one exported Xray VLESS node into a loopback-only SOCKS service."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from enrich_slots import atomic_json

PORT = 18081


def canonical_config(export):
    if not isinstance(export, dict):
        raise ValueError('Expected a JSON object exported for Xray')
    if export.get('protocol') == 'vless':
        choices = [export]
    else:
        choices = [o for o in export.get('outbounds', [])
                   if isinstance(o, dict) and o.get('protocol') == 'vless']
    if len(choices) != 1:
        raise ValueError('Export exactly one VLESS node, not the whole subscription')
    node = choices[0]
    if node.get('proxySettings'):
        raise ValueError('Chained outbounds are not supported')
    stream = deepcopy(node.get('streamSettings', {}))
    if stream.get('sockopt', {}).get('dialerProxy'):
        raise ValueError('Chained transport is not supported')
    # Do not copy Mac routing, inbound ports, DNS rules or interface bindings.
    stream.pop('sockopt', None)
    if stream.get('security') not in ('reality', 'tls'):
        raise ValueError('A TLS or Reality connection is required')
    def check_verification(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in ('allowinsecure', 'insecure', 'skipcertverify') and item is not False and item is not None:
                    raise ValueError('Disabled certificate verification is not allowed')
                check_verification(item)
        elif isinstance(value, list):
            for item in value:
                check_verification(item)
    check_verification(stream)
    if stream['security'] == 'reality':
        reality = stream.get('realitySettings', {})
        if reality.get('privateKey'):
            raise ValueError('Server-side private keys must not be exported here')
        if not reality.get('serverName') or not (reality.get('publicKey') or reality.get('password')):
            raise ValueError('Reality server name or public key is missing')
    settings = deepcopy(node.get('settings', {}))
    servers = settings.get('vnext')
    if not isinstance(servers, list) or len(servers) != 1:
        raise ValueError('Export must contain one remote VLESS server')
    server = servers[0]
    if not isinstance(server.get('address'), str) or not server['address'].strip():
        raise ValueError('Remote server address missing')
    if type(server.get('port')) is not int or not 1 <= server['port'] <= 65535:
        raise ValueError('Invalid remote server port')
    users = server.get('users')
    if not isinstance(users, list) or len(users) != 1 or not users[0].get('id'):
        raise ValueError('Export must contain one VLESS identity')
    outbound = {'tag': 'courier-proxy', 'protocol': 'vless',
                'settings': settings, 'streamSettings': stream}
    if node.get('mux'):
        outbound['mux'] = deepcopy(node['mux'])
    return {
        'log': {'loglevel': 'warning'},
        'inbounds': [{'tag': 'local-socks', 'listen': '127.0.0.1', 'port': PORT,
                      'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': False}}],
        'outbounds': [outbound],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 2_000_000:
            raise ValueError('Export file too large')
        result = canonical_config(json.loads(args.input.read_text()))
        atomic_json(args.output, result)
        print('Private SOCKS configuration prepared on 127.0.0.1:18081; secrets hidden.')
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit('Could not prepare proxy. Export one Xray VLESS JSON node with TLS verification enabled. No secrets printed.')
