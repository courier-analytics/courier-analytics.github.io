"""Freeze tomorrow's booked slots during the agreed 23:59 Moscow window."""
import argparse
from proxy_config import configured_proxy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

from audit_sources import audit
from verify_server_proxy import error_code

MOSCOW = ZoneInfo('Europe/Moscow')


def in_capture_window(now, target_day):
    local = now.astimezone(MOSCOW)
    return (local.date()+timedelta(days=1)).isoformat() == target_day and local.hour == 23 and local.minute == 59


def freeze(observations, started, completed, day):
    if not in_capture_window(started, day) or not in_capture_window(completed, day):
        raise ValueError('Plan collection outside the 23:59 Moscow window')
    if completed < started:
        raise ValueError('Invalid snapshot time range')
    shops = []
    for shop in observations['shops']:
        slots = []
        for slot in shop['slots']:
            if slot['date'] != day:
                raise ValueError('Wrong plan day')
            slots.append({key: slot[key] for key in ('date', 'slot_id', 'slot_type', 'time_from', 'time_to')})
            slots[-1]['couriers'] = [{'courier_id': c['courier_id']} for c in slot['couriers']]
        shops.append({'shop_id': shop['shop_id'], 'slots': slots})
    if not shops:
        raise ValueError('No verified scopes to snapshot')
    return {'schema_version': 1, 'verified': True, 'date': day,
            'started_at': started.isoformat(), 'completed_at': completed.isoformat(),
            'scope_config': observations['scope_config'], 'shops': shops}


def write_immutable(path, result):
    fd, temporary = tempfile.mkstemp(prefix='.plan-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Atomic creation without replacing an existing frozen snapshot.
        os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(day, token, proxy, folder, check_only=False, now=None, pause=time.sleep):
    now = now or (lambda: datetime.now(timezone.utc))
    for attempt in range(1, 4):
        started = now()
        if not check_only and not in_capture_window(started, day):
            raise ValueError('Plan collection outside the 23:59 Moscow window')
        try:
            audit(day, token, proxy, folder, extra_details=False)
            observations = json.loads((folder/'all-shops-observations.json').read_text())
            if not {5818, 7745}.issubset({s['shop_id'] for s in observations['shops']}):
                raise ValueError('Both dashboard DS must be available for plan collection')
            if check_only:
                return observations
            return freeze(observations, started, now(), day)
        except RuntimeError as error:
            code = error_code(error)
            retryable = code in {'authenticated_connection_curl_'+str(n) for n in (5, 6, 7, 28, 35, 52, 56)} or code in {
                'authenticated_api_http_502', 'authenticated_api_http_503', 'authenticated_api_http_504'}
            print('Plan source attempt: '+json.dumps({'attempt': attempt, 'error': code}), flush=True)
            if not retryable or attempt == 3 or (not check_only and not in_capture_window(now(), day)):
                raise RuntimeError('Plan source unavailable: '+code) from None
            pause(2)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=configured_proxy())
    parser.add_argument('--private-dir', type=Path, default=Path('/opt/courier-analytics/private'))
    parser.add_argument('--check-connection', action='store_true', help='Read tomorrow via the same route now; never freeze a plan')
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    day = (started.astimezone(MOSCOW).date()+timedelta(days=1)).isoformat()
    if not args.check_connection and not in_capture_window(started, day):
        raise SystemExit('Plan capture is allowed only at 23:59 Moscow; no historical plan invented.')
    directory = args.private_dir/'plans'
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory/('plan-'+day+'.json')
    if not args.check_connection and path.exists():
        raise SystemExit('Plan already frozen; existing file preserved.')
    token = json.loads(args.session.read_text())['token']
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise SystemExit('Invalid session')
    with tempfile.TemporaryDirectory(prefix='.plan-', dir=directory) as temporary:
        temporary = Path(temporary)
        result = collect(day, token, args.proxy, temporary, check_only=args.check_connection)
        if not args.check_connection:
            write_immutable(path, result)
    if args.check_connection:
        print('Tomorrow plan API read passed; no plan frozen; date:', day,
              '; shops:', [s['shop_id'] for s in result['shops']])
    else:
        print('Plan frozen for', day, '; shops:', [s['shop_id'] for s in result['shops']])
