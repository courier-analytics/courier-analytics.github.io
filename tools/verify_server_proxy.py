"""Read-only authenticated verification of every active DS scope via a candidate proxy."""
import argparse
import json
from pathlib import Path
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from audit_sources import audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', default='socks5h://127.0.0.1:18081')
    args = parser.parse_args()
    try:
        token = json.loads(Path('/root/curator-session.json').read_text())['token']
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        day = datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
        with tempfile.TemporaryDirectory(prefix='courier-proxy-verification-') as directory:
            result = audit(day, token, args.proxy, Path(directory), extra_details=False)
        if {s['shop_id'] for s in result['shops'] if s['scope_verified']} != {5818, 7745, 4747}:
            raise ValueError('Not all DS scopes verified')
        print('Candidate server proxy: authenticated API reads passed for all three DS and their clusters.')
    except (ValueError, OSError, KeyError, TypeError, RuntimeError):
        raise SystemExit('Candidate proxy/session verification failed; no active route changed; private responses hidden.')
