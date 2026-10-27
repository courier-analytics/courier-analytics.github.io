"""Read-only authenticated verification of every active DS scope via a candidate proxy."""
import argparse
import json
import re
import subprocess
from pathlib import Path
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from audit_sources import audit
from enrich_slots import ApiError


def network_probe(proxy):
    try:
        result = subprocess.run(['curl', '--proxy', proxy, '--noproxy', '',
            '--silent', '--show-error', '--connect-timeout', '8', '--max-time', '18',
            '--output', '/dev/null', '--write-out', '%{http_code}',
            'https://couriers-schedules.vkusvill.ru/v1/shops'],
            capture_output=True, text=True, timeout=22)
        return {'curl_exit': result.returncode,
                'anonymous_http_status': result.stdout.strip() if result.stdout.strip().isdigit() else None}
    except subprocess.TimeoutExpired:
        return {'curl_exit': 28, 'anonymous_http_status': None}


def error_code(error):
    if isinstance(error, ApiError):
        return 'authenticated_api_http_'+str(error.status)
    match = re.fullmatch(r'API connection failed \(curl (\d+)\)', str(error))
    if match:
        return 'authenticated_connection_curl_'+match[1]
    match = re.fullmatch(r'API application error (\d+); response hidden', str(error))
    if match:
        return 'authenticated_api_application_'+match[1]
    return 'source_format_or_local_configuration_error'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', default='socks5h://127.0.0.1:18081')
    args = parser.parse_args()
    try:
        probe = network_probe(args.proxy)
        print('Anonymous network probe: '+json.dumps(probe), flush=True)
        if probe['curl_exit']:
            raise SystemExit('Candidate server proxy network failed (curl '+str(probe['curl_exit'])+'); no active route changed.')
        token = json.loads(Path('/root/curator-session.json').read_text())['token']
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        day = datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
        with tempfile.TemporaryDirectory(prefix='courier-proxy-verification-') as directory:
            result = audit(day, token, args.proxy, Path(directory), extra_details=False)
        verified = {s['shop_id'] for s in result['shops'] if s['scope_verified']}
        print('DS verification: '+json.dumps([{'shop_id': s['shop_id'],
            'verified': s['scope_verified'], 'reason': s.get('reason')}
            for s in result['shops']]), flush=True)
        # New/unavailable 8092 must not prevent restoring the three previously
        # working DS. Its lack of access remains explicit, never a fake zero.
        if not {5818, 7745, 4747}.issubset(verified):
            raise ValueError('Not all DS scopes verified')
        print('Candidate server proxy: authenticated API reads passed for '+str(len(verified))+' available DS and their clusters.')
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        raise SystemExit('Candidate verification failed: '+error_code(error)+'. No active route changed; private responses hidden.')
