"""Private Windows credentials and a read-only NTLM check of the medical report."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlencode
from uuid import UUID

from prepare_openvpn import private_write
from probe_powerbi_vpn import HOST, REPORT_PATH, private_address

CREDENTIALS = Path('/root/courier-powerbi.json')
REPORT_ITEM_PATH = unquote(REPORT_PATH[len('/reports/powerbi'):])
CATALOG_PATH = '/reports/api/v2.0/PowerBIReports?' + urlencode({
    '$filter': "Path eq '" + REPORT_ITEM_PATH.replace("'", "''") + "'"})


def validate_credentials(saved):
    if not isinstance(saved, dict):
        raise ValueError('Invalid private credential file')
    username, password = saved.get('username'), saved.get('password')
    if not all(isinstance(v, str) and v and not any(ord(c) < 32 or ord(c) == 127 for c in v)
               for v in (username, password)):
        raise ValueError('Credentials must be nonempty and contain no control characters')
    if ':' in username or not ('\\' in username or '@' in username):
        raise ValueError('Use the full Windows login: DOMAIN\\user or user@domain')
    return {'username': username, 'password': password}


def load_credentials(path=CREDENTIALS):
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Private Power BI credentials missing or permissions broader than 600')
    return validate_credentials(json.loads(path.read_text()))


def save_credentials(path=CREDENTIALS, replace=False):
    if path.exists() and not replace:
        load_credentials(path)
        print('Existing private Power BI credentials retained.', flush=True)
        return
    saved = validate_credentials({
        'username': getpass.getpass('Full Windows login DOMAIN\\user (hidden): '),
        'password': getpass.getpass('Windows password (hidden): ')})
    private_write(path, json.dumps(saved, ensure_ascii=False))
    print('Power BI credentials saved privately with permissions 600.', flush=True)


def curl_credentials(saved):
    saved = validate_credentials(saved)
    value = saved['username'] + ':' + saved['password']
    value = value.replace('\\', '\\\\').replace('"', '\\"')
    return 'user = "' + value + '"\n'


def catalog_request(address, saved, folder):
    address = private_address(address)
    body = folder / 'catalog-response.json'
    private_write(body, '')
    # This is the report's original HTTP service, reached only via the corporate
    # VPN. NTLM supplies challenge/response authentication, never HTTP Basic.
    # Disable user curl defaults and redirects. Credentials travel on stdin only.
    command = ['curl', '--disable', '--config', '-', '--ntlm', '--http1.1',
               '--proxy', '', '--noproxy', '*', '--silent',
               '--connect-timeout', '5', '--max-time', '25',
               '--max-filesize', '2097152', '--resolve', f'{HOST}:80:{address}',
               '--header', 'Accept: application/json', '--output', str(body),
               '--write-out', '%{http_code}', 'http://' + HOST + CATALOG_PATH]
    try:
        result = subprocess.run(command, input=curl_credentials(saved), capture_output=True,
                                text=True, timeout=30)
        code = result.stdout.strip()
        status = int(code) if re.fullmatch(r'[1-5][0-9]{2}', code) else None
        data = None
        if result.returncode == 0 and status == 200 and body.stat().st_size <= 2097152:
            try:
                data = json.loads(body.read_text(encoding='utf-8-sig'))
            except (ValueError, UnicodeError):
                pass
        return {'curl_exit': result.returncode, 'http_status': status}, data
    except subprocess.TimeoutExpired:
        return {'curl_exit': 28, 'http_status': None}, None
    finally:
        body.unlink(missing_ok=True)


def report_metadata(data):
    rows = data.get('value') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    matches = [row for row in rows if isinstance(row, dict) and row.get('Path') == REPORT_ITEM_PATH]
    if len(matches) != 1:
        return None
    row = matches[0]
    try:
        identity = str(UUID(row.get('Id')))
    except (ValueError, TypeError, AttributeError):
        return None
    return {'id': identity, 'path': REPORT_ITEM_PATH,
            'name': row.get('Name') if isinstance(row.get('Name'), str) else None}


def check_login(address, folder, credentials_path=CREDENTIALS,
                metadata_path=Path('/opt/courier-analytics/private/powerbi-report-metadata.json')):
    saved = load_credentials(credentials_path)
    result, data = catalog_request(address, saved, folder)
    metadata = report_metadata(data) if result['curl_exit'] == 0 and result['http_status'] == 200 else None
    print('Power BI authenticated catalog: ' + json.dumps({**result,
          'medical_report_found': metadata is not None}), flush=True)
    if metadata is not None:
        metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_write(metadata_path, json.dumps(metadata, ensure_ascii=False))
        print('Medical report metadata saved privately. No courier rows read; metric 10 unchanged.', flush=True)
    return metadata is not None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--save', action='store_true')
    parser.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise ValueError('Run on the VPS as root')
        if not args.save:
            raise ValueError('Use --save to configure credentials; run the VPN probe to test login')
        save_credentials(replace=args.replace)
    except (ValueError, OSError, EOFError):
        raise SystemExit('Credential configuration failed; private details hidden.')
