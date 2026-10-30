"""Temporary OpenVPN test for Superset. No permanent network or collector changes."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time

from prepare_openvpn import candidate, private_write

HOST = 'superset.svc.vkusvill.ru'


def vpn_config(profile, addresses, auth):
    # Reuse strict option validation, replacing only the destination host routes.
    return candidate(profile, addresses, auth)


def health_probe(address):
    command = ['curl', '--proxy', '', '--noproxy', '*', '--silent',
               '--connect-timeout', '8', '--max-time', '12',
               '--resolve', f'{HOST}:443:{address}', '--output', '/dev/null',
               '--write-out', '%{http_code}', f'https://{HOST}/health']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=16)
        return {'address': address, 'curl_exit': result.returncode,
                'http_status': result.stdout.strip() if result.stdout.strip().isdigit() else None}
    except subprocess.TimeoutExpired:
        return {'address': address, 'curl_exit': 28, 'http_status': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-login', action='store_true', help='Verify saved Superset credentials while VPN is connected')
    parser.add_argument('--profile', type=Path, default=Path('/root/courier-openvpn-tcp.ovpn'))
    parser.add_argument('--auth', type=Path, default=Path('/root/courier-openvpn.auth'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Run as root on the VPS')
    if not args.auth.is_absolute() or any(c.isspace() for c in str(args.auth)):
        raise ValueError('Invalid auth path')
    addresses = sorted({r[4][0] for r in socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM)})
    if len(addresses) > 4:
        raise ValueError('Too many destination addresses; review required')
    config, needs_auth = vpn_config(args.profile.read_text(), addresses, args.auth)
    if needs_auth and (not args.auth.is_file() or args.auth.stat().st_mode & 0o077):
        raise ValueError('VPN auth file missing or permissions too broad; require 600')
    # Refuse overlapping tests instead of mistaking an existing tunnel for success.
    existing = subprocess.run(['pgrep', '-x', 'openvpn'], capture_output=True)
    if existing.returncode != 1:
        raise ValueError('Another OpenVPN process exists; stop/review it before testing')
    with tempfile.TemporaryDirectory(prefix='courier-superset-', dir='/root') as folder:
        folder = Path(folder)
        path, log = folder/'candidate.conf', folder/'private.log'
        private_write(path, config)
        private_write(log, '')
        worker = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=5s', '120s',
            'openvpn', '--config', str(path), '--log', str(log), '--verb', '3'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            print('Temporary VPN test, maximum 125 seconds. Profile and log remain private.', flush=True)
            deadline = time.monotonic() + 60
            connected = False
            while time.monotonic() < deadline:
                text = log.read_text(errors='replace')
                if 'Initialization Sequence Completed' in text:
                    connected = True
                    break
                if worker.poll() is not None or 'AUTH_FAILED' in text:
                    break
                time.sleep(.5)
            if not connected:
                text = log.read_text(errors='replace')
                print(json.dumps({'vpn_connected': False, 'auth_failed': 'AUTH_FAILED' in text,
                    'tls_error': 'TLS Error' in text, 'certificate_error': 'VERIFY ERROR' in text}))
                return 1
            print('VPN connected. Superset destination routes only; TLS verification enabled.', flush=True)
            probes = [health_probe(address) for address in addresses]
            for result in probes:
                print(json.dumps(result), flush=True)
            success = bool(probes) and all(p['curl_exit'] == 0 and p['http_status'] == '200' for p in probes)
            print('Superset health: ' + ('PASSED' if success else 'not confirmed'))
            if success and args.check_login:
                from superset_access import check_login
                success = check_login()
                print('Superset authentication: ' + ('PASSED' if success else 'not confirmed'))
            return 0 if success else 1
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
            print('Temporary VPN stopped. Collector, timers and system DNS unchanged.', flush=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(str(error))
    except (OSError, subprocess.SubprocessError):
        raise SystemExit('Local network/process/file error; private details hidden.')
