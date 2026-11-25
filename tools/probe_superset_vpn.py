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


def wait_for_idle_vpn(seconds=0):
    """Wait for other jobs; never terminate or attach to their VPN process."""
    if type(seconds) is not int or not 0<=seconds<=600:
        raise ValueError('VPN wait must be between 0 and 600 seconds')
    deadline=time.monotonic()+seconds
    announced=False
    while True:
        existing=subprocess.run(['pgrep','-x','openvpn'],capture_output=True)
        if existing.returncode==1:return
        if existing.returncode!=0:raise ValueError('Could not check existing VPN process')
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise ValueError('VPN is busy; export not started. No existing process was stopped.')
        if not announced:
            print('VPN is busy; waiting up to '+str(seconds)+' seconds for the current job to finish.',flush=True)
            announced=True
        time.sleep(min(5,remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-vpn',type=int,default=0,help='Wait up to 600 seconds for an existing VPN job, without stopping it')
    parser.add_argument('--ziz-services',nargs=2,metavar=('FROM','TO'),help='Distinct DS9107 ZIZ/service pairs for one or two calendar days')
    parser.add_argument('--pay-couriers',type=int,nargs='+',help='Private payroll type export for specified courier IDs')
    parser.add_argument('--staffing-shop',type=int,choices=(7745,8889,9107),help='Export one staffing shop instead of the default pair')
    parser.add_argument('--collect-staffing',action='store_true',help='Private paginated workforce export for weeks 910-914')
    parser.add_argument('--compare-order-ids',action='store_true',help='Read-only Matryoshka order ID comparison')
    parser.add_argument('--reconcile-matryoshka',action='store_true',help='Compare native delivered counts by date and courier type; no sends')
    parser.add_argument('--collect-matryoshka',action='store_true',help='Collect explicitly assigned Matryoshka participants; no sends')
    parser.add_argument('--matryoshka-history',action='store_true',help='Private all-company history diagnostic; no alerts')
    parser.add_argument('--inspect-matryoshka',action='store_true',help='Private courier discovery for three pilot shops; no alerts')
    parser.add_argument('--inspect-datasets', action='store_true', help='Read dataset schemas, no rows or SQL')
    parser.add_argument('--provider', choices=('ldap', 'db'), help='Override Superset provider for this test only')
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
    from shared_vpn_resource import acquire
    vpn_lease=acquire()
    wait_for_idle_vpn(args.wait_vpn)
    with tempfile.TemporaryDirectory(prefix='courier-superset-', dir='/root') as folder:
        folder = Path(folder)
        path, log = folder/'candidate.conf', folder/'private.log'
        private_write(path, config)
        private_write(log, '')
        worker = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=5s', ('600s' if args.collect_staffing else '120s'),
            'openvpn', '--config', str(path), '--log', str(log), '--verb', '3'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            print('Temporary VPN test, maximum '+('605' if args.collect_staffing else '125')+' seconds. Profile and log remain private.', flush=True)
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
                success = check_login(args.provider, args.inspect_datasets, args.inspect_matryoshka, args.matryoshka_history, args.collect_matryoshka, args.reconcile_matryoshka, args.collect_staffing, args.staffing_shop, args.pay_couriers, args.ziz_services, args.compare_order_ids)
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
