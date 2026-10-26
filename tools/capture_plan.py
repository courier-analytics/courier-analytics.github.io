"""Freeze tomorrow's booked slots during the agreed 23:59 Moscow window."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from audit_sources import audit

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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--private-dir', type=Path, default=Path('/opt/courier-analytics/private'))
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    day = (started.astimezone(MOSCOW).date()+timedelta(days=1)).isoformat()
    if not in_capture_window(started, day):
        raise SystemExit('Plan capture is allowed only at 23:59 Moscow; no historical plan invented.')
    directory = args.private_dir/'plans'
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory/('plan-'+day+'.json')
    if path.exists():
        raise SystemExit('Plan already frozen; existing file preserved.')
    token = json.loads(args.session.read_text())['token']
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise SystemExit('Invalid session')
    with tempfile.TemporaryDirectory(prefix='.plan-', dir=directory) as temporary:
        temporary = Path(temporary)
        audit(day, token, args.proxy, temporary, extra_details=False)
        data = json.loads((temporary/'all-shops-observations.json').read_text())
        result = freeze(data, started, datetime.now(timezone.utc), day)
        write_immutable(path, result)
    print('Plan frozen for', day, '; shops:', [s['shop_id'] for s in result['shops']])
