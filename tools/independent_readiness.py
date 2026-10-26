"""Safe local session and anonymous internal Power BI connectivity diagnostics."""
import json
from pathlib import Path
import socket
import urllib.error
import urllib.request

HOST = 'izb-dwh-ssrs01'


def probe(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    headers, status = None, None
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'courier-readiness'}), timeout=8) as response:
            headers, status = response.headers, response.status
    except urllib.error.HTTPError as error:
        headers, status = error.headers, error.code
    except (OSError, ValueError):
        return {'url': url, 'reachable': False, 'note': 'connection_or_tls_verification_failed'}
    challenge = ','.join(headers.get_all('WWW-Authenticate', []))
    return {'url': url, 'reachable': True, 'http_status': status,
            'auth_schemes': [scheme for scheme in ('Negotiate', 'NTLM', 'Bearer') if scheme.lower() in challenge.lower()],
            'content_type': headers.get('Content-Type', '').split(';')[0]}


if __name__ == '__main__':
    report = {'session': {}, 'power_bi': {}}
    try:
        saved = json.loads(Path('/root/curator-session.json').read_text())
        report['session'] = {'token_present': bool(saved.get('token')),
                             'refresh_credential_present': any(bool(saved.get(k)) for k in ('refresh_token', 'refreshToken'))}
    except (OSError, ValueError, TypeError):
        report['session'] = {'readable': False}
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(HOST, 80, family=socket.AF_INET)})
        report['power_bi']['dns_resolves'] = bool(addresses)
        report['power_bi']['probes'] = [probe(f'{scheme}://{HOST}{path}')
            for scheme, path in [('http', '/reports/'), ('https', '/reports/'),
                                 ('http', '/reports/api/v2.0/PowerBIReports')]]
    except OSError:
        report['power_bi'] = {'dns_resolves': False, 'note': 'corporate_dns_or_vpn_required'}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('No passwords, tokens or report data printed. HTTP probes are anonymous; HTTPS verification stays enabled.')
