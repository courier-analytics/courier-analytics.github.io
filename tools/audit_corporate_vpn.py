"""Read only VPN network metadata for Superset; never print raw profile/log data."""
import ipaddress
import json
from pathlib import Path
import re
import socket

SUPERSET_HOST = 'superset.svc.vkusvill.ru'
LOGS = ('/root/courier-openvpn-tcp-test.log', '/root/courier-openvpn-test.log')


def network_metadata(text):
    dns, routes = set(), set()
    # Parse individual pushed directives, never the full PUSH_REPLY (may contain auth-token).
    for match in re.finditer(r'(?:^|[,\s])dhcp-option\s+DNS\s+(\d+(?:\.\d+){3})(?=[,\s\x27]|$)', text):
        try:
            dns.add(str(ipaddress.IPv4Address(match[1])))
        except ValueError:
            pass
    for match in re.finditer(r'(?:^|,)route\s+(\d+(?:\.\d+){3})\s+(\d+(?:\.\d+){3})(?=[,\s\x27]|$)', text):
        try:
            network = ipaddress.IPv4Network(match[1] + '/' + match[2], strict=False)
            routes.add(str(network))
        except ValueError:
            pass
    return {'vpn_dns_ipv4': sorted(dns), 'pushed_ipv4_networks': sorted(routes),
            'connected_in_log': 'Initialization Sequence Completed' in text}


def main():
    report = {'vpn_auth_file_present': Path('/root/courier-openvpn.auth').is_file(),
              'tcp_candidate_present': Path('/root/courier-openvpn-tcp-candidate.conf').is_file(),
              'logs': []}
    for name in LOGS:
        path = Path(name)
        if path.is_file():
            report['logs'].append({'file': path.name, **network_metadata(path.read_text(errors='replace'))})
    try:
        report['superset_system_dns_ipv4'] = sorted({r[4][0] for r in socket.getaddrinfo(
            SUPERSET_HOST, 443, socket.AF_INET, socket.SOCK_STREAM)})
    except OSError:
        report['superset_system_dns_ipv4'] = []
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Read-only audit. No VPN started; no DNS, routes, credentials or timers changed.')
    print('Historical log metadata does not prove current VPN connectivity.')


if __name__ == '__main__':
    try:
        main()
    except OSError:
        raise SystemExit('Cannot read local metadata; private details hidden.')
