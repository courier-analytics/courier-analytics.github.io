"""Power BI access test through a temporary corporate VPN on the VPS."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import quote

from prepare_openvpn import candidate, private_write

HOST = 'izb-dwh-ssrs01.izbenka.local'
REPORT_PATH = '/reports/powerbi/' + quote('Управления_ВВ/Последняя_миля/ЛМК Курьеров', safe='/')
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(n) for n in
                         ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def private_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError('Power BI address must be a corporate private IPv4 address')
    return str(address)


def response_metadata(headers):
    # Authentication headers can contain opaque credentials: retain scheme names only.
    challenges = re.findall(r'^WWW-Authenticate:\s*([^\r\n]+)', headers,
                            flags=re.IGNORECASE | re.MULTILINE)
    schemes = [scheme for challenge in challenges for scheme in re.findall(
        r'(?:^|,)\s*(Negotiate|NTLM|Basic|Bearer)\b', challenge, flags=re.IGNORECASE)]
    return sorted({scheme.lower() for scheme in schemes})


def probe(address, scheme, path, folder):
    address = private_address(address)
    if scheme not in ('http', 'https') or path not in ('/reports/', REPORT_PATH,
                                                     '/reports/api/v2.0/PowerBIReports'):
        raise ValueError('Unexpected probe endpoint')
    headers = folder / 'response-headers'
    private_write(headers, '')
    port = 443 if scheme == 'https' else 80
    command = ['curl', '--proxy', '', '--noproxy', '*', '--silent',
               '--connect-timeout', '5', '--max-time', '12',
               '--resolve', f'{HOST}:{port}:{address}',
               '--dump-header', str(headers), '--output', '/dev/null',
               '--write-out', '%{http_code}', f'{scheme}://{HOST}{path}']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=16)
        code = result.stdout.strip()
        status = int(code) if re.fullmatch(r'[1-5][0-9]{2}', code) else None
        auth = response_metadata(headers.read_text(errors='replace'))
        return {'scheme': scheme, 'endpoint': 'catalog' if 'api/v2.0' in path else
                ('report' if path == REPORT_PATH else 'portal'),
                'curl_exit': result.returncode, 'http_status': status,
                'auth_schemes': auth}
    except subprocess.TimeoutExpired:
        return {'scheme': scheme, 'curl_exit': 28, 'http_status': None,
                'auth_schemes': []}
    finally:
        headers.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, help='IPv4 resolved on the corporate network')
    parser.add_argument('--profile', type=Path, default=Path('/root/courier-openvpn-tcp.ovpn'))
    parser.add_argument('--auth', type=Path, default=Path('/root/courier-openvpn.auth'))
    parser.add_argument('--check-login', action='store_true', help='Check saved Windows credentials using NTLM')
    parser.add_argument('--save-login', action='store_true', help='Save missing Windows credentials with hidden input, then test them')
    parser.add_argument('--replace-login', action='store_true', help='Replace saved Windows credentials; requires --save-login')
    parser.add_argument('--inspect-model', action='store_true', help='Read report field references using saved Windows credentials; no data query')
    parser.add_argument('--collect-medical', action='store_true', help='Read shop aggregates and prepare a private validated LMK candidate; no publication')
    parser.add_argument('--shops', type=int, nargs='+', choices=(5818, 7745), default=[5818, 7745])
    parser.add_argument('--preflight', action='store_true', help='Check saved report structure locally before connecting; requires --collect-medical')
    parser.add_argument('--onec-probe', action='store_true', help='Inspect only the supplied 1C web login page; no authentication or courier queries')
    parser.add_argument('--onec-assets', action='store_true', help='Collect static login form resources; requires --onec-probe')
    parser.add_argument('--onec-login', action='store_true', help='Check the real 1C browser login with private saved credentials')
    parser.add_argument('--onec-save-login', action='store_true', help='Save missing 1C credentials using hidden prompts; requires --onec-login')
    parser.add_argument('--onec-replace-login', action='store_true', help='Replace 1C credentials using hidden prompts; requires --onec-login')
    parser.add_argument('--onec-route-check', action='store_true', help='Compare unauthenticated 1C entry, loader and auth-settings responses')
    parser.add_argument('--onec-inspect-ui', action='store_true', help='Save private interface screenshot and control labels after 1C login')
    parser.add_argument('--onec-inspect-roster', action='store_true', help='Open References/Couriers for private read-only interface inspection; requires --onec-login')
    args = parser.parse_args()
    address = private_address(args.address)
    if args.onec_inspect_roster:
        args.onec_inspect_ui = True
    if args.onec_inspect_ui and not args.onec_login:
        raise ValueError('--onec-inspect-ui requires --onec-login')
    if args.onec_route_check and (address != '10.210.254.19' or any((
            args.onec_probe, args.onec_assets, args.onec_login, args.onec_save_login,
            args.onec_replace_login, args.check_login, args.save_login, args.replace_login,
            args.inspect_model, args.collect_medical, args.preflight))):
        raise ValueError('Use only the confirmed 1C address and route-check action')
    if args.onec_assets and not args.onec_probe:
        raise ValueError('--onec-assets requires --onec-probe')
    if args.onec_save_login and not args.onec_login:
        raise ValueError('--onec-save-login requires --onec-login')
    if args.onec_replace_login and not args.onec_login:
        raise ValueError('--onec-replace-login requires --onec-login')
    if args.onec_login and (args.onec_probe or args.onec_assets):
        raise ValueError('Choose 1C inspection or browser login')
    if (args.onec_probe or args.onec_login) and any((args.check_login, args.save_login, args.replace_login,
                               args.inspect_model, args.collect_medical, args.preflight)):
        raise ValueError('1C page inspection cannot be combined with Power BI actions')
    if os.geteuid() != 0:
        raise ValueError('Run on the VPS as root')
    if args.preflight:
        if not args.collect_medical:
            raise ValueError('--preflight requires --collect-medical')
        from powerbi_medical import preflight
        if not preflight():
            return 1
    if not args.auth.is_absolute() or any(c.isspace() for c in str(args.auth)):
        raise ValueError('Invalid VPN auth file path')
    config, needs_auth = candidate(args.profile.read_text(), [address], args.auth)
    if needs_auth and (not args.auth.is_file() or args.auth.stat().st_mode & 0o077):
        raise ValueError('Saved VPN auth file missing or permissions broader than 600')
    if subprocess.run(['pgrep', '-x', 'openvpn'], capture_output=True).returncode != 1:
        raise ValueError('An OpenVPN process exists; review it before starting this test')
    if args.replace_login and not args.save_login:
        raise ValueError('--replace-login requires --save-login')
    if args.save_login:
        from powerbi_access import save_credentials
        save_credentials(replace=args.replace_login)
    if args.onec_login:
        try:
            import playwright.sync_api
        except ImportError:
            raise ValueError('Install the dedicated 1C browser runtime and run with its Python')
        from onec_browser import save_credentials, load_credentials
        if args.onec_save_login or args.onec_replace_login:
            save_credentials(replace=args.onec_replace_login)
        load_credentials()
    with tempfile.TemporaryDirectory(prefix='courier-powerbi-', dir='/root') as directory:
        folder = Path(directory)
        profile, log = folder / 'candidate.conf', folder / 'private.log'
        private_write(profile, config)
        private_write(log, '')
        worker = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=5s', '240s',
            'openvpn', '--config', str(profile), '--log', str(log), '--verb', '3'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            print('Temporary corporate VPN test; read-only requests, private data hidden.', flush=True)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                text = log.read_text(errors='replace')
                if 'Initialization Sequence Completed' in text:
                    break
                if worker.poll() is not None or 'AUTH_FAILED' in text:
                    break
                time.sleep(.5)
            text = log.read_text(errors='replace')
            if 'Initialization Sequence Completed' not in text:
                print(json.dumps({'vpn_connected': False, 'auth_failed': 'AUTH_FAILED' in text,
                    'tls_error': 'TLS Error' in text, 'certificate_error': 'VERIFY ERROR' in text}))
                return 1
            print('VPN connected; only the specified corporate IPv4 is routed through it.', flush=True)
            if args.onec_route_check:
                from onec_route_check import check
                from powerbi_access import corporate_interface
                return 0 if check(interface=corporate_interface(address)) else 1
            if args.onec_login:
                from onec_browser import check_login
                from playwright.sync_api import Error as BrowserError
                try:
                    return 0 if check_login(address, inspect_ui=args.onec_inspect_ui,
                                           inspect_roster=args.onec_inspect_roster) else 1
                except BrowserError:
                    raise ValueError('1C browser operation failed; private details hidden') from None
            if args.onec_probe:
                from onec_access import inspect_page
                return 0 if inspect_page(address, folder, assets=args.onec_assets) else 1
            results = [probe(address, scheme, path, folder) for scheme, path in
                       [('http', '/reports/'), ('http', REPORT_PATH),
                        ('http', '/reports/api/v2.0/PowerBIReports'), ('https', '/reports/')]]
            for result in results:
                print(json.dumps(result), flush=True)
            if args.check_login or args.save_login or args.inspect_model or args.collect_medical:
                from powerbi_access import check_login
                return 0 if check_login(address, folder, inspect_model=args.inspect_model,
                    collect_medical=args.collect_medical, medical_shops=tuple(args.shops)) else 1
            print('This test does not authenticate, export medical data, or update metric 10.', flush=True)
            return 0 if any(r['curl_exit'] == 0 and r['http_status'] for r in results) else 1
        finally:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=3)
            print('Temporary VPN stopped; system DNS, public proxy and dashboard jobs unchanged.', flush=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as error:
        raise SystemExit(str(error))
    except (OSError, EOFError, subprocess.SubprocessError):
        raise SystemExit('Local file, network or process error; private details hidden.')
