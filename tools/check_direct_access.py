"""Read-only API connectivity diagnostics. No session, tokens or route changes."""
import json
import os
import shutil
import socket
import subprocess

HOST = 'couriers-schedules.vkusvill.ru'
URL = 'https://' + HOST + '/v1/shops'


def probe(address, tls12=False):
    command = ['curl', '--proxy', '', '--noproxy', '*', '--silent', '--show-error',
               '--connect-timeout', '4', '--max-time', '8', '--output', '/dev/null',
               '--resolve', f'{HOST}:443:{address}', '--write-out', '%{json}']
    if tls12:
        command += ['--tlsv1.2', '--tls-max', '1.2', '--http1.1']
    result = subprocess.run(command + [URL], capture_output=True, text=True, timeout=12)
    try:
        metrics = json.loads(result.stdout)
    except ValueError:
        metrics = {}
    return {'address': address, 'mode': 'TLS1.2_HTTP1.1' if tls12 else 'default',
            'curl_exit': result.returncode,
            **{key: metrics.get(key) for key in (
                'http_code', 'time_connect', 'time_appconnect', 'time_total',
                'remote_ip', 'ssl_verify_result')},
            'error': result.stderr.strip()[:350]}


if __name__ == '__main__':
    print('Proxy variable names present (values hidden):',
          [name for name in ('http_proxy', 'https_proxy', 'all_proxy',
                             'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY') if os.environ.get(name)])
    print('All probes explicitly bypass proxies; TLS verification stays enabled.')
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(
            HOST, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)})
    except OSError:
        raise SystemExit('DNS lookup failed')
    print('Resolved IPv4 addresses:', addresses)
    for address in addresses[:4]:
        if shutil.which('ip'):
            route = subprocess.run(['ip', '-4', 'route', 'get', address],
                                   capture_output=True, text=True, timeout=5)
            print('Route:', route.stdout.strip())
        for tls12 in (False, True):
            try:
                print(json.dumps(probe(address, tls12), ensure_ascii=False), flush=True)
            except subprocess.TimeoutExpired:
                print(json.dumps({'address': address, 'error': 'probe process timeout'}), flush=True)
