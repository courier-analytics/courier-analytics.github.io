"""Compare unauthenticated 1C routes. No passwords or browser cookies used."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

HOST = 'couriers.int.vkusvill.ru'
BASE = '/couriers/ru_RU/'
ADDRESS = '10.210.254.19'


def check(interface=None):
    result = {'host': HOST, 'target_address': ADDRESS, 'requests': []}
    with tempfile.TemporaryDirectory(prefix='onec-route-') as directory:
        folder = Path(directory)
        cookies = folder/'cookies'
        cookies.touch(mode=0o600)
        version = None
        for name in ('entry', 'loader', 'auth_settings'):
            if name != 'entry' and version is None:
                break
            path = BASE if name == 'entry' else BASE + (
                'scripts/mod_main_loader.js?sysver='+version if name == 'loader' else
                'e1cib/additionalAuthSettings?sysver='+version)
            headers, body = folder/'headers', folder/'body'
            headers.touch(mode=0o600, exist_ok=True)
            body.touch(mode=0o600, exist_ok=True)
            cmd = ['curl', '--disable', '--proxy', '', '--noproxy', '*', '--silent',
                '--connect-timeout', '8', '--max-time', '25', '--max-filesize', '12000000',
                '--resolve', HOST+':443:'+ADDRESS, '--cookie', str(cookies),
                '--cookie-jar', str(cookies), '--dump-header', str(headers),
                '--output', str(body), '--write-out', '%{http_code}',
                '--header', 'Accept: application/json' if name == 'auth_settings' else 'Accept: */*']
            if interface:
                cmd += ['--interface', interface]
            if name == 'auth_settings':
                cmd += ['--request', 'POST', '--header', 'Content-Type: application/json; charset=utf-8', '--data-binary', '']
            cmd.append('https://'+HOST+path)
            response = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = body.read_bytes()
            item = {'stage': name, 'curl_exit': response.returncode,
                    'http_status': response.stdout.strip() if response.stdout.strip().isdigit() else None}
            result['requests'].append(item)
            if response.returncode or response.stdout.strip() != '200':
                continue
            if name == 'entry':
                match = re.search(rb'var\s+VERSION\s*=\s*["\']([0-9.]{1,40})["\']', data)
                version = match[1].decode() if match else None
                item['version'] = version
                item['sha256'] = hashlib.sha256(data).hexdigest()
            elif name == 'loader':
                item['sha256'] = hashlib.sha256(data).hexdigest()
            else:
                try:
                    payload = json.loads(data)
                    item['json_object'] = isinstance(payload, dict)
                    if isinstance(payload, dict):
                        allowed = {'cred', 'showHelpURL', 'helpURL', 'showPasswordRecoveryURL', 'passwordRecoveryURL', 'sendMail'}
                        item['recognized_keys'] = sorted(set(payload) & allowed)
                        item['other_key_count'] = len(set(payload) - allowed)
                        item['has_auth_challenge'] = isinstance(payload.get('cred'), str) and bool(payload['cred'])
                except (ValueError, UnicodeError):
                    item['json_object'] = False
    print('1C route comparison: '+json.dumps(result), flush=True)
    return all(row['curl_exit'] == 0 and row['http_status'] == '200' for row in result['requests']) and len(result['requests']) == 3


if __name__ == '__main__':
    try:
        raise SystemExit(0 if check() else 1)
    except (ValueError, OSError, subprocess.SubprocessError):
        raise SystemExit('1C route comparison failed; response details hidden.')
